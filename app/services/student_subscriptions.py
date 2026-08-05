from __future__ import annotations

import calendar
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import as_utc
from app.db.models import (
    InventoryItem,
    Offer,
    OfferValidityPolicy,
    Order,
    Provider,
    ReceiptSnapshot,
    StudentProfile,
    StudentSubscription,
    StudentSubscriptionStatus,
    SubscriptionStartTrigger,
    User,
    ValidityType,
    WarrantyPolicy,
)


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


class StudentSubscriptionService:
    async def policy(self, session: AsyncSession, offer: Offer) -> OfferValidityPolicy:
        policy = await session.scalar(
            select(OfferValidityPolicy).where(OfferValidityPolicy.offer_id == offer.id)
        )
        if policy:
            return policy
        policy = OfferValidityPolicy(
            offer_id=offer.id,
            validity_type=ValidityType.DAYS_FROM_ACTIVATION.value,
            duration_value=offer.duration_days or 30,
            start_trigger=SubscriptionStartTrigger.DELIVERY.value,
        )
        session.add(policy)
        await session.flush()
        return policy

    async def validate_sale(self, session: AsyncSession, offer: Offer) -> OfferValidityPolicy:
        policy = await self.policy(session, offer)
        now = datetime.now(UTC)
        if policy.validity_type == ValidityType.FIXED_OFFER_END.value:
            fixed_end = as_utc(policy.fixed_end_at)
            if not fixed_end or fixed_end <= now:
                raise ValueError("انتهت صلاحية هذا العرض")
            remaining = (fixed_end - now).total_seconds() / 86400
            if remaining < policy.min_remaining_days:
                raise ValueError("المدة المتبقية أقل من الحد المسموح للبيع")
        return policy

    def validity_label(
        self,
        policy: OfferValidityPolicy,
        inventory_item: InventoryItem | None = None,
        now: datetime | None = None,
    ) -> str:
        now = now or datetime.now(UTC)
        if policy.validity_type == ValidityType.DAYS_FROM_ACTIVATION.value:
            return f"{policy.duration_value or 0} يومًا من تاريخ التفعيل"
        if policy.validity_type == ValidityType.MONTHS_FROM_ACTIVATION.value:
            return f"{policy.duration_value or 0} شهرًا من تاريخ التفعيل"
        if policy.validity_type == ValidityType.FIXED_OFFER_END.value:
            if not policy.fixed_end_at:
                return "تاريخ انتهاء ثابت غير محدد"
            fixed_end = as_utc(policy.fixed_end_at)
            if not fixed_end:
                return "تاريخ انتهاء ثابت غير محدد"
            remaining = max(0, int((fixed_end - now).total_seconds() // 86400))
            return f"ينتهي بتاريخ {fixed_end:%d/%m/%Y} — المتبقي نحو {remaining} يوم"
        if policy.validity_type == ValidityType.INVENTORY_END.value:
            if inventory_item and inventory_item.expires_at:
                return f"حسب الحساب — ينتهي بتاريخ {inventory_item.expires_at:%d/%m/%Y}"
            return "حسب تاريخ الحساب المخصص من المخزون"
        return "يحدد عند التسليم"

    def _compute_end(
        self,
        policy: OfferValidityPolicy,
        starts_at: datetime,
        inventory_item: InventoryItem | None = None,
    ) -> datetime | None:
        if policy.validity_type == ValidityType.DAYS_FROM_ACTIVATION.value:
            return starts_at + timedelta(days=max(1, policy.duration_value or 1))
        if policy.validity_type == ValidityType.MONTHS_FROM_ACTIVATION.value:
            return _add_months(starts_at, max(1, policy.duration_value or 1))
        if policy.validity_type == ValidityType.FIXED_OFFER_END.value:
            return as_utc(policy.fixed_end_at)
        if policy.validity_type == ValidityType.INVENTORY_END.value:
            return as_utc(inventory_item.expires_at) if inventory_item else None
        return None

    async def ensure_for_order(
        self,
        session: AsyncSession,
        order: Order,
        inventory_item: InventoryItem | None = None,
    ) -> StudentSubscription:
        existing = await session.scalar(
            select(StudentSubscription).where(StudentSubscription.order_id == order.id)
        )
        if existing:
            if inventory_item and not existing.inventory_item_id:
                existing.inventory_item_id = inventory_item.id
            return existing
        offer = await session.get(Offer, order.offer_id)
        provider = await session.get(Provider, order.provider_id)
        if not offer or not provider:
            raise ValueError("بيانات الاشتراك ناقصة")
        policy = await self.policy(session, offer)
        service_name = offer.title
        # The service snapshot intentionally falls back to the offer title. The
        # catalog hierarchy can be renamed later without changing old receipts.
        subscription = StudentSubscription(
            order_id=order.id,
            user_id=order.user_id,
            provider_id=order.provider_id,
            offer_id=order.offer_id,
            inventory_item_id=inventory_item.id if inventory_item else None,
            provider_name_snapshot=provider.name_ar,
            service_name_snapshot=service_name,
            offer_name_snapshot=offer.title,
            validity_type=policy.validity_type,
            duration_value=policy.duration_value,
            status=StudentSubscriptionStatus.PENDING.value,
            ordered_at=order.created_at,
        )
        session.add(subscription)
        await session.flush()
        return subscription

    async def mark_payment_approved(
        self, session: AsyncSession, order: Order
    ) -> StudentSubscription:
        subscription = await self.ensure_for_order(session, order)
        offer = await session.get(Offer, order.offer_id)
        if not offer:
            raise ValueError("العرض غير موجود")
        policy = await self.policy(session, offer)
        now = datetime.now(UTC)
        subscription.payment_approved_at = now
        subscription.status = StudentSubscriptionStatus.WAITING_ACTIVATION.value
        if policy.start_trigger == SubscriptionStartTrigger.PAYMENT_APPROVED.value:
            subscription.starts_at = now
            subscription.ends_at = self._compute_end(policy, now)
            subscription.status = StudentSubscriptionStatus.ACTIVE.value
        await session.flush()
        return subscription

    async def mark_delivered(
        self,
        session: AsyncSession,
        order: Order,
        inventory_item: InventoryItem | None = None,
    ) -> StudentSubscription:
        subscription = await self.ensure_for_order(session, order, inventory_item)
        offer = await session.get(Offer, order.offer_id)
        if not offer:
            raise ValueError("العرض غير موجود")
        policy = await self.policy(session, offer)
        now = datetime.now(UTC)
        subscription.delivered_at = now
        subscription.status = StudentSubscriptionStatus.WAITING_ACTIVATION.value
        if policy.start_trigger == SubscriptionStartTrigger.DELIVERY.value:
            subscription.starts_at = now
            subscription.activated_at = now
            subscription.ends_at = self._compute_end(policy, now, inventory_item)
            subscription.status = StudentSubscriptionStatus.ACTIVE.value
        warranty_policy = await session.scalar(
            select(WarrantyPolicy).where(
                WarrantyPolicy.offer_id == offer.id,
                WarrantyPolicy.is_enabled.is_(True),
            )
        )
        if warranty_policy and subscription.ends_at:
            subscription.warranty_ends_at = subscription.ends_at
        else:
            subscription.warranty_ends_at = now + timedelta(hours=max(1, policy.warranty_hours))
        subscription.objection_ends_at = now + timedelta(hours=max(1, policy.objection_hours))
        await self.ensure_receipt(session, order, subscription)
        await session.flush()
        return subscription

    async def mark_needs_support(
        self,
        session: AsyncSession,
        order: Order,
        reason: str = "",
    ) -> StudentSubscription:
        """Finish a failed fulfilment transition without leaving the lifecycle frozen."""
        subscription = await self.ensure_for_order(session, order)
        terminal = {
            StudentSubscriptionStatus.ACTIVE.value,
            StudentSubscriptionStatus.EXPIRED.value,
            StudentSubscriptionStatus.CANCELLED.value,
            StudentSubscriptionStatus.REFUNDED.value,
        }
        if subscription.status not in terminal:
            subscription.status = StudentSubscriptionStatus.NEEDS_SUPPORT.value
        await session.flush()
        return subscription

    async def provider_order_snapshot(
        self, session: AsyncSession, order: Order
    ) -> dict[str, object]:
        """Return one provider-safe student/CV/subscription snapshot for dashboards."""
        subscription = await session.scalar(
            select(StudentSubscription).where(StudentSubscription.order_id == order.id)
        )
        profile = await session.scalar(
            select(StudentProfile).where(StudentProfile.user_id == order.user_id)
        )
        return {
            "profile": profile,
            "subscription": subscription,
            "starts_at": as_utc(subscription.starts_at) if subscription else None,
            "ends_at": as_utc(subscription.ends_at) if subscription else None,
            "subscription_status": (
                subscription.status
                if subscription
                else StudentSubscriptionStatus.PENDING.value
            ),
        }

    async def activate(self, session: AsyncSession, order: Order) -> StudentSubscription:
        subscription = await self.ensure_for_order(session, order)
        offer = await session.get(Offer, order.offer_id)
        if not offer:
            raise ValueError("العرض غير موجود")
        policy = await self.policy(session, offer)
        inventory = (
            await session.get(InventoryItem, subscription.inventory_item_id)
            if subscription.inventory_item_id
            else None
        )
        now = datetime.now(UTC)
        subscription.activated_at = now
        if not subscription.starts_at:
            subscription.starts_at = now
        subscription.ends_at = self._compute_end(policy, subscription.starts_at, inventory)
        subscription.status = StudentSubscriptionStatus.ACTIVE.value
        warranty_policy = await session.scalar(
            select(WarrantyPolicy).where(
                WarrantyPolicy.offer_id == offer.id,
                WarrantyPolicy.is_enabled.is_(True),
            )
        )
        if warranty_policy and subscription.ends_at:
            subscription.warranty_ends_at = subscription.ends_at
        elif not subscription.warranty_ends_at:
            subscription.warranty_ends_at = now + timedelta(hours=max(1, policy.warranty_hours))
        if not subscription.objection_ends_at:
            subscription.objection_ends_at = now + timedelta(hours=max(1, policy.objection_hours))
        await self.ensure_receipt(session, order, subscription)
        await session.flush()
        return subscription

    async def ensure_receipt(
        self,
        session: AsyncSession,
        order: Order,
        subscription: StudentSubscription,
    ) -> ReceiptSnapshot:
        existing = await session.scalar(
            select(ReceiptSnapshot).where(ReceiptSnapshot.order_id == order.id)
        )
        from app.db.models import PaymentMethod

        payment_method = (
            await session.get(PaymentMethod, order.payment_method_id)
            if order.payment_method_id
            else None
        )
        payment_method_name = payment_method.name if payment_method else "غير محدد"
        snapshot = {
            "order_public_id": order.public_id,
            "provider": subscription.provider_name_snapshot,
            "service": subscription.service_name_snapshot,
            "offer": subscription.offer_name_snapshot,
            "ordered_at": order.created_at.isoformat(),
            "payment_approved_at": subscription.payment_approved_at.isoformat()
            if subscription.payment_approved_at
            else None,
            "delivered_at": subscription.delivered_at.isoformat()
            if subscription.delivered_at
            else None,
            "starts_at": subscription.starts_at.isoformat() if subscription.starts_at else None,
            "ends_at": subscription.ends_at.isoformat() if subscription.ends_at else None,
            "validity_type": subscription.validity_type,
            "subtotal_iqd": order.subtotal_iqd,
            "service_fee_iqd": order.service_fee_iqd,
            "total_iqd": order.total_iqd,
            "payment_method": payment_method_name,
        }
        if existing:
            existing.subscription_id = subscription.id
            existing.snapshot = snapshot
            await session.flush()
            return existing
        receipt = ReceiptSnapshot(
            order_id=order.id,
            subscription_id=subscription.id,
            snapshot=snapshot,
        )
        session.add(receipt)
        await session.flush()
        return receipt

    async def user_subscriptions(
        self, session: AsyncSession, user: User, limit: int = 50
    ) -> list[StudentSubscription]:
        items, _total = await self.user_subscriptions_page(
            session, user, filter_key="all", page=0, page_size=max(1, min(limit, 100))
        )
        return items

    @staticmethod
    def _subscription_filter(filter_key: str):
        key = (filter_key or "all").strip().lower()
        if key == "active":
            return StudentSubscription.status == StudentSubscriptionStatus.ACTIVE.value
        if key == "expiring":
            return StudentSubscription.status == StudentSubscriptionStatus.EXPIRING.value
        if key == "pending":
            return StudentSubscription.status.in_(
                [
                    StudentSubscriptionStatus.PENDING.value,
                    StudentSubscriptionStatus.WAITING_ACTIVATION.value,
                ]
            )
        if key == "expired":
            return StudentSubscription.status == StudentSubscriptionStatus.EXPIRED.value
        return None

    async def user_subscriptions_page(
        self,
        session: AsyncSession,
        user: User,
        *,
        filter_key: str = "all",
        page: int = 0,
        page_size: int = 8,
    ) -> tuple[list[StudentSubscription], int]:
        page = max(0, int(page))
        page_size = max(1, min(int(page_size), 20))
        conditions = [StudentSubscription.user_id == user.id]
        status_filter = self._subscription_filter(filter_key)
        if status_filter is not None:
            conditions.append(status_filter)
        total = int(
            await session.scalar(
                select(func.count(StudentSubscription.id)).where(*conditions)
            )
            or 0
        )
        rows = list(
            (
                await session.scalars(
                    select(StudentSubscription)
                    .where(*conditions)
                    .order_by(
                        StudentSubscription.created_at.desc(),
                        StudentSubscription.id.desc(),
                    )
                    .offset(page * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return rows, total

    async def user_subscription_counts(
        self, session: AsyncSession, user: User
    ) -> dict[str, int]:
        rows = list(
            (
                await session.execute(
                    select(StudentSubscription.status, func.count(StudentSubscription.id))
                    .where(StudentSubscription.user_id == user.id)
                    .group_by(StudentSubscription.status)
                )
            ).all()
        )
        by_status = {str(status): int(count) for status, count in rows}
        return {
            "all": sum(by_status.values()),
            "active": by_status.get(StudentSubscriptionStatus.ACTIVE.value, 0),
            "expiring": by_status.get(StudentSubscriptionStatus.EXPIRING.value, 0),
            "pending": by_status.get(StudentSubscriptionStatus.PENDING.value, 0)
            + by_status.get(StudentSubscriptionStatus.WAITING_ACTIVATION.value, 0),
            "expired": by_status.get(StudentSubscriptionStatus.EXPIRED.value, 0),
        }

    async def get_for_user(
        self, session: AsyncSession, subscription_id: int, user: User
    ) -> StudentSubscription | None:
        return await session.scalar(
            select(StudentSubscription).where(
                StudentSubscription.id == subscription_id,
                StudentSubscription.user_id == user.id,
            )
        )

    async def receipt(self, session: AsyncSession, order_id: int) -> ReceiptSnapshot | None:
        return await session.scalar(
            select(ReceiptSnapshot).where(ReceiptSnapshot.order_id == order_id)
        )

    async def sync_statuses(self, session: AsyncSession) -> list[StudentSubscription]:
        now = datetime.now(UTC)
        subscriptions = list(
            (
                await session.scalars(
                    select(StudentSubscription).where(
                        StudentSubscription.status.in_(
                            [
                                StudentSubscriptionStatus.ACTIVE.value,
                                StudentSubscriptionStatus.EXPIRING.value,
                            ]
                        )
                    )
                )
            ).all()
        )
        changed: list[StudentSubscription] = []
        for subscription in subscriptions:
            if not subscription.ends_at:
                continue
            ends_at = as_utc(subscription.ends_at)
            if not ends_at:
                continue
            remaining = ends_at - now
            old = subscription.status
            if remaining.total_seconds() <= 0:
                subscription.status = StudentSubscriptionStatus.EXPIRED.value
            elif remaining <= timedelta(days=7):
                subscription.status = StudentSubscriptionStatus.EXPIRING.value
            else:
                subscription.status = StudentSubscriptionStatus.ACTIVE.value
            if old != subscription.status:
                changed.append(subscription)
        await session.flush()
        return changed
