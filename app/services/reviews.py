from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order, OrderStatus, Review, User


class ReviewService:
    @staticmethod
    def stars(average: float, maximum: int = 5) -> str:
        """Render rounded provider rating as gold emoji stars plus empty stars."""
        filled = max(0, min(maximum, int(float(average or 0) + 0.5)))
        return "⭐" * filled + "☆" * (maximum - filled)

    async def submit_rating(
        self,
        session: AsyncSession,
        user: User,
        order: Order,
        rating: int,
    ) -> Review:
        if order.user_id != user.id:
            raise PermissionError("غير مصرح")
        if order.status != OrderStatus.COMPLETED.value:
            raise ValueError("يمكن تقييم الطلب بعد اكتماله فقط")
        if rating < 1 or rating > 5:
            raise ValueError("التقييم يجب أن يكون بين 1 و5")
        review = await session.scalar(
            select(Review)
            .where(Review.user_id == user.id, Review.order_id == order.id)
            .with_for_update()
        )
        if not review:
            review = Review(
                user_id=user.id,
                provider_id=order.provider_id,
                offer_id=order.offer_id,
                order_id=order.id,
                rating=rating,
            )
            session.add(review)
        else:
            review.rating = rating
        await session.flush()
        return review

    async def set_comment(
        self,
        session: AsyncSession,
        user: User,
        order_id: int,
        comment: str,
    ) -> Review:
        review = await session.scalar(
            select(Review)
            .where(Review.user_id == user.id, Review.order_id == order_id)
            .with_for_update()
        )
        if not review:
            raise ValueError("اختر التقييم أولًا")
        review.comment = comment.strip()[:1000]
        await session.flush()
        return review

    async def get_for_order(
        self, session: AsyncSession, user_id: int, order_id: int
    ) -> Review | None:
        return await session.scalar(
            select(Review).where(Review.user_id == user_id, Review.order_id == order_id)
        )

    async def provider_summaries(
        self, session: AsyncSession, provider_ids: list[int]
    ) -> dict[int, tuple[float, int]]:
        """Fetch all provider ratings in one grouped query.

        The catalog home used to issue one SQL query per provider, which became
        the dominant latency source as the number of platforms grew.
        """
        ids = sorted({int(provider_id) for provider_id in provider_ids})
        if not ids:
            return {}
        rows = (
            await session.execute(
                select(
                    Review.provider_id,
                    func.avg(Review.rating),
                    func.count(Review.id),
                )
                .where(Review.provider_id.in_(ids))
                .group_by(Review.provider_id)
            )
        ).all()
        result = {
            int(provider_id): (round(float(average or 0), 2), int(count or 0))
            for provider_id, average, count in rows
        }
        for provider_id in ids:
            result.setdefault(provider_id, (0.0, 0))
        return result

    async def provider_summary(self, session: AsyncSession, provider_id: int) -> tuple[float, int]:
        average, count = (
            await session.execute(
                select(func.avg(Review.rating), func.count(Review.id)).where(
                    Review.provider_id == provider_id
                )
            )
        ).one()
        return round(float(average or 0), 2), int(count or 0)
