from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import as_utc
from app.core.utils import public_id
from app.db.models import (
    DeliveryJob,
    DeliveryJobStatus,
    InventoryItem,
    InventoryStatus,
    Order,
    OrderStatus,
    ProviderInboxItem,
    ProviderInboxItemKind,
    ProviderInboxItemStatus,
    StudentSubscription,
    StudentSubscriptionStatus,
    User,
    WarrantyClaim,
    WarrantyClaimEvent,
    WarrantyClaimStatus,
    WarrantyPolicy,
    WarrantyReplacement,
    WarrantyResolutionType,
)
from app.services.orders import OrderService
from app.services.provider_operations import ProviderOperationsService


@dataclass(slots=True, frozen=True)
class WarrantyEligibility:
    allowed: bool
    reason: str = ""


class WarrantyService:
    ACTIVE_CLAIM_STATUSES = {
        WarrantyClaimStatus.OPEN.value,
        WarrantyClaimStatus.IN_REVIEW.value,
        WarrantyClaimStatus.WAITING_STUDENT_ACTION.value,
        WarrantyClaimStatus.REPLACEMENT_PENDING.value,
        WarrantyClaimStatus.WAITING_STUDENT_CONFIRMATION.value,
    }

    def __init__(
        self,
        orders: OrderService,
        provider_operations: ProviderOperationsService,
    ) -> None:
        self.orders = orders
        self.provider_operations = provider_operations

    async def configure(
        self,
        session: AsyncSession,
        *,
        provider_id: int,
        offer_id: int,
        enabled: bool,
        response_sla_minutes: int = 60,
    ) -> WarrantyPolicy:
        if response_sla_minutes < 5 or response_sla_minutes > 1440:
            raise ValueError("مهلة الاستجابة للضمان غير صحيحة")
        row = await session.scalar(
            select(WarrantyPolicy)
            .where(WarrantyPolicy.offer_id == int(offer_id))
            .with_for_update()
        )
        if row is None:
            row = WarrantyPolicy(provider_id=int(provider_id), offer_id=int(offer_id))
            session.add(row)
        elif row.provider_id != int(provider_id):
            raise PermissionError("العرض لا يتبع هذه المنصة")
        row.is_enabled = bool(enabled)
        row.coverage_mode = "subscription_period"
        row.response_sla_minutes = int(response_sla_minutes)
        await session.flush()
        return row

    async def eligibility(
        self,
        session: AsyncSession,
        *,
        subscription: StudentSubscription,
        user: User,
    ) -> WarrantyEligibility:
        if subscription.user_id != user.id:
            return WarrantyEligibility(False, "غير مصرح")
        policy = await session.scalar(
            select(WarrantyPolicy).where(
                WarrantyPolicy.offer_id == subscription.offer_id,
                WarrantyPolicy.is_enabled.is_(True),
            )
        )
        if policy is None:
            return WarrantyEligibility(False, "هذا الاشتراك لا يتضمن ضماناً")
        if subscription.status not in {
            StudentSubscriptionStatus.ACTIVE.value,
            StudentSubscriptionStatus.EXPIRING.value,
            StudentSubscriptionStatus.WAITING_ACTIVATION.value,
            StudentSubscriptionStatus.NEEDS_SUPPORT.value,
        }:
            return WarrantyEligibility(False, "حالة الاشتراك لا تسمح بالمطالبة")
        now = datetime.now(UTC)
        coverage_end = as_utc(subscription.ends_at) or as_utc(subscription.warranty_ends_at)
        if coverage_end is None or coverage_end <= now:
            return WarrantyEligibility(False, "انتهت مدة ضمان الاشتراك")
        active = await session.scalar(
            select(WarrantyClaim.id).where(
                WarrantyClaim.subscription_id == subscription.id,
                WarrantyClaim.status.in_(self.ACTIVE_CLAIM_STATUSES),
            )
        )
        if active:
            return WarrantyEligibility(False, "توجد مطالبة ضمان مفتوحة لهذا الاشتراك")
        return WarrantyEligibility(True)

    async def open_claim(
        self,
        session: AsyncSession,
        *,
        subscription: StudentSubscription,
        user: User,
        category: str,
        screenshot_file_id: str,
        note: str = "",
    ) -> WarrantyClaim:
        if category not in {"otp", "logged_out", "other"}:
            raise ValueError("نوع مشكلة الضمان غير صحيح")
        if not screenshot_file_id:
            raise ValueError("لقطة الشاشة مطلوبة")
        locked_subscription = await session.scalar(
            select(StudentSubscription)
            .where(
                StudentSubscription.id == subscription.id,
                StudentSubscription.user_id == user.id,
            )
            .with_for_update()
        )
        if locked_subscription is None:
            raise ValueError("الاشتراك غير موجود أو غير مصرح")
        subscription = locked_subscription
        eligible = await self.eligibility(session, subscription=subscription, user=user)
        if not eligible.allowed:
            raise ValueError(eligible.reason)
        policy = await session.scalar(
            select(WarrantyPolicy).where(WarrantyPolicy.offer_id == subscription.offer_id)
        )
        if policy is None:
            raise ValueError("سياسة الضمان غير موجودة")
        key = f"warranty:subscription:{subscription.id}:opened:{int(datetime.now(UTC).timestamp())}"
        claim = WarrantyClaim(
            public_id=public_id("WRT"),
            idempotency_key=key,
            policy_id=policy.id,
            subscription_id=subscription.id,
            order_id=subscription.order_id,
            provider_id=subscription.provider_id,
            user_id=user.id,
            category=category,
            screenshot_file_id=screenshot_file_id,
            student_note=str(note)[:4000],
        )
        session.add(claim)
        await session.flush()
        session.add(
            WarrantyClaimEvent(
                claim_id=claim.id,
                actor_user_id=user.id,
                event_type="opened",
                to_status=claim.status,
                idempotency_key=f"warranty:{claim.id}:opened",
                metadata_json={"category": category},
            )
        )
        await self.provider_operations.enqueue_inbox(
            session,
            provider_id=subscription.provider_id,
            kind=ProviderInboxItemKind.WARRANTY.value,
            idempotency_key=f"warranty:{claim.id}:provider-inbox",
            title=f"⚠️ مطالبة ضمان {claim.public_id}",
            summary=(
                f"الطالب يبلغ عن مشكلة في الاشتراك {subscription.offer_name_snapshot}. "
                f"نوع المشكلة: {category}."
            ),
            order_id=subscription.order_id,
            user_id=user.id,
            source_type="warranty_claim",
            source_id=claim.id,
            file_id=screenshot_file_id,
            priority="urgent",
            payload={"subscription_id": subscription.id, "category": category},
        )
        subscription.status = StudentSubscriptionStatus.NEEDS_SUPPORT.value
        await session.flush()
        return claim

    async def allow_new_otp(
        self,
        session: AsyncSession,
        *,
        claim_id: int,
        provider_id: int,
        actor_user_id: int,
    ) -> WarrantyClaim:
        claim = await self._lock_claim(session, claim_id, provider_id)
        before = claim.status
        claim.status = WarrantyClaimStatus.WAITING_STUDENT_ACTION.value
        claim.resolution_type = WarrantyResolutionType.NEW_OTP_ALLOWED.value
        claim.first_response_at = claim.first_response_at or datetime.now(UTC)
        await self._event(
            session,
            claim,
            actor_user_id,
            "new_otp_allowed",
            before,
            claim.status,
        )
        return claim

    async def allocate_replacement(
        self,
        session: AsyncSession,
        *,
        claim_id: int,
        provider_id: int,
        actor_user_id: int,
    ) -> WarrantyClaim:
        claim = await self._lock_claim(session, claim_id, provider_id)
        existing = await session.scalar(
            select(WarrantyReplacement).where(WarrantyReplacement.claim_id == claim.id)
        )
        if existing:
            claim.status = WarrantyClaimStatus.WAITING_STUDENT_CONFIRMATION.value
            return claim
        subscription = await session.get(StudentSubscription, claim.subscription_id)
        order = await session.get(Order, claim.order_id)
        if not subscription or not order:
            raise ValueError("بيانات الاشتراك غير مكتملة")
        item = await session.scalar(
            select(InventoryItem)
            .where(
                InventoryItem.offer_id == subscription.offer_id,
                InventoryItem.status == InventoryStatus.AVAILABLE.value,
                (InventoryItem.expires_at.is_(None))
                | (InventoryItem.expires_at > datetime.now(UTC)),
            )
            .order_by(InventoryItem.expires_at.asc().nullslast(), InventoryItem.id.asc())
            .with_for_update(skip_locked=True)
        )
        if item is None:
            raise ValueError("لا يوجد حساب بديل متاح في المخزون")
        item.status = InventoryStatus.RESERVED.value
        item.reserved_order_id = order.id
        item.reserved_at = datetime.now(UTC)
        job = DeliveryJob(
            order_id=order.id,
            inventory_item_id=item.id,
            job_type="warranty_replacement",
            idempotency_key=f"warranty:{claim.id}:replacement-delivery",
            status=DeliveryJobStatus.PENDING.value,
        )
        session.add(job)
        await session.flush()
        replacement = WarrantyReplacement(
            claim_id=claim.id,
            old_inventory_item_id=subscription.inventory_item_id,
            new_inventory_item_id=item.id,
            delivery_job_id=job.id,
            replaced_by_user_id=int(actor_user_id),
        )
        session.add(replacement)
        before = claim.status
        claim.status = WarrantyClaimStatus.WAITING_STUDENT_CONFIRMATION.value
        claim.resolution_type = WarrantyResolutionType.REPLACEMENT_ACCOUNT.value
        claim.first_response_at = claim.first_response_at or datetime.now(UTC)
        # Keep the original subscription binding until the student confirms
        # the replacement works. WarrantyReplacement preserves the full audit trail.
        await self.orders.change_status(
            session,
            order,
            OrderStatus.WAITING_FULFILLMENT.value,
            actor_user_id=actor_user_id,
            note="تم اعتماد حساب بديل ضمن الضمان",
            metadata={"warranty_claim_id": claim.id},
        )
        await self._event(
            session,
            claim,
            actor_user_id,
            "replacement_allocated",
            before,
            claim.status,
            {"inventory_item_id": item.id, "delivery_job_id": job.id},
        )
        return claim

    async def provider_text_response(
        self,
        session: AsyncSession,
        *,
        claim_id: int,
        provider_id: int,
        actor_user_id: int,
        note: str,
    ) -> WarrantyClaim:
        message = str(note).strip()
        if len(message) < 2:
            raise ValueError("اكتب رداً واضحاً للطالب")
        claim = await self._lock_claim(session, claim_id, provider_id)
        before = claim.status
        claim.provider_note = message[:4000]
        claim.status = WarrantyClaimStatus.WAITING_STUDENT_CONFIRMATION.value
        claim.resolution_type = WarrantyResolutionType.TEXT_RESPONSE.value
        claim.first_response_at = claim.first_response_at or datetime.now(UTC)
        claim.assigned_user_id = int(actor_user_id)
        await self._event(
            session, claim, actor_user_id, "provider_text_response", before, claim.status,
            {"note_length": len(message)},
        )
        return claim

    async def student_confirm_success(
        self,
        session: AsyncSession,
        *,
        claim_id: int,
        user: User,
    ) -> WarrantyClaim:
        claim = await session.scalar(
            select(WarrantyClaim)
            .where(WarrantyClaim.id == int(claim_id), WarrantyClaim.user_id == user.id)
            .with_for_update()
        )
        if claim is None:
            raise ValueError("مطالبة الضمان غير موجودة")
        if claim.status not in {
            WarrantyClaimStatus.WAITING_STUDENT_CONFIRMATION.value,
            WarrantyClaimStatus.WAITING_STUDENT_ACTION.value,
        }:
            raise ValueError("المطالبة ليست بانتظار تأكيد الطالب")
        before = claim.status
        claim.status = WarrantyClaimStatus.RESOLVED.value
        claim.student_confirmed_at = datetime.now(UTC)
        claim.resolved_at = datetime.now(UTC)
        inbox_item = await session.scalar(
            select(ProviderInboxItem)
            .where(
                ProviderInboxItem.provider_id == claim.provider_id,
                ProviderInboxItem.source_type == "warranty_claim",
                ProviderInboxItem.source_id == claim.id,
            )
            .with_for_update()
        )
        if inbox_item is not None:
            inbox_item.status = ProviderInboxItemStatus.RESOLVED.value
            inbox_item.processed_at = datetime.now(UTC)
            inbox_item.processed_by_user_id = user.id
        subscription = await session.scalar(
            select(StudentSubscription)
            .where(StudentSubscription.id == claim.subscription_id)
            .with_for_update()
        )
        replacement = await session.scalar(
            select(WarrantyReplacement).where(WarrantyReplacement.claim_id == claim.id)
        )
        if subscription:
            if replacement is not None:
                subscription.inventory_item_id = replacement.new_inventory_item_id
            subscription.status = StudentSubscriptionStatus.ACTIVE.value
        await self._event(
            session,
            claim,
            user.id,
            "student_confirmed_success",
            before,
            claim.status,
        )
        return claim

    async def student_reports_problem(
        self,
        session: AsyncSession,
        *,
        claim_id: int,
        user: User,
        note: str = "",
    ) -> WarrantyClaim:
        claim = await session.scalar(
            select(WarrantyClaim)
            .where(WarrantyClaim.id == int(claim_id), WarrantyClaim.user_id == user.id)
            .with_for_update()
        )
        if claim is None:
            raise ValueError("مطالبة الضمان غير موجودة")
        before = claim.status
        claim.status = WarrantyClaimStatus.IN_REVIEW.value
        claim.student_note = (claim.student_note + "\n" + str(note)).strip()[:4000]
        await self._event(
            session,
            claim,
            user.id,
            "student_reports_problem",
            before,
            claim.status,
        )
        return claim

    async def _lock_claim(
        self, session: AsyncSession, claim_id: int, provider_id: int
    ) -> WarrantyClaim:
        claim = await session.scalar(
            select(WarrantyClaim)
            .where(
                WarrantyClaim.id == int(claim_id),
                WarrantyClaim.provider_id == int(provider_id),
            )
            .with_for_update()
        )
        if claim is None:
            raise ValueError("مطالبة الضمان غير موجودة")
        if claim.status not in self.ACTIVE_CLAIM_STATUSES:
            raise ValueError("تم إغلاق مطالبة الضمان")
        return claim

    async def _event(
        self,
        session: AsyncSession,
        claim: WarrantyClaim,
        actor_user_id: int | None,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        metadata: dict | None = None,
    ) -> None:
        event_number = int(
            await session.scalar(
                select(func.count())
                .select_from(WarrantyClaimEvent)
                .where(WarrantyClaimEvent.claim_id == claim.id)
            )
            or 0
        )
        key = f"warranty:{claim.id}:event:{event_number + 1}:{event_type}:{to_status or '-'}"
        existing = await session.scalar(
            select(WarrantyClaimEvent.id).where(WarrantyClaimEvent.idempotency_key == key)
        )
        if existing:
            return
        session.add(
            WarrantyClaimEvent(
                claim_id=claim.id,
                actor_user_id=actor_user_id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                idempotency_key=key,
                metadata_json=dict(metadata or {}),
            )
        )
        await session.flush()
