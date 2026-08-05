from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.utils import referral_code
from app.db.models import Order, OrderStatus, PointsTransaction, StudentProfile, User, UserRole
from app.services.data_protection import DataProtectionService


class UserService:
    def __init__(self, settings: Settings, data_protection: DataProtectionService) -> None:
        self.settings = settings
        self.data_protection = data_protection

    @staticmethod
    def _telegram_cache(session: AsyncSession) -> dict[int, User | None]:
        return session.info.setdefault("campuspass_users_by_telegram", {})

    @staticmethod
    def _id_cache(session: AsyncSession) -> dict[int, User | None]:
        return session.info.setdefault("campuspass_users_by_id", {})

    @classmethod
    def _remember(
        cls,
        session: AsyncSession,
        user: User | None,
        *,
        telegram_id: int | None = None,
        user_id: int | None = None,
    ) -> User | None:
        if user is not None:
            cls._telegram_cache(session)[int(user.telegram_id)] = user
            cls._id_cache(session)[int(user.id)] = user
        else:
            if telegram_id is not None:
                cls._telegram_cache(session)[int(telegram_id)] = None
            if user_id is not None:
                cls._id_cache(session)[int(user_id)] = None
        return user

    async def get(self, session: AsyncSession, telegram_id: int) -> User | None:
        cache = self._telegram_cache(session)
        key = int(telegram_id)
        if key in cache:
            return cache[key]
        user = await session.scalar(
            select(User).options(selectinload(User.profile)).where(User.telegram_id == key)
        )
        return self._remember(session, user, telegram_id=key)

    async def get_by_id(self, session: AsyncSession, user_id: int) -> User | None:
        cache = self._id_cache(session)
        key = int(user_id)
        if key in cache:
            return cache[key]
        user = await session.scalar(
            select(User).options(selectinload(User.profile)).where(User.id == key)
        )
        return self._remember(session, user, user_id=key)

    @staticmethod
    def normalize_referral_payload(value: str | None) -> str:
        payload = (value or "").strip()
        lowered = payload.lower()
        for prefix in ("ref_", "ref-", "invite_"):
            if lowered.startswith(prefix):
                payload = payload[len(prefix):]
                break
        return payload.strip().upper()[:32]

    async def _eligible_referrer(
        self,
        session: AsyncSession,
        telegram_id: int,
        start_ref: str | None,
    ) -> User | None:
        code = self.normalize_referral_payload(start_ref)
        if not code:
            return None
        referrer = await session.scalar(select(User).where(User.referral_code == code))
        if not referrer or referrer.telegram_id == telegram_id:
            return None
        return referrer

    async def get_or_create(
        self,
        session: AsyncSession,
        telegram_id: int,
        telegram_username: str | None,
        telegram_name: str,
        start_ref: str | None = None,
    ) -> User:
        user = await self.get(session, telegram_id)
        if user:
            user.telegram_username = telegram_username
            user.telegram_name = telegram_name
            if self.settings.is_admin(telegram_id):
                user.role = UserRole.ADMIN.value
            # A student may have opened the bot before clicking the invitation.
            # Bind the referral only while no successful purchase exists and never
            # overwrite an existing inviter.
            if start_ref and user.referred_by_user_id is None:
                completed = int(
                    await session.scalar(
                        select(func.count(Order.id)).where(
                            Order.user_id == user.id,
                            Order.status == OrderStatus.COMPLETED.value,
                        )
                    )
                    or 0
                )
                if completed == 0:
                    referrer = await self._eligible_referrer(session, telegram_id, start_ref)
                    if referrer:
                        user.referred_by_user_id = referrer.id
            await session.flush()
            self._remember(session, user)
            return user

        role = UserRole.ADMIN.value if self.settings.is_admin(telegram_id) else UserRole.USER.value
        referrer = await self._eligible_referrer(session, telegram_id, start_ref)
        referred_by_user_id = referrer.id if referrer else None

        code = referral_code()
        while await session.scalar(select(User.id).where(User.referral_code == code)):
            code = referral_code()

        user = User(
            telegram_id=telegram_id,
            telegram_username=telegram_username,
            telegram_name=telegram_name,
            role=role,
            referral_code=code,
            referred_by_user_id=referred_by_user_id,
        )
        session.add(user)
        await session.flush()
        self._remember(session, user)
        return user

    async def accept_terms(self, session: AsyncSession, user: User) -> None:
        now = datetime.now(UTC)
        user.terms_accepted_at = now
        user.privacy_accepted_at = now
        user.privacy_policy_version = self.settings.privacy_policy_version
        await session.flush()

    async def save_profile(
        self,
        session: AsyncSession,
        user: User,
        data: dict[str, str],
        *,
        count_edit: bool = True,
    ) -> StudentProfile:
        profile = user.profile
        if profile is None:
            profile = StudentProfile(user_id=user.id, **data)
            session.add(profile)
            user.profile = profile
        else:
            for key, value in data.items():
                setattr(profile, key, value)
            if count_edit:
                profile.edit_count += 1
        await self.data_protection.protect_profile(
            session,
            profile,
            str(data.get("full_name") or profile.full_name),
            str(data.get("phone") or profile.phone),
        )
        await session.flush()
        return profile

    async def add_points(
        self,
        session: AsyncSession,
        user: User,
        amount: int,
        reason: str,
        reference_type: str | None = None,
        reference_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> bool:
        normalized_key = (idempotency_key or "").strip()[:160] or None
        if normalized_key and await session.scalar(
            select(PointsTransaction.id).where(
                PointsTransaction.idempotency_key == normalized_key
            )
        ):
            return False
        user.points += amount
        session.add(
            PointsTransaction(
                user_id=user.id,
                amount=amount,
                reason=reason,
                reference_type=reference_type,
                reference_id=reference_id,
                idempotency_key=normalized_key,
            )
        )
        await session.flush()
        return True
