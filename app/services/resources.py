from __future__ import annotations

from datetime import UTC, datetime, timedelta
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (OfferResourcePool, ResourceSeat, ResourceSeatStatus,
                           TemporaryAccessSession)


class ResourcePoolService:
    async def create_pool(self, session: AsyncSession, *, provider_id: int, offer_id: int,
                          name: str, capacity: int, kind: str = "shared_account",
                          reserve_capacity: int = 0, reusable_after_expiry: bool = True,
                          access_duration_minutes: int | None = None,
                          deletion_required: bool = False) -> OfferResourcePool:
        if capacity < 1 or reserve_capacity < 0 or reserve_capacity >= capacity:
            raise ValueError("سعة المورد غير صحيحة")
        pool = OfferResourcePool(provider_id=provider_id, offer_id=offer_id, name=name,
                                 capacity=capacity, reserve_capacity=reserve_capacity, kind=kind,
                                 reusable_after_expiry=reusable_after_expiry,
                                 access_duration_minutes=access_duration_minutes,
                                 deletion_required=deletion_required)
        session.add(pool)
        await session.flush()
        session.add_all([ResourceSeat(pool_id=pool.id, seat_number=i) for i in range(1, capacity + 1)])
        await session.flush()
        return pool

    async def hold(self, session: AsyncSession, *, offer_id: int, order_id: int,
                   user_id: int, minutes: int = 15) -> ResourceSeat:
        now = datetime.now(UTC)
        await self.release_expired_holds(session, now)
        pools = list((await session.scalars(select(OfferResourcePool).where(
            OfferResourcePool.offer_id == offer_id, OfferResourcePool.is_active.is_(True)
        ).order_by(OfferResourcePool.id))).all())
        for pool in pools:
            active_count = int(await session.scalar(select(func.count(ResourceSeat.id)).where(
                ResourceSeat.pool_id == pool.id,
                ResourceSeat.status.in_([ResourceSeatStatus.HELD.value, ResourceSeatStatus.ACTIVE.value])
            )) or 0)
            if active_count >= pool.capacity - pool.reserve_capacity:
                continue
            seat = await session.scalar(select(ResourceSeat).where(
                ResourceSeat.pool_id == pool.id,
                ResourceSeat.status == ResourceSeatStatus.AVAILABLE.value
            ).order_by(ResourceSeat.seat_number).with_for_update(skip_locked=True))
            if seat:
                seat.status = ResourceSeatStatus.HELD.value
                seat.order_id, seat.user_id = order_id, user_id
                seat.held_until = now + timedelta(minutes=minutes)
                await session.flush()
                return seat
        raise ValueError("نفدت المقاعد مؤقتاً")

    async def activate(self, session: AsyncSession, seat: ResourceSeat) -> TemporaryAccessSession | None:
        if seat.status not in {ResourceSeatStatus.HELD.value, ResourceSeatStatus.ACTIVE.value}:
            raise ValueError("المقعد غير محجوز")
        pool = await session.get(OfferResourcePool, seat.pool_id)
        seat.status = ResourceSeatStatus.ACTIVE.value
        seat.activated_at = datetime.now(UTC)
        seat.held_until = None
        if pool and pool.access_duration_minutes and seat.order_id and seat.user_id:
            ends = seat.activated_at + timedelta(minutes=pool.access_duration_minutes)
            seat.release_at = ends
            temp = await session.scalar(select(TemporaryAccessSession).where(
                TemporaryAccessSession.order_id == seat.order_id))
            if temp is None:
                temp = TemporaryAccessSession(order_id=seat.order_id, seat_id=seat.id,
                    user_id=seat.user_id, starts_at=seat.activated_at, ends_at=ends,
                    deletion_required=pool.deletion_required)
                session.add(temp)
            await session.flush()
            return temp
        await session.flush()
        return None

    async def release_expired_holds(self, session: AsyncSession, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        result = await session.execute(update(ResourceSeat).where(
            ResourceSeat.status == ResourceSeatStatus.HELD.value,
            ResourceSeat.held_until < now
        ).values(status=ResourceSeatStatus.AVAILABLE.value, order_id=None, user_id=None, held_until=None))
        return int(result.rowcount or 0)

    async def acknowledge_deletion(self, session: AsyncSession, order_id: int, user_id: int) -> bool:
        row = await session.scalar(select(TemporaryAccessSession).where(
            TemporaryAccessSession.order_id == order_id,
            TemporaryAccessSession.user_id == user_id).with_for_update())
        if not row:
            return False
        row.deletion_acknowledged_at = datetime.now(UTC)
        if row.seat_id:
            seat = await session.get(ResourceSeat, row.seat_id)
            if seat:
                seat.status = ResourceSeatStatus.AVAILABLE.value
                seat.order_id = seat.user_id = None
                seat.released_at = datetime.now(UTC)
        await session.flush()
        return True
