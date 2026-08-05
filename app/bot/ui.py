from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from aiogram.exceptions import TelegramBadRequest
from aiogram import Bot
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from app.bot.keyboards.inline import validate_callback_markup, with_navigation

logger = logging.getLogger(__name__)

# Telegram may deliver two clicks on the same inline message almost together. Serializing edits
# per (chat, message) prevents stale database snapshots from overwriting the latest keyboard.
_RENDER_LOCKS: dict[tuple[int, int], asyncio.Lock] = {}
_MAX_RENDER_LOCKS = 10_000

# Top-level workspace transitions are serialized per actor/chat.  This is separate
# from message edit locking because Home may create a reply-keyboard message while
# an older inline callback is still in flight.
_TRANSITION_LOCKS: dict[tuple[int, int], asyncio.Lock] = {}
_MAX_TRANSITION_LOCKS = 20_000

# A serial lock prevents races, while this tiny dedupe window prevents the second
# queued click from creating the same destination again after the first click has
# already completed. Messages live for less than a second in this cache and the
# database remains the source of truth.
_TRANSITION_DEDUPE_SECONDS = 0.9
_LAST_TRANSITION_RENDERS: dict[tuple[str, int, int], tuple[float, str, Message]] = {}
_MAX_TRANSITION_RENDERS = 5_000


def _transition_signature(text: str, markup: object) -> str:
    return f"{text}\x1f{markup!r}"


def _recent_transition(
    kind: str,
    chat_id: int,
    actor_id: int | None,
    signature: str,
) -> Message | None:
    key = (kind, int(chat_id), int(actor_id or chat_id))
    cached = _LAST_TRANSITION_RENDERS.get(key)
    now = time.monotonic()
    if cached is None:
        return None
    created_at, cached_signature, message = cached
    if now - created_at <= _TRANSITION_DEDUPE_SECONDS and cached_signature == signature:
        return message
    if now - created_at > _TRANSITION_DEDUPE_SECONDS:
        _LAST_TRANSITION_RENDERS.pop(key, None)
    return None


def _remember_transition(
    kind: str,
    chat_id: int,
    actor_id: int | None,
    signature: str,
    message: Message,
) -> None:
    key = (kind, int(chat_id), int(actor_id or chat_id))
    _LAST_TRANSITION_RENDERS[key] = (time.monotonic(), signature, message)
    if len(_LAST_TRANSITION_RENDERS) > _MAX_TRANSITION_RENDERS:
        cutoff = time.monotonic() - _TRANSITION_DEDUPE_SECONDS
        for stale_key, (created_at, _signature, _message) in list(
            _LAST_TRANSITION_RENDERS.items()
        )[:1000]:
            if created_at < cutoff and stale_key != key:
                _LAST_TRANSITION_RENDERS.pop(stale_key, None)


@asynccontextmanager
async def transition_lock(chat_id: int, actor_id: int | None = None) -> AsyncIterator[None]:
    key = (int(chat_id), int(actor_id or chat_id))
    lock = _TRANSITION_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _TRANSITION_LOCKS[key] = lock
    if len(_TRANSITION_LOCKS) > _MAX_TRANSITION_LOCKS:
        for stale_key, stale_lock in list(_TRANSITION_LOCKS.items())[:2000]:
            if stale_key != key and not stale_lock.locked():
                _TRANSITION_LOCKS.pop(stale_key, None)
    async with lock:
        yield


def _render_key(message: Message) -> tuple[int, int]:
    chat_id = int(getattr(getattr(message, "chat", None), "id", 0) or 0)
    message_id = int(getattr(message, "message_id", 0) or 0)
    return chat_id, message_id


def _render_lock(message: Message) -> asyncio.Lock:
    key = _render_key(message)
    lock = _RENDER_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _RENDER_LOCKS[key] = lock
    if len(_RENDER_LOCKS) > _MAX_RENDER_LOCKS:
        for stale_key, stale_lock in list(_RENDER_LOCKS.items())[:1000]:
            if not stale_lock.locked() and stale_key != key:
                _RENDER_LOCKS.pop(stale_key, None)
    return lock


