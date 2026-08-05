from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatAction
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
    Update,
    User as TelegramUser,
)
from sqlalchemy import select

from app.bot.states import (
    AdminAnnouncementStates,
    AdminCustomButtonStates,
    AdminMediaStates,
    AdminOfferImageStates,
    AdminProviderLogoStates,
    AdminWithdrawalStates,
    BotIssueStates,
    DirectSupportStates,
    PaymentProofStates,
    ProviderBrandingStates,
    ProviderGuideStates,
    ProviderPaymentMethodStates,
    ProviderSettlementProofStates,
    SupportStates,
    TemporaryLogoutStates,
)
from app.core.config import Settings
from app.domain.callback_compat import normalize_callback
from app.core.database import Database
from app.db.models import User
from app.services.container import Services
from app.services.platform_access import invalidate_provider_access_cache

logger = logging.getLogger(__name__)


FSM_CLEAR_CALLBACKS: frozenset[str] = frozenset()


class CallbackCompatibilityOuterMiddleware(BaseMiddleware):
    """Normalize versioned and legacy callback payloads before router matching.

    Telegram keeps old inline keyboards in chat history. This outer middleware
    runs before filters, so an append-only alias can preserve a historical
    button without duplicating handlers or weakening authorization checks.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Update) and event.callback_query is not None:
            normalized, version = normalize_callback(event.callback_query.data)
            data["callback_schema_version"] = version
            if normalized != event.callback_query.data:
                callback = event.callback_query.model_copy(update={"data": normalized})
                event = event.model_copy(update={"callback_query": callback})
        return await handler(event, data)


class CallbackNavigationStateMiddleware(BaseMiddleware):
    """Leave state transitions to the destination handlers.

    The previous implementation cleared FSM data before Home/Back destinations
    were resolved. A transient DB or Telegram failure could therefore erase a
    valid wizard while leaving the user on the old screen. Home/Cancel handlers
    now clear only after a destination was rendered successfully; Back moves one
    state up and keeps collected data. This middleware remains as a compatibility
    registration point and deliberately performs no mutation.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        return await handler(event, data)



class FSMInputValidationMiddleware(BaseMiddleware):
    """Reject empty or incompatible FSM input before state handlers run.

    This is a final safety net, not a replacement for domain validation inside
    handlers.  It prevents stickers, voice notes, empty text and wrong proof/logo
    attachments from falling through an active state and leaving the session
    apparently frozen.
    """

    _NAVIGATION_TEXTS = {
        "🏠 الرئيسية",
        "الرئيسية",
        "القائمة الرئيسية",
        "⬅️ رجوع",
        "↩️ رجوع",
        "رجوع",
        "❌ إلغاء العملية",
        "إلغاء",
        "الغاء",
        "إلغاء العملية",
    }
    _PHOTO_ONLY_STATES = {
        AdminOfferImageStates.image.state,
        AdminProviderLogoStates.logo.state,
        ProviderBrandingStates.logo.state,
        ProviderSettlementProofStates.proof.state,
    }
    _PHOTO_OR_URL_STATES: set[str] = set()
    _PHOTO_OR_DOCUMENT_STATES = {
        PaymentProofStates.proof_file.state,
        AdminWithdrawalStates.proof.state,
        TemporaryLogoutStates.proof.state,
    }
    _MEDIA_OR_TEXT_STATES = {
        ProviderGuideStates.step_content.state,
        AdminAnnouncementStates.body.state,
        AdminCustomButtonStates.content.state,
        BotIssueStates.attachment.state,
        SupportStates.ticket_message.state,
        DirectSupportStates.details.state,
        ProviderPaymentMethodStates.proof_guide.state,
    }
    _MEDIA_ONLY_STATES = {AdminMediaStates.file.state}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)
        state = data.get("state")
        current = await state.get_state() if state is not None else None
        if not current:
            return await handler(event, data)

        text = event.text
        clean_text = text.strip() if text is not None else ""
        if clean_text in self._NAVIGATION_TEXTS or clean_text.startswith("/"):
            return await handler(event, data)

        if current in self._PHOTO_ONLY_STATES and not event.photo:
            await event.answer("أرسل صورة فقط لهذه الخطوة، أو اضغط رجوع/الرئيسية للخروج.")
            return None
        if current in self._PHOTO_OR_URL_STATES:
            if event.photo:
                return await handler(event, data)
            if clean_text.startswith("https://") and len(clean_text) <= 2_000:
                return await handler(event, data)
            await event.answer("أرسل صورة واضحة أو رابط HTTPS صالح، ولا ترسل ملفًا من نوع آخر.")
            return None
        if current in self._PHOTO_OR_DOCUMENT_STATES:
            if event.photo or event.document:
                return await handler(event, data)
            await event.answer("أرسل صورة أو ملف الإثبات المطلوب فقط.")
            return None
        if current in self._MEDIA_ONLY_STATES:
            if event.photo or event.video or event.document:
                return await handler(event, data)
            await event.answer("أرسل صورة أو فيديو أو مستندًا صالحًا لهذه الخطوة.")
            return None
        if current in self._MEDIA_OR_TEXT_STATES:
            caption = (event.caption or "").strip()
            if clean_text or caption or event.photo or event.video or event.document:
                return await handler(event, data)
            await event.answer("أرسل نصًا واضحًا أو المرفق المطلوب لهذه الخطوة.")
            return None

        # All remaining FSM states are text-input states.  Rejecting arbitrary
        # attachments here keeps `(message.text or "")` handlers deterministic
        # and prevents a wrong sticker/file from looking like a frozen session.
        if event.photo or event.video or event.document or event.audio or event.voice or event.sticker:
            await event.answer("هذه الخطوة تقبل نصًا فقط. اكتب القيمة المطلوبة أو اضغط رجوع.")
            return None
        if not clean_text:
            await event.answer("لا يمكن قبول قيمة فارغة. اكتب البيانات بوضوح أو اضغط إلغاء.")
            return None
        if "\x00" in clean_text or len(clean_text) > 12_000:
            await event.answer("المدخل غير صالح أو أطول من الحد المسموح. اختصره ثم أرسله مجددًا.")
            return None
        return await handler(event, data)


