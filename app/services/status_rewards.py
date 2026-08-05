from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import StudentRewardEvent, StudentRewardStatus, User


@dataclass(frozen=True, slots=True)
class RewardSummary:
    level: str
    status_points: int
    successful_referrals: int
    successful_purchases: int
    status_link_shares: int
    next_level_points: int


class StatusRewardService:
    LEVELS: tuple[tuple[str, int], ...] = (
        ("starter", 0),
        ("active", 100),
        ("ambassador", 300),
        ("elite", 700),
    )

    async def get_or_create(self, session: AsyncSession, user: User) -> StudentRewardStatus:
        row = await session.scalar(
            select(StudentRewardStatus).where(StudentRewardStatus.user_id == user.id).with_for_update()
        )
        if row is None:
            row = StudentRewardStatus(user_id=user.id)
            session.add(row)
            await session.flush()
        return row

    @classmethod
    def level_for_points(cls, points: int) -> tuple[str, int]:
        current = cls.LEVELS[0][0]
        next_threshold = cls.LEVELS[-1][1]
        for index, (name, threshold) in enumerate(cls.LEVELS):
            if points >= threshold:
                current = name
                if index + 1 < len(cls.LEVELS):
                    next_threshold = cls.LEVELS[index + 1][1]
                else:
                    next_threshold = threshold
            else:
                break
        return current, next_threshold

    async def record(
        self,
        session: AsyncSession,
        *,
        user: User,
        event_type: str,
        points_delta: int,
        idempotency_key: str,
        reference_type: str | None = None,
        reference_id: int | None = None,
        metadata: dict | None = None,
    ) -> bool:
        existing = await session.scalar(
            select(StudentRewardEvent.id).where(StudentRewardEvent.idempotency_key == idempotency_key)
        )
        if existing:
            return False
        status = await self.get_or_create(session, user)
        delta = int(points_delta)
        status.status_points = max(0, int(status.status_points) + delta)
        if event_type == "successful_referral":
            status.successful_referrals += 1
        elif event_type == "successful_purchase":
            status.successful_purchases += 1
        elif event_type == "status_link_share":
            status.status_link_shares += 1
        level, _next = self.level_for_points(status.status_points)
        status.current_level = level
        session.add(
            StudentRewardEvent(
                user_id=user.id,
                event_type=event_type[:40],
                points_delta=delta,
                idempotency_key=idempotency_key[:160],
                reference_type=reference_type[:40] if reference_type else None,
                reference_id=reference_id,
                metadata_json=metadata or {},
            )
        )
        await session.flush()
        return True

    async def summary(self, session: AsyncSession, user: User) -> RewardSummary:
        status = await self.get_or_create(session, user)
        level, next_threshold = self.level_for_points(status.status_points)
        if status.current_level != level:
            status.current_level = level
        return RewardSummary(
            level=level,
            status_points=int(status.status_points),
            successful_referrals=int(status.successful_referrals),
            successful_purchases=int(status.successful_purchases),
            status_link_shares=int(status.status_link_shares),
            next_level_points=max(0, next_threshold - int(status.status_points)),
        )
