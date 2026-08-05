from __future__ import annotations

import logging

from aiogram import Bot
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Notification, ProviderStaff, User

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, bot: Bot, settings: Settings) -> None:
        self.bot = bot
        self.settings = settings

    async def send_user(
        self,
        session: AsyncSession,
        user: User,
        title: str,
        body: str,
        reply_markup=None,
        raise_on_error: bool = False,
        idempotency_key: str | None = None,
    ) -> bool:
        normalized_key = (idempotency_key or "").strip()[:160] or None
        notification = None
        if normalized_key:
            notification = await session.scalar(
                select(Notification).where(
                    Notification.idempotency_key == normalized_key
                )
            )
            if notification and notification.delivery_status == "sent":
                return True
        if not notification:
            notification = Notification(
                user_id=user.id,
                notification_type="telegram",
                idempotency_key=normalized_key,
                title=title,
                body=body,
                delivery_status="pending",
            )
            session.add(notification)
            await session.flush()
        notification.attempts += 1
        notification.title = title
        notification.body = body
        try:
            sent = await self.bot.send_message(
                user.telegram_id,
                f"<b>{title}</b>\n\n{body}",
                reply_markup=reply_markup,
            )
            from datetime import UTC, datetime

            notification.delivery_status = "sent"
            notification.sent_at = datetime.now(UTC)
            notification.telegram_message_id = sent.message_id
            notification.last_error = None
            await session.flush()
            return True
        except Exception as exc:
            notification.delivery_status = "failed"
            notification.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            await session.flush()
            logger.warning("Could not notify user %s: %s", user.telegram_id, exc)
            if raise_on_error:
                raise
            return False

    async def send_admins(self, text: str) -> None:
        for telegram_id in self.settings.admin_ids:
            try:
                await self.bot.send_message(telegram_id, text)
            except Exception as exc:
                logger.warning("Could not notify admin %s: %s", telegram_id, exc)

    async def provider_reviewer_ids(self, session: AsyncSession, provider_id: int) -> list[int]:
        return list(
            (
                await session.scalars(
                    select(User.telegram_id)
                    .join(ProviderStaff, ProviderStaff.user_id == User.id)
                    .where(
                        ProviderStaff.provider_id == provider_id,
                        ProviderStaff.is_active.is_(True),
                        or_(
                            ProviderStaff.can_review_payments.is_(True),
                            or_(
                                ProviderStaff.role == "OWNER",
                                func.lower(ProviderStaff.title).in_(
                                    ("owner", "platform_owner", "provider_owner", "مالك")
                                ),
                            ),
                        ),
                    )
                )
            ).all()
        )

    async def provider_support_ids(self, session: AsyncSession, provider_id: int) -> list[int]:
        return list(
            (
                await session.scalars(
                    select(User.telegram_id)
                    .join(ProviderStaff, ProviderStaff.user_id == User.id)
                    .where(
                        ProviderStaff.provider_id == provider_id,
                        ProviderStaff.is_active.is_(True),
                        or_(
                            ProviderStaff.can_support.is_(True),
                            or_(
                                ProviderStaff.role == "OWNER",
                                func.lower(ProviderStaff.title).in_(
                                    ("owner", "platform_owner", "provider_owner", "مالك")
                                ),
                            ),
                        ),
                    )
                )
            ).all()
        )