class SessionMiddleware(BaseMiddleware):
    """Provide one transaction-scoped SQLAlchemy session per accepted update."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        services: Services,
        *,
        slow_warning_ms: int | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.services = services
        self.slow_warning_ms = max(
            100,
            int(slow_warning_ms or settings.slow_update_warning_ms),
        )

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        started = time.perf_counter()
        correlation_id = secrets.token_hex(4).upper()
        data["correlation_id"] = correlation_id
        async with self.database.session_factory() as session:
            session.info["campuspass_settings"] = self.settings
            data["session"] = session
            data["settings"] = self.settings
            data["services"] = self.services
            try:
                result = await handler(event, data)
                dirty_platform_auth = session.info.get("campuspass_platform_auth_dirty")
                await session.commit()
                if isinstance(dirty_platform_auth, dict):
                    invalidate_provider_access_cache(
                        telegram_ids=dirty_platform_auth.get("telegram_ids", ()),
                        provider_ids=dirty_platform_auth.get("provider_ids", ()),
                    )
                elif dirty_platform_auth:
                    # Compatibility with older mutation sites that set a boolean.
                    invalidate_provider_access_cache()
                return result
            except Exception:
                await session.rollback()
                raise
            finally:
                elapsed_ms = (time.perf_counter() - started) * 1000
                if elapsed_ms >= self.slow_warning_ms:
                    actor = data.get("event_from_user")
                    logger.warning(
                        "Slow Telegram update correlation=%s elapsed_ms=%.0f actor=%s event=%s",
                        correlation_id,
                        elapsed_ms,
                        getattr(actor, "id", "unknown"),
                        type(event).__name__,
                    )


class BannedUserMiddleware(BaseMiddleware):
    """Stop banned users while caching the read-only flag briefly for fast menus."""

    def __init__(self, cache_ttl_seconds: float = 30.0) -> None:
        self.cache_ttl_seconds = max(1.0, float(cache_ttl_seconds))
        self._cache: dict[int, tuple[float, bool]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        actor = data.get("event_from_user")
        settings: Settings | None = data.get("settings")
        session = data.get("session")
        if not actor or not session or (settings and settings.is_admin(actor.id)):
            return await handler(event, data)

        now = time.monotonic()
        cached = self._cache.get(int(actor.id))
        if cached is not None and now - cached[0] < self.cache_ttl_seconds:
            is_banned = cached[1]
        else:
            try:
                async with asyncio.timeout(0.60):
                    is_banned = bool(
                        await session.scalar(
                            select(User.is_banned)
                            .where(User.telegram_id == actor.id)
                            .limit(1)
                        )
                    )
            except Exception as exc:
                # Do not let a slow/failed authorization read hold a callback
                # beyond Telegram's deadline or continue with an unknown status.
                with contextlib.suppress(Exception):
                    await session.rollback()
                logger.warning(
                    "Banned-user lookup failed user=%s error=%s",
                    actor.id,
                    type(exc).__name__,
                )
                text = "تعذر التحقق من الجلسة الآن. أعد المحاولة بعد لحظة."
                if isinstance(event, CallbackQuery):
                    with contextlib.suppress(Exception):
                        await event.answer(text, show_alert=True)
                elif isinstance(event, Message):
                    with contextlib.suppress(Exception):
                        await event.answer(text)
                return None
            self._cache[int(actor.id)] = (now, is_banned)
            if len(self._cache) > 20_000:
                cutoff = now - self.cache_ttl_seconds
                self._cache = {
                    user_id: item for user_id, item in self._cache.items() if item[0] >= cutoff
                }
        if not is_banned:
            return await handler(event, data)

        text = "🚫 تم إيقاف حسابك من استخدام البوت. إذا تعتقد أن هذا خطأ، تواصل مع الدعم."
        if isinstance(event, CallbackQuery):
            with contextlib.suppress(Exception):
                await event.answer(text, show_alert=True)
        elif isinstance(event, Message):
            with contextlib.suppress(Exception):
                await event.answer(text)
        return None


class RateLimitMiddleware(BaseMiddleware):
    """Action-aware anti-spam gate that runs before opening a DB session.

    Normal navigation keeps a very short global interval. Exact duplicate and
    financially sensitive operations receive a longer per-action lock. Redis is
    used when available so multiple replicas enforce the same policy.
    """

    _SENSITIVE_PREFIXES = (
        "payment:",
        "payments:",
        "proof:",
        "wallet:",
        "withdraw:",
        "settlement:",
        "otp:",
        "warranty:",
        "friend:",
        "group_purchase:",
        "provider:payment",
        "provider:confirm",
        "admin:payment",
        "admin:finance",
    )

    def __init__(
        self,
        min_interval: float = 0.35,
        redis_client: Any | None = None,
        *,
        duplicate_window: float = 2.0,
        sensitive_interval: float = 1.25,
    ) -> None:
        self.min_interval = max(0.25, float(min_interval))
        self.duplicate_window = max(self.min_interval, float(duplicate_window))
        self.sensitive_interval = max(self.min_interval, float(sensitive_interval))
        self.redis = redis_client
        self.last_seen: dict[tuple[int, str], float] = defaultdict(float)
        self._locks: dict[int, asyncio.Lock] = {}
        self._cleanup_lock = asyncio.Lock()
        self._redis_warning_at = 0.0

    @staticmethod
    def _actual_event(event: TelegramObject) -> TelegramObject:
        if not isinstance(event, Update):
            return event
        return (
            event.callback_query
            or event.message
            or event.edited_message
            or event.inline_query
            or event.chosen_inline_result
            or event.shipping_query
            or event.pre_checkout_query
            or event.my_chat_member
            or event.chat_member
            or event.chat_join_request
            or event
        )

    @classmethod
    def _user(cls, event: TelegramObject, data: dict[str, Any]) -> TelegramUser | None:
        user = data.get("event_from_user")
        if isinstance(user, TelegramUser):
            return user
        actual = cls._actual_event(event)
        candidate = getattr(actual, "from_user", None)
        return candidate if isinstance(candidate, TelegramUser) else None

    @classmethod
    def _action(cls, event: TelegramObject) -> tuple[str, bool]:
        actual = cls._actual_event(event)
        if isinstance(actual, CallbackQuery):
            value = (actual.data or "callback:empty")[:256]
            sensitive = value.startswith(cls._SENSITIVE_PREFIXES)
            return f"callback:{value}", sensitive
        if isinstance(actual, Message):
            if actual.photo:
                return f"photo:{actual.photo[-1].file_unique_id}", True
            if actual.document:
                return f"document:{actual.document.file_unique_id}", True
            if actual.text:
                normalized = " ".join(actual.text.split())[:256]
                return f"text:{normalized}", normalized.startswith("/")
            return f"message:{actual.content_type}", False
        return f"event:{type(actual).__name__}", False

    async def _limited_local(
        self, user_id: int, action: str, *, sensitive: bool
    ) -> bool:
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            global_key = (user_id, "__global__")
            action_key = (user_id, action)
            global_limited = now - self.last_seen[global_key] < self.min_interval
            action_window = self.sensitive_interval if sensitive else self.duplicate_window
            duplicate_limited = now - self.last_seen[action_key] < action_window
            limited = global_limited or duplicate_limited
            if not limited:
                self.last_seen[global_key] = now
                self.last_seen[action_key] = now

        if len(self.last_seen) > 40_000:
            async with self._cleanup_lock:
                cutoff = time.monotonic() - max(120.0, self.duplicate_window * 4)
                self.last_seen = defaultdict(
                    float,
                    {key: seen for key, seen in self.last_seen.items() if seen >= cutoff},
                )
                active_users = {key[0] for key in self.last_seen}
                self._locks = {
                    uid: existing_lock
                    for uid, existing_lock in self._locks.items()
                    if uid in active_users or existing_lock.locked()
                }
        return limited

    async def _limited(
        self, user_id: int, action: str, *, sensitive: bool
    ) -> bool:
        if self.redis is not None:
            try:
                action_digest = __import__("hashlib").sha256(
                    action.encode("utf-8")
                ).hexdigest()[:20]
                action_window = self.sensitive_interval if sensitive else self.duplicate_window
                async with asyncio.timeout(0.20):
                    global_ok = await self.redis.set(
                        f"campuspass:rate:v11:global:{user_id}",
                        "1",
                        nx=True,
                        px=max(250, int(self.min_interval * 1_000)),
                    )
                    action_ok = await self.redis.set(
                        f"campuspass:rate:v11:action:{user_id}:{action_digest}",
                        "1",
                        nx=True,
                        px=max(500, int(action_window * 1_000)),
                    )
                return not (bool(global_ok) and bool(action_ok))
            except Exception as exc:
                now = time.monotonic()
                if now - self._redis_warning_at >= 30.0:
                    logger.warning(
                        "Redis rate limiter unavailable; using local fallback: %s",
                        type(exc).__name__,
                    )
                    self._redis_warning_at = now
        return await self._limited_local(user_id, action, sensitive=sensitive)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = self._user(event, data)
        action, sensitive = self._action(event)
        if user and await self._limited(int(user.id), action, sensitive=sensitive):
            actual = self._actual_event(event)
            text = (
                "🔒 تم تجاهل التكرار لحماية العملية. انتظر لحظة ثم حاول مجددًا."
                if sensitive
                else "⏳ انتظر لحظة ثم حاول مجددًا"
            )
            if isinstance(actual, CallbackQuery):
                with contextlib.suppress(Exception):
                    await actual.answer(text)
            elif isinstance(actual, Message) and (actual.text or "").startswith("/"):
                with contextlib.suppress(Exception):
                    await actual.answer(text)
            return None
        return await handler(event, data)


class ActivityIndicatorMiddleware(BaseMiddleware):
    """Immediate feedback plus bounded queues for expensive operations.

    Normal navigation receives no extra Telegram API calls. Handlers marked with
    ``processing_immediate``, ``imap``, ``ai``, ``report`` or ``long_operation``
    show the progress message before work begins and execute behind an operation-
    specific semaphore. A traffic spike therefore queues heavy jobs instead of
    freezing every menu button or exhausting Railway memory.
    """

    def __init__(
        self,
        delay_ms: int = 50,
        text: str = "جاري المعالجة، يرجى الانتظار...",
        *,
        ai_limit: int = 5,
        imap_limit: int = 8,
        report_limit: int = 4,
        long_operation_limit: int = 12,
    ) -> None:
        self.delay = min(0.095, max(0.0, delay_ms / 1_000))
        self.text = text.strip() or "جاري المعالجة، يرجى الانتظار..."
        self._semaphores = {
            "ai": asyncio.Semaphore(max(1, int(ai_limit))),
            "imap": asyncio.Semaphore(max(1, int(imap_limit))),
            "report": asyncio.Semaphore(max(1, int(report_limit))),
            "long": asyncio.Semaphore(max(1, int(long_operation_limit))),
        }

    @staticmethod
    def _handler_flags(data: dict[str, Any]) -> dict[str, Any]:
        handler_object = data.get("handler")
        flags = getattr(handler_object, "flags", None)
        return flags if isinstance(flags, dict) else {}

    @staticmethod
    def _message_from_event(event: TelegramObject) -> Message | None:
        if isinstance(event, Message):
            return event
        if isinstance(event, CallbackQuery) and isinstance(event.message, Message):
            return event.message
        return None

    @staticmethod
    def _operation_key(flags: dict[str, Any]) -> str | None:
        if flags.get("ai"):
            return "ai"
        if flags.get("imap"):
            return "imap"
        if flags.get("report"):
            return "report"
        if flags.get("long_operation") or flags.get("processing_immediate"):
            return "long"
        return None

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Callback handlers own the acknowledgement as their first statement.
        # Never queue them behind a semaphore or create a temporary chat message
        # before that acknowledgement; DB/task concurrency remains bounded by
        # the dispatcher and service-level limits.
        if isinstance(event, CallbackQuery):
            return await handler(event, data)

        message = self._message_from_event(event)
        bot = data.get("bot")
        flags = self._handler_flags(data)
        operation_key = self._operation_key(flags)
        if flags.get("processing") is False or not message or not bot or not operation_key:
            return await handler(event, data)

        status_holder: dict[str, Any] = {}

        async def indicator() -> None:
            # Explicitly marked heavy handlers must get feedback before queueing.
            if self.delay:
                await asyncio.sleep(self.delay)
            with contextlib.suppress(Exception):
                await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            with contextlib.suppress(Exception):
                status_holder["message"] = await bot.send_message(message.chat.id, self.text)

        await indicator()
        semaphore = self._semaphores[operation_key]
        error_reference: str | None = None
        try:
            async with semaphore:
                return await handler(event, data)
        except Exception:
            error_reference = secrets.token_hex(4).upper()
            logger.exception("Unhandled bot operation error reference=%s", error_reference)
            raise
        finally:
            status = status_holder.get("message")
            if error_reference:
                error_text = (
                    "⚠️ تعذر إكمال العملية حاليًا. لم يتوقف البوت. "
                    "أعد المحاولة، وإذا تكررت المشكلة أرسل رقم المتابعة: "
                    f"<code>{error_reference}</code>"
                )
                if status:
                    with contextlib.suppress(Exception):
                        await bot.edit_message_text(
                            error_text,
                            chat_id=status.chat.id,
                            message_id=status.message_id,
                        )
                else:
                    with contextlib.suppress(Exception):
                        await bot.send_message(message.chat.id, error_text)
            elif status:
                with contextlib.suppress(Exception):
                    await bot.delete_message(status.chat.id, status.message_id)


class OperationalRestrictionMiddleware(BaseMiddleware):
    """Keep overdue temporary-account users inside the proof/support recovery flow.

    This is intentionally separate from the permanent ban flag. A restricted
    student can still upload logout evidence or request review, while all other
    commerce/navigation actions remain blocked until the provider confirms exit.
    """

    _ALLOWED_CALLBACK_PREFIXES = ("tmp:", "support:")
    _ALLOWED_STATE_MARKERS = ("TemporaryLogoutStates", "SupportStates", "DirectSupportStates")

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        actor = data.get("event_from_user")
        session = data.get("session")
        services = data.get("services")
        settings: Settings | None = data.get("settings")
        if not actor or not session or not services or (settings and settings.is_admin(actor.id)):
            return await handler(event, data)

        restriction = await services.provider_operations.active_restriction(
            session, telegram_id=int(actor.id)
        )
        if restriction is None:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            callback_data = str(event.data or "")
            if callback_data.startswith(self._ALLOWED_CALLBACK_PREFIXES):
                return await handler(event, data)
        elif isinstance(event, Message):
            raw_state = str(data.get("raw_state") or "")
            if any(marker in raw_state for marker in self._ALLOWED_STATE_MARKERS):
                return await handler(event, data)

        text = (
            "⚠️ انتهت مدة حساب مؤقت ولم يتم تأكيد تسجيل خروجك.\n"
            "أرسل إثبات الخروج أو اطلب مراجعة حتى تعود لاستخدام بقية البوت."
        )
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📤 إرسال إثبات الخروج",
                        callback_data=f"tmp:proof_order:{restriction.order_id}",
                        style="success",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📝 طلب مراجعة",
                        callback_data=f"tmp:review:{restriction.id}",
                        style="primary",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🆘 مركز المساعدة",
                        callback_data="announcement:open:support",
                    )
                ],
            ]
        )
        if isinstance(event, CallbackQuery):
            with contextlib.suppress(Exception):
                await event.answer("يجب معالجة إثبات تسجيل الخروج أولاً", show_alert=True)
            if event.message:
                with contextlib.suppress(Exception):
                    await event.message.answer(text, reply_markup=markup)
        elif isinstance(event, Message):
            with contextlib.suppress(Exception):
                await event.answer(text, reply_markup=markup)
        return None
