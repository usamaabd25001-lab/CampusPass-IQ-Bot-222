from __future__ import annotations

import contextlib
import time
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import CallbackPayloadError, callback_payload
from app.db.models import (
    Announcement,
    AnnouncementDelivery,
    AnnouncementStatus,
    ProviderStaff,
    StudentProfile,
    User,
    UserRole,
)


class AnnouncementService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._no_active_until = 0.0

    async def recipients(self, session: AsyncSession, announcement: Announcement) -> list[User]:
        query = select(User).where(User.is_active.is_(True))
        scope = announcement.target_scope
        value = (announcement.target_value or "").strip()
        if scope == "students":
            query = query.where(User.role == UserRole.USER.value)
        elif scope == "admins":
            query = query.where(User.role == UserRole.ADMIN.value)
        elif scope == "providers":
            query = query.join(ProviderStaff, ProviderStaff.user_id == User.id).where(
                ProviderStaff.is_active.is_(True)
            )
        elif scope == "governorate" and value:
            query = query.join(StudentProfile, StudentProfile.user_id == User.id).where(
                StudentProfile.governorate == value
            )
        elif scope == "college" and value:
            query = query.join(StudentProfile, StudentProfile.user_id == User.id).where(
                StudentProfile.college == value
            )
        elif scope == "university" and value:
            query = query.join(StudentProfile, StudentProfile.user_id == User.id).where(
                StudentProfile.university == value
            )
        return list((await session.scalars(query.distinct().order_by(User.id))).all())

    @staticmethod
    def markup(announcement: Announcement) -> InlineKeyboardMarkup | None:
        """Build an external-link button or a safe internal bot-action button.

        Internal actions are stored in ``button_url`` with the ``action:`` prefix,
        for example ``action:offers``. This keeps the database schema backward
        compatible and avoids fragile deep links or hard-coded bot usernames.
        """
        if not announcement.button_text or not announcement.button_url:
            return None
        target = announcement.button_url.strip()
        if target.startswith("action:"):
            action = target.removeprefix("action:").strip()
            try:
                payload = callback_payload("announcement", "open", action)
            except CallbackPayloadError:
                # Never let one malformed admin-configured action break an
                # entire broadcast batch or reach Telegram as BUTTON_DATA_INVALID.
                return None
            return InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=announcement.button_text,
                            callback_data=payload,
                            style="primary",
                        )
                    ]
                ]
            )
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=announcement.button_text,
                        url=target,
                        style="primary",
                    )
                ]
            ]
        )

    async def send_one(
        self,
        session: AsyncSession,
        announcement: Announcement,
        user: User,
    ) -> AnnouncementDelivery:
        delivery = await session.scalar(
            select(AnnouncementDelivery)
            .where(
                AnnouncementDelivery.announcement_id == announcement.id,
                AnnouncementDelivery.user_id == user.id,
            )
            .with_for_update()
        )
        if not delivery:
            delivery = AnnouncementDelivery(
                announcement_id=announcement.id,
                user_id=user.id,
                chat_id=user.telegram_id,
            )
            session.add(delivery)
            await session.flush()
        if delivery.sent_at:
            return delivery
        text = f"📣 <b>{announcement.title}</b>\n\n{announcement.body}"
        try:
            if announcement.media_type == "photo" and announcement.media_file_id:
                sent = await self.bot.send_photo(
                    user.telegram_id,
                    announcement.media_file_id,
                    caption=text,
                    reply_markup=self.markup(announcement),
                )
            elif announcement.media_type == "video" and announcement.media_file_id:
                sent = await self.bot.send_video(
                    user.telegram_id,
                    announcement.media_file_id,
                    caption=text,
                    reply_markup=self.markup(announcement),
                )
            elif announcement.media_type == "document" and announcement.media_file_id:
                sent = await self.bot.send_document(
                    user.telegram_id,
                    announcement.media_file_id,
                    caption=text,
                    reply_markup=self.markup(announcement),
                )
            else:
                sent = await self.bot.send_message(
                    user.telegram_id,
                    text,
                    reply_markup=self.markup(announcement),
                )
            delivery.message_id = sent.message_id
            delivery.sent_at = datetime.now(UTC)
            if announcement.pin_message:
                previous = list(
                    (
                        await session.scalars(
                            select(AnnouncementDelivery).where(
                                AnnouncementDelivery.user_id == user.id,
                                AnnouncementDelivery.id != delivery.id,
                                AnnouncementDelivery.pinned_at.is_not(None),
                                AnnouncementDelivery.unpinned_at.is_(None),
                            )
                        )
                    ).all()
                )
                for old in previous:
                    with contextlib.suppress(Exception):
                        await self.bot.unpin_chat_message(
                            chat_id=old.chat_id,
                            message_id=old.message_id,
                        )
                    old.unpinned_at = datetime.now(UTC)
                try:
                    await self.bot.pin_chat_message(
                        chat_id=user.telegram_id,
                        message_id=sent.message_id,
                        disable_notification=True,
                    )
                    delivery.pinned_at = datetime.now(UTC)
                except Exception as exc:
                    # The announcement itself was delivered, but pinning failed for this chat.
                    # Keep the delivery successful and expose the pin failure to the owner.
                    delivery.error = f"pin_failed: {exc}"[:2000]
        except Exception as exc:  # Telegram errors must not abort the whole campaign.
            delivery.error = str(exc)[:2000]
        await session.flush()
        return delivery

    async def dispatch(
        self, session: AsyncSession, announcement: Announcement
    ) -> tuple[int, int, int, int]:
        """Send an announcement and return sent, failed, pinned, pin_failed counts."""
        recipients = await self.recipients(session, announcement)
        success = 0
        failed = 0
        pinned = 0
        pin_failed = 0
        for user in recipients:
            delivery = await self.send_one(session, announcement, user)
            if delivery.sent_at:
                success += 1
                if announcement.pin_message:
                    if delivery.pinned_at:
                        pinned += 1
                    else:
                        pin_failed += 1
            else:
                failed += 1
        announcement.status = AnnouncementStatus.ACTIVE.value
        await session.flush()
        return success, failed, pinned, pin_failed

    async def process_due(self, session: AsyncSession) -> tuple[int, int]:
        now = datetime.now(UTC)
        due = list(
            (
                await session.scalars(
                    select(Announcement).where(
                        Announcement.status.in_(
                            [AnnouncementStatus.SCHEDULED.value, AnnouncementStatus.ACTIVE.value]
                        ),
                        Announcement.starts_at <= now,
                    )
                )
            ).all()
        )
        dispatched = 0
        finished = 0
        for announcement in due:
            if announcement.ends_at and announcement.ends_at <= now:
                await self.finish(session, announcement)
                finished += 1
                continue
            await self.dispatch(session, announcement)
            dispatched += 1
        return dispatched, finished

    async def finish(self, session: AsyncSession, announcement: Announcement) -> None:
        deliveries = list(
            (
                await session.scalars(
                    select(AnnouncementDelivery).where(
                        AnnouncementDelivery.announcement_id == announcement.id,
                        AnnouncementDelivery.pinned_at.is_not(None),
                        AnnouncementDelivery.unpinned_at.is_(None),
                    )
                )
            ).all()
        )
        for delivery in deliveries:
            with contextlib.suppress(Exception):
                await self.bot.unpin_chat_message(
                    chat_id=delivery.chat_id,
                    message_id=delivery.message_id,
                )
            delivery.unpinned_at = datetime.now(UTC)
        announcement.status = AnnouncementStatus.FINISHED.value
        await session.flush()

    async def stop_by_id(self, session: AsyncSession, announcement_id: int) -> bool:
        announcement = await session.scalar(
            select(Announcement).where(Announcement.id == announcement_id).with_for_update()
        )
        if not announcement:
            return False
        if announcement.status == AnnouncementStatus.FINISHED.value:
            return True
        await self.finish(session, announcement)
        return True

    async def active_for_user(
        self, session: AsyncSession, user: User
    ) -> list[Announcement]:
        now = datetime.now(UTC)
        now_monotonic = time.monotonic()
        if self._no_active_until > now_monotonic:
            return []
        rows = list(
            (
                await session.scalars(
                    select(Announcement).where(
                        Announcement.status == AnnouncementStatus.ACTIVE.value,
                        Announcement.starts_at <= now,
                        (Announcement.ends_at.is_(None) | (Announcement.ends_at > now)),
                    )
                    .order_by(Announcement.starts_at.desc())
                    .limit(20)
                )
            ).all()
        )
        if not rows:
            self._no_active_until = now_monotonic + 15.0
            return []
        needs_provider_check = any(row.target_scope == "providers" for row in rows)
        is_provider = False
        if needs_provider_check:
            is_provider = bool(
                await session.scalar(
                    select(ProviderStaff.id).where(
                        ProviderStaff.user_id == user.id,
                        ProviderStaff.is_active.is_(True),
                    )
                )
            )
        # UserService loads the one-to-one profile with the user, so do not issue
        # another query on every main-menu refresh.
        profile = user.profile
        result: list[Announcement] = []
        for row in rows:
            if row.target_scope == "all":
                result.append(row)
            elif row.target_scope == "students" and user.role == UserRole.USER.value:
                result.append(row)
            elif row.target_scope == "admins" and user.role == UserRole.ADMIN.value:
                result.append(row)
            elif row.target_scope == "providers" and is_provider:
                result.append(row)
            elif (
                row.target_scope == "governorate"
                and profile
                and profile.governorate == (row.target_value or "").strip()
            ):
                result.append(row)
            elif (
                row.target_scope == "college"
                and profile
                and profile.college == (row.target_value or "").strip()
            ):
                result.append(row)
            elif (
                row.target_scope == "university"
                and profile
                and profile.university == (row.target_value or "").strip()
            ):
                result.append(row)
        return result

    async def send_active_for_user(self, session: AsyncSession, user: User) -> int:
        """Deliver currently active campaigns to a user who opened/refreshed the bot.

        The per-user unique delivery row prevents duplicate messages on every menu
        refresh while ensuring users who joined after campaign dispatch still receive it.
        """
        sent = 0
        for announcement in await self.active_for_user(session, user):
            delivery = await self.send_one(session, announcement, user)
            if delivery.sent_at:
                sent += 1
        return sent