async def edit_or_send(
    message: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    ensure_navigation: bool = True,
    back_callback: str = "nav:back",
    **kwargs: Any,
) -> Message:
    """Render one callback menu in place, serialized per Telegram message.

    The single fallback is used only when Telegram cannot edit the source message. The old
    callback message is then removed when possible, so repeated clicks cannot create duplicates.
    """

    if ensure_navigation:
        reply_markup = with_navigation(reply_markup, back_callback=back_callback)
    else:
        reply_markup = validate_callback_markup(reply_markup)

    async with _render_lock(message):
        try:
            if message.text is not None:
                return await message.edit_text(text, reply_markup=reply_markup, **kwargs)
            if message.caption is not None:
                return await message.edit_caption(caption=text, reply_markup=reply_markup, **kwargs)
        except TelegramBadRequest as exc:
            detail = str(exc).lower()
            if "message is not modified" in detail:
                return message
            logger.debug("Telegram rejected in-place render (%s); using fallback", detail)
        except Exception:
            logger.debug("In-place Telegram render failed; using a single fallback", exc_info=True)

        # Build the destination first. A temporary DB/Telegram failure must never
        # destroy the only usable screen. Once the replacement exists, remove the
        # stale source best-effort. The per-message lock prevents duplicate fallback
        # renders from concurrent clicks.
        replacement = await message.answer(text, reply_markup=reply_markup, **kwargs)
        if replacement.message_id != message.message_id:
            await delete_safely(message)
        return replacement


async def callback_notice(
    callback: CallbackQuery,
    text: object | None = None,
    *,
    show_alert: bool = False,
) -> Message | None:
    """Show post-acknowledgement feedback in the same inline message.

    Telegram callback queries are acknowledged exactly once at handler entry. Any later success or
    validation feedback is therefore rendered in place instead of attempting a second
    answerCallbackQuery call or creating a duplicate menu message.
    """

    message = callback.message
    if not isinstance(message, Message):
        return None
    if text is None or str(text).strip() == "":
        return message

    icon = "⚠️" if show_alert else "✅"
    notice = f"{icon} <b>{html.escape(str(text))}</b>"
    current = ""
    if getattr(message, "text", None):
        current = str(getattr(message, "html_text", None) or message.text)
    elif getattr(message, "caption", None):
        current = str(getattr(message, "html_caption", None) or message.caption)
    # Keep the current menu context when it safely fits Telegram's text limit.
    rendered = f"{notice}\n\n{current}" if current and len(notice) + len(current) < 3900 else notice
    return await edit_or_send(
        message,
        rendered,
        reply_markup=getattr(message, "reply_markup", None),
    )


async def edit_markup(
    message: Message,
    reply_markup: InlineKeyboardMarkup | None,
    *,
    ensure_navigation: bool = True,
    back_callback: str = "nav:back",
) -> Message:
    """Refresh only the keyboard after a database state change."""

    if ensure_navigation:
        reply_markup = with_navigation(reply_markup, back_callback=back_callback)
    else:
        reply_markup = validate_callback_markup(reply_markup)

    async with _render_lock(message):
        try:
            return await message.edit_reply_markup(reply_markup=reply_markup)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return message
            raise


async def delete_safely(message: Message | None) -> bool:
    """Delete a message and report whether it was removed successfully."""

    if message is None:
        return False
    try:
        await message.delete()
        return True
    except Exception:
        logger.debug(
            "Could not delete Telegram message chat=%s message=%s",
            _render_key(message)[0],
            _render_key(message)[1],
            exc_info=True,
        )
        return False


