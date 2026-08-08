from __future__ import annotations

from collections import defaultdict
from html.parser import HTMLParser
from urllib.parse import urlparse
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MessageTemplate, User

DEFAULT_TEMPLATES: dict[str, tuple[str, str, list[str]]] = {
    "start.welcome": (
        "رسالة /start",
        "أهلًا بك في CampusPass IQ Bot 👋\nمنصة الاشتراكات والخدمات الطلابية.",
        [],
    ),
    "processing.generic": (
        "جاري المعالجة",
        "⏳ جاري معالجة طلبك، يرجى الانتظار...",
        [],
    ),
    "payment.received": (
        "تم استلام إثبات الدفع",
        "تم استلام إثبات الدفع للطلب <code>{order_id}</code> ✅\nسيصلك إشعار بعد التدقيق.",
        ["order_id"],
    ),
    "payment.approved": (
        "تم قبول الدفع",
        "تم قبول الدفع للطلب <code>{order_id}</code> ✅\nجاري تجهيز الاشتراك بصورة آمنة.",
        ["order_id"],
    ),
    "delivery.sent": (
        "تم تسليم الاشتراك",
        "تم إرسال بيانات الاشتراك للطلب <code>{order_id}</code> ✅",
        ["order_id"],
    ),
    "subscription.expiring": (
        "اشتراك على وشك الانتهاء",
        "اشتراكك في {offer_name} من {provider_name} سينتهي بتاريخ {ends_at}.",
        ["offer_name", "provider_name", "ends_at"],
    ),
    "offer.launched": (
        "إطلاق عرض جديد",
        "<b>{platform_name}</b> أطلقت عرضًا جديدًا 🔥\n\n{description}\n\n💰 السعر: <b>{price}</b>\n⏰ ينتهي: <b>{ends_at}</b>",
        ["platform_name", "description", "price", "ends_at"],
    ),
    "system.error": (
        "حدث خطأ",
        "تعذر إكمال العملية حاليًا. رقم المتابعة: <code>{reference}</code>",
        ["reference"],
    ),
}




_ALLOWED_TELEGRAM_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "span", "tg-spoiler", "a", "code", "pre", "blockquote", "tg-emoji",
}


class _TelegramHTMLValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.error: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in _ALLOWED_TELEGRAM_TAGS:
            self.error = f"وسم HTML غير مدعوم: <{tag}>"
            return
        if tag in {"a", "span", "tg-emoji"}:
            allowed_attrs = {"href"} if tag == "a" else ({"class"} if tag == "span" else {"emoji-id"})
            if any(name not in allowed_attrs for name, _value in attrs):
                self.error = f"خاصية HTML غير مدعومة داخل <{tag}>"
                return
            if tag == "a":
                href = next((value for name, value in attrs if name == "href"), None)
                parsed = urlparse((href or "").strip())
                if parsed.scheme.lower() not in {"http", "https", "tg", "mailto"}:
                    self.error = "رابط HTML غير آمن أو غير مدعوم"
                    return
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.error is not None:
            return
        tag = tag.lower()
        if not self.stack or self.stack[-1] != tag:
            self.error = f"إغلاق HTML غير متطابق: </{tag}>"
            return
        self.stack.pop()

    def close(self) -> None:
        super().close()
        if self.stack and self.error is None:
            self.error = f"وسم HTML غير مغلق: <{self.stack[-1]}>"


def validate_telegram_html(value: str) -> None:
    parser = _TelegramHTMLValidator()
    try:
        parser.feed(value)
        parser.close()
    except Exception as exc:
        raise ValueError("صيغة HTML غير صالحة") from exc
    if parser.error:
        raise ValueError(parser.error)


class _SafeFormat(defaultdict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class MessageTemplateService:
    def __init__(self, cache_ttl_seconds: float = 300.0) -> None:
        self.cache_ttl_seconds = max(10.0, float(cache_ttl_seconds))
        self._welcome_cache: tuple[float, str] | None = None

    def invalidate(self, key: str | None = None) -> None:
        if key is None or key == "start.welcome":
            self._welcome_cache = None

    async def welcome_text(self, session: AsyncSession, fallback: str) -> str:
        now = time.monotonic()
        if self._welcome_cache is not None and self._welcome_cache[0] > now:
            return self._welcome_cache[1]
        row = await session.scalar(
            select(MessageTemplate).where(
                MessageTemplate.template_key == "start.welcome",
                MessageTemplate.locale == "ar",
                MessageTemplate.is_enabled.is_(True),
            )
        )
        value = (row.body if row and row.body.strip() else fallback).strip()
        self._welcome_cache = (now + self.cache_ttl_seconds, value)
        return value

    async def reset_welcome(self, session: AsyncSession, fallback: str, actor: User | None = None) -> MessageTemplate:
        row = await self.update(session, "start.welcome", fallback.strip(), actor, "ar")
        self.invalidate("start.welcome")
        return row

    async def seed(self, session: AsyncSession) -> None:
        for key, (title, body, variables) in DEFAULT_TEMPLATES.items():
            existing = await session.scalar(
                select(MessageTemplate).where(
                    MessageTemplate.template_key == key,
                    MessageTemplate.locale == "ar",
                )
            )
            if not existing:
                session.add(
                    MessageTemplate(
                        template_key=key,
                        locale="ar",
                        title=title,
                        body=body,
                        variables=variables,
                    )
                )
        await session.flush()

    async def get(
        self,
        session: AsyncSession,
        key: str,
        locale: str = "ar",
    ) -> MessageTemplate | None:
        await self.seed(session)
        return await session.scalar(
            select(MessageTemplate).where(
                MessageTemplate.template_key == key,
                MessageTemplate.locale == locale,
                MessageTemplate.is_enabled.is_(True),
            )
        )

    async def render(
        self,
        session: AsyncSession,
        key: str,
        values: dict[str, Any] | None = None,
        locale: str = "ar",
        fallback: str | None = None,
    ) -> str:
        row = await self.get(session, key, locale)
        body = row.body if row else fallback or DEFAULT_TEMPLATES.get(key, ("", key, []))[1]
        safe_values = _SafeFormat(str)
        safe_values.update({k: str(v) for k, v in (values or {}).items()})
        return body.format_map(safe_values)

    async def list(self, session: AsyncSession, locale: str = "ar") -> list[MessageTemplate]:
        await self.seed(session)
        return list(
            (
                await session.scalars(
                    select(MessageTemplate)
                    .where(MessageTemplate.locale == locale)
                    .order_by(MessageTemplate.template_key)
                )
            ).all()
        )

    async def update(
        self,
        session: AsyncSession,
        key: str,
        body: str,
        actor: User | None = None,
        locale: str = "ar",
    ) -> MessageTemplate:
        row = await session.scalar(
            select(MessageTemplate).where(
                MessageTemplate.template_key == key,
                MessageTemplate.locale == locale,
            )
        )
        if not row:
            row = MessageTemplate(
                template_key=key,
                locale=locale,
                title=key,
                body=body,
            )
            session.add(row)
        else:
            row.body = body
        row.updated_by_user_id = actor.id if actor else None
        await session.flush()
        self.invalidate(key)
        return row