async def remove_reply_keyboard_temporarily(message: Message) -> Message | None:
    """Hide a persistent ReplyKeyboard without a deleted carrier workaround.

    The returned message is deliberately visible. Callers that need an inline
    workspace should use :func:`send_inline_menu`, which turns the same visible
    message into the final inline menu after Telegram applies the removal.
    """

    try:
        return await message.answer(
            "تم الانتقال إلى مساحة الأدوات.",
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception:
        logger.debug("Could not remove reply keyboard", exc_info=True)
        return None


async def send_inline_menu(
    chat_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None,
    *,
    bot: Bot,
    source_message_id: int | None = None,
    source_message: Message | None = None,
    actor_id: int | None = None,
    ensure_navigation: bool = True,
    back_callback: str = "nav:back",
    **kwargs: Any,
) -> Message:
    """Render one deterministic inline workspace.

    There is no deleted keyboard carrier.  When entering from a ReplyKeyboard,
    the final visible message is first sent with ``ReplyKeyboardRemove`` and then
    receives its InlineKeyboard via ``edit_message_reply_markup``.  When replacing
    an existing inline message, the source is edited first and is never deleted
    until a complete replacement exists.
    """

    if ensure_navigation:
        markup = with_navigation(markup, back_callback=back_callback)
    else:
        markup = validate_callback_markup(markup)
    if source_message is not None:
        source_message_id = source_message.message_id

    signature = _transition_signature(text, markup)
    async with transition_lock(chat_id, actor_id):
        recent = _recent_transition("inline", chat_id, actor_id, signature)
        if recent is not None:
            if source_message_id is not None and source_message_id != recent.message_id:
                with contextlib.suppress(Exception):
                    await bot.delete_message(chat_id, int(source_message_id))
            return recent
        if source_message_id is not None:
            try:
                edited = await bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=int(source_message_id),
                    reply_markup=markup,
                    **kwargs,
                )
                if isinstance(edited, Message):
                    _remember_transition("inline", chat_id, actor_id, signature, edited)
                    return edited
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc).lower() and source_message is not None:
                    _remember_transition("inline", chat_id, actor_id, signature, source_message)
                    return source_message
                logger.debug("Could not edit source inline menu; creating replacement", exc_info=True)
            except Exception:
                logger.debug("Could not edit source inline menu; creating replacement", exc_info=True)

        transition = await bot.send_message(
            chat_id,
            text,
            reply_markup=ReplyKeyboardRemove(),
            **kwargs,
        )
        try:
            edited = await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=transition.message_id,
                reply_markup=markup,
            )
            final_message = edited if isinstance(edited, Message) else transition
        except Exception:
            # Telegram clients that reject changing ReplyKeyboardRemove to Inline
            # receive one replacement; the transition is deleted only after the
            # replacement succeeds, so navigation can never leave a blank screen.
            final_message = await bot.send_message(chat_id, text, reply_markup=markup, **kwargs)
            await delete_safely(transition)

        if source_message_id is not None and source_message_id != final_message.message_id:
            with contextlib.suppress(Exception):
                await bot.delete_message(chat_id, int(source_message_id))
        _remember_transition("inline", chat_id, actor_id, signature, final_message)
        return final_message


async def send_reply_menu(
    message: Message,
    text: str,
    reply_markup: ReplyKeyboardMarkup,
    *,
    source_message: Message | None = None,
    actor_id: int | None = None,
    **kwargs: Any,
) -> Message:
    """Send the final visible Home/submenu message with its ReplyKeyboard attached."""

    signature = _transition_signature(text, reply_markup)
    async with transition_lock(message.chat.id, actor_id):
        recent = _recent_transition("reply", message.chat.id, actor_id, signature)
        if recent is not None:
            if source_message is not None and source_message.message_id != recent.message_id:
                await delete_safely(source_message)
            return recent
        rendered = await message.bot.send_message(
            message.chat.id,
            text,
            reply_markup=reply_markup,
            **kwargs,
        )
        if source_message is not None and source_message.message_id != rendered.message_id:
            await delete_safely(source_message)
        _remember_transition("reply", message.chat.id, actor_id, signature, rendered)
        return rendered


async def install_reply_keyboard_temporarily(
    message: Message,
    reply_markup: ReplyKeyboardMarkup,
) -> Message:
    """Legacy alias retained for old imports; no temporary/deleted carrier is used."""

    logger.warning("Deprecated install_reply_keyboard_temporarily call; sending visible keyboard message")
    return await send_reply_menu(
        message,
        "استخدم الأزرار في لوحة القائمة بالأسفل.",
        reply_markup,
        actor_id=getattr(getattr(message, "from_user", None), "id", None),
    )
