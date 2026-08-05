from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import public_id
from app.db.models import (
    AdCampaign,
    AdCampaignRecipient,
    Announcement,
    AnnouncementStatus,
    BusinessInvoice,
    BusinessInvoiceProof,
    BusinessInvoiceStatus,
    BotIssueReport,
    CampaignStatus,
    CouponAssignment,
    CouponCampaign,
    FavoriteTargetType,
    FinancialProofRegistry,
    HybridBundle,
    HybridBundleComponent,
    HybridBundlePurchase,
    HybridBundleStatus,
    HybridInventoryHold,
    HybridPurchaseProof,
    HybridPurchaseStatus,
    HybridRevenueAllocation,
    MissingServiceRequest,
    DeliveryJob,
    DeliveryJobStatus,
    DeliveryType,
    InventoryItem,
    InventoryStatus,
    Offer,
    OfferStatus,
    Order,
    OrderCoupon,
    OrderStatus,
    OwnerInboxItem,
    OwnerInboxKind,
    OwnerInboxStatus,
    Provider,
    ProviderBillingPolicy,
    ProviderStatus,
    PurchaseReservation,
    ReservationStatus,
    RewardTaskCampaign,
    RewardTaskCompletion,
    RewardTaskStatus,
    StudentFavorite,
    StudentProfile,
    StudentRewardStatus,
    StudentSubscription,
    SupportTicket,
    TicketStatus,
    User,
    WalletEntryType,
    WalletOwnerType,
)
from app.domain.owner_commerce import (
    HybridAllocation,
    billing_decision,
    normalize_audience_rule,
    reward_campaign_capacity,
    validate_hybrid_allocations,
)
from app.services.announcements import AnnouncementService
from app.services.enterprise import EnterpriseCoreService
from app.services.order_coupons import OrderCouponService
from app.services.wallets import WalletService


class OwnerCommerceService:
    """Owner-side commercial control plane for V11.4.

    All public mutations are idempotent or protected by row locks. Telegram is
    treated as a presentation layer; PostgreSQL remains the source of truth.
    """

    def __init__(
        self,
        *,
        enterprise: EnterpriseCoreService,
        wallets: WalletService,
        announcements: AnnouncementService,
        order_coupons: OrderCouponService,
    ) -> None:
        self.enterprise = enterprise
        self.wallets = wallets
        self.announcements = announcements
        self.order_coupons = order_coupons

    async def _claim_financial_proof(
        self, session: AsyncSession, *, file_unique_id: str, source_type: str,
        source_id: int, submitted_by_user_id: int, provider_id: int | None
    ) -> str:
        normalized = (file_unique_id or "").strip()
        if not normalized:
            raise ValueError("تعذر التحقق من بصمة ملف الإثبات")
        fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        existing = await session.scalar(
            select(FinancialProofRegistry)
            .where(FinancialProofRegistry.fingerprint == fingerprint)
            .with_for_update()
        )
        if existing:
            if existing.source_type == source_type and existing.source_id == int(source_id):
                return fingerprint
            raise ValueError("تم استخدام صورة الإثبات نفسها في عملية مالية أخرى")
        session.add(FinancialProofRegistry(
            fingerprint=fingerprint, source_type=source_type, source_id=int(source_id),
            submitted_by_user_id=int(submitted_by_user_id), provider_id=provider_id,
        ))
        await session.flush()
        return fingerprint

    async def audience_user_ids(
        self,
        session: AsyncSession,
        rule: dict[str, Any] | None,
        *,
        marketing_only: bool,
    ) -> list[int]:
        normalized = normalize_audience_rule(rule)
        kind = normalized["type"]
        limit = int(normalized["limit"])
        query = select(User.id).where(
            User.is_active.is_(True),
            User.is_banned.is_(False),
        )
        if marketing_only:
            query = query.where(User.marketing_opt_in.is_(True))

        value = normalized.get("value")
        if kind in {"college", "university", "department", "stage", "governorate"}:
            field = getattr(StudentProfile, kind)
            query = query.join(StudentProfile, StudentProfile.user_id == User.id).where(field == str(value))
        elif kind in {"provider_buyers", "provider_top_buyers"}:
            provider_id = int(value)
            query = (
                query.join(Order, Order.user_id == User.id)
                .where(
                    Order.provider_id == provider_id,
                    Order.status.in_(
                        [
                            OrderStatus.PAID.value,
                            OrderStatus.DELIVERED.value,
                            OrderStatus.COMPLETED.value,
                        ]
                    ),
                )
                .group_by(User.id)
            )
            if kind == "provider_top_buyers":
                query = query.order_by(func.count(Order.id).desc(), User.id)
        elif kind == "expired_subscription":
            provider_id = int(value)
            now = datetime.now(UTC)
            query = query.join(StudentSubscription, StudentSubscription.user_id == User.id).where(
                StudentSubscription.provider_id == provider_id,
                StudentSubscription.ends_at.is_not(None),
                StudentSubscription.ends_at <= now,
                StudentSubscription.ends_at >= now - timedelta(days=7),
            )
        elif kind == "favorite_offer":
            query = query.join(StudentFavorite, StudentFavorite.user_id == User.id).where(
                StudentFavorite.target_type == FavoriteTargetType.OFFER.value,
                StudentFavorite.target_id == int(value),
            )
        elif kind == "status_link_sharers":
            query = query.join(StudentRewardStatus, StudentRewardStatus.user_id == User.id).where(
                StudentRewardStatus.status_link_shares > 0
            ).order_by(StudentRewardStatus.status_link_shares.desc(), User.id)
        elif kind == "most_active":
            query = query.join(StudentRewardStatus, StudentRewardStatus.user_id == User.id).order_by(
                StudentRewardStatus.status_points.desc(), User.id
            )

        return list((await session.scalars(query.distinct().limit(limit))).all())

    async def upsert_billing_policy(
        self,
        session: AsyncSession,
        *,
        provider_id: int,
        cycle_days: int,
        due_hours: int,
        fixed_service_fee_iqd: int,
        ad_hourly_rate_iqd: int,
        auto_suspend: bool,
    ) -> ProviderBillingPolicy:
        if cycle_days not in {7, 30}:
            raise ValueError("دورة الفوترة يجب أن تكون أسبوعية أو شهرية")
        if not 1 <= due_hours <= 24 * 30:
            raise ValueError("مهلة السداد غير صالحة")
        if fixed_service_fee_iqd < 0 or ad_hourly_rate_iqd < 0:
            raise ValueError("الرسوم لا يمكن أن تكون سالبة")
        provider = await session.get(Provider, provider_id)
        if not provider:
            raise ValueError("المنصة غير موجودة")
        policy = await session.scalar(
            select(ProviderBillingPolicy)
            .where(ProviderBillingPolicy.provider_id == provider_id)
            .with_for_update()
        )
        if not policy:
            policy = ProviderBillingPolicy(provider_id=provider_id)
            session.add(policy)
        policy.cycle_days = cycle_days
        policy.due_hours = due_hours
        policy.fixed_service_fee_iqd = int(fixed_service_fee_iqd)
        policy.ad_hourly_rate_iqd = int(ad_hourly_rate_iqd)
        policy.auto_suspend = bool(auto_suspend)
        policy.is_active = True
        if not policy.next_invoice_at:
            policy.next_invoice_at = datetime.now(UTC)
        await session.flush()
        return policy

    async def issue_due_invoices(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
    ) -> list[BusinessInvoice]:
        moment = now or datetime.now(UTC)
        policies = list(
            (
                await session.scalars(
                    select(ProviderBillingPolicy)
                    .where(
                        ProviderBillingPolicy.is_active.is_(True),
                        ProviderBillingPolicy.next_invoice_at <= moment,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        invoices: list[BusinessInvoice] = []
        for policy in policies:
            decision = billing_decision(
                next_invoice_at=policy.next_invoice_at,
                cycle_days=policy.cycle_days,
                due_hours=policy.due_hours,
                now=moment,
            )
            if not decision.should_issue:
                continue
            period_key = policy.next_invoice_at.date().isoformat()
            policy.next_invoice_at = decision.next_invoice_at
            # A zero-fee policy is a deliberate exemption, not a one-dinar invoice.
            if int(policy.fixed_service_fee_iqd) == 0:
                continue
            invoice = await self.enterprise.issue_invoice(
                session,
                provider_id=policy.provider_id,
                subscription_id=None,
                amount_iqd=int(policy.fixed_service_fee_iqd),
                idempotency_key=f"provider-billing:{policy.provider_id}:{period_key}",
                due_days=max(1, (policy.due_hours + 23) // 24),
                description="رسوم CampusPass IQ الدورية",
            )
            invoice.due_at = decision.due_at
            invoices.append(invoice)
        await session.flush()
        return invoices

    async def submit_invoice_proof(
        self,
        session: AsyncSession,
        *,
        invoice_id: int,
        provider_id: int,
        submitted_by_user_id: int,
        file_id: str,
        file_type: str,
        claimed_amount_iqd: int,
        file_unique_id: str,
    ) -> BusinessInvoiceProof:
        invoice = await session.scalar(
            select(BusinessInvoice).where(BusinessInvoice.id == invoice_id).with_for_update()
        )
        if not invoice or invoice.provider_id != provider_id:
            raise ValueError("الفاتورة لا تخص هذه المنصة")
        if invoice.status == BusinessInvoiceStatus.PAID.value:
            raise ValueError("الفاتورة مسددة مسبقاً")
        fingerprint = await self._claim_financial_proof(
            session, file_unique_id=file_unique_id, source_type="business_invoice",
            source_id=invoice.id, submitted_by_user_id=submitted_by_user_id,
            provider_id=provider_id,
        )
        existing = await session.scalar(
            select(BusinessInvoiceProof).where(
                BusinessInvoiceProof.file_fingerprint == fingerprint
            )
        )
        if existing:
            return existing
        proof = BusinessInvoiceProof(
            invoice_id=invoice.id,
            provider_id=provider_id,
            submitted_by_user_id=submitted_by_user_id,
            file_id=file_id,
            file_type=file_type,
            file_fingerprint=fingerprint,
            claimed_amount_iqd=max(0, int(claimed_amount_iqd)),
            status="pending",
        )
        session.add(proof)
        invoice.status = BusinessInvoiceStatus.ISSUED.value
        await session.flush()
        await self.ensure_owner_inbox_item(
            session,
            kind=OwnerInboxKind.BILLING_PROOF.value,
            source_type="business_invoice_proof",
            source_id=proof.id,
            provider_id=provider_id,
            user_id=submitted_by_user_id,
            summary=f"وصل تسديد للفاتورة {invoice.invoice_number}",
            payload={"invoice_id": invoice.id, "proof_id": proof.id},
            priority=20,
        )
        return proof

    async def review_invoice_proof(
        self,
        session: AsyncSession,
        *,
        proof_id: int,
        admin_user_id: int,
        approved: bool,
        reason: str = "",
    ) -> BusinessInvoiceProof:
        proof = await session.scalar(
            select(BusinessInvoiceProof)
            .where(BusinessInvoiceProof.id == proof_id)
            .with_for_update()
        )
        if not proof:
            raise ValueError("إثبات الدفع غير موجود")
        if proof.status in {"approved", "rejected"}:
            return proof
        invoice = await session.scalar(
            select(BusinessInvoice)
            .where(BusinessInvoice.id == proof.invoice_id)
            .with_for_update()
        )
        if not invoice:
            raise ValueError("الفاتورة غير موجودة")
        proof.reviewed_by_user_id = admin_user_id
        proof.reviewed_at = datetime.now(UTC)
        if approved:
            if proof.claimed_amount_iqd < invoice.total_iqd:
                raise ValueError("المبلغ المرفوع أقل من قيمة الفاتورة")
            proof.status = "approved"
            await self.enterprise.mark_invoice_paid(
                session,
                invoice_id=invoice.id,
                payment_idempotency_key=f"business-invoice:{invoice.id}:proof:{proof.id}",
            )
            await self._restore_provider_if_clear(session, invoice.provider_id)
        else:
            proof.status = "rejected"
            proof.rejection_reason = reason[:1000]
        await self.resolve_owner_inbox_source(
            session, source_type="business_invoice_proof", source_id=proof.id,
            accepted=approved,
        )
        await session.flush()
        return proof

    async def enforce_overdue_billing(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
    ) -> list[int]:
        moment = now or datetime.now(UTC)
        invoices = list(
            (
                await session.scalars(
                    select(BusinessInvoice)
                    .where(
                        BusinessInvoice.status.in_(
                            [
                                BusinessInvoiceStatus.ISSUED.value,
                                BusinessInvoiceStatus.PARTIALLY_PAID.value,
                            ]
                        ),
                        BusinessInvoice.due_at < moment,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        suspended: list[int] = []
        for invoice in invoices:
            invoice.status = BusinessInvoiceStatus.OVERDUE.value
            policy = await session.scalar(
                select(ProviderBillingPolicy).where(
                    ProviderBillingPolicy.provider_id == invoice.provider_id
                )
            )
            if policy and policy.auto_suspend:
                provider = await session.scalar(
                    select(Provider).where(Provider.id == invoice.provider_id).with_for_update()
                )
                if provider:
                    provider.status = ProviderStatus.SUSPENDED.value
                    provider.is_active = False
                    suspended.append(provider.id)
        await session.flush()
        return suspended

    async def _restore_provider_if_clear(self, session: AsyncSession, provider_id: int) -> None:
        overdue = await session.scalar(
            select(func.count(BusinessInvoice.id)).where(
                BusinessInvoice.provider_id == provider_id,
                BusinessInvoice.status == BusinessInvoiceStatus.OVERDUE.value,
            )
        )
        if int(overdue or 0) == 0:
            provider = await session.scalar(
                select(Provider).where(Provider.id == provider_id).with_for_update()
            )
            if provider and provider.status == ProviderStatus.SUSPENDED.value:
                provider.status = ProviderStatus.ACTIVE.value
                provider.is_active = True

    async def ensure_owner_inbox_item(
        self,
        session: AsyncSession,
        *,
        kind: str,
        source_type: str,
        source_id: int,
        summary: str,
        payload: dict[str, Any] | None = None,
        provider_id: int | None = None,
        user_id: int | None = None,
        order_id: int | None = None,
        priority: int = 100,
    ) -> OwnerInboxItem:
        existing = await session.scalar(
            select(OwnerInboxItem).where(
                OwnerInboxItem.source_type == source_type,
                OwnerInboxItem.source_id == source_id,
            )
        )
        if existing:
            return existing
        item = OwnerInboxItem(
            public_id=public_id("IN"),
            kind=kind,
            source_type=source_type,
            source_id=source_id,
            summary=summary[:500],
            payload_json=payload or {},
            provider_id=provider_id,
            user_id=user_id,
            order_id=order_id,
            priority=max(1, int(priority)),
        )
        session.add(item)
        await session.flush()
        return item

    async def resolve_owner_inbox_source(
        self,
        session: AsyncSession,
        *,
        source_type: str,
        source_id: int,
        accepted: bool,
    ) -> None:
        item = await session.scalar(
            select(OwnerInboxItem)
            .where(
                OwnerInboxItem.source_type == source_type,
                OwnerInboxItem.source_id == source_id,
            )
            .with_for_update()
        )
        if item:
            item.status = (
                OwnerInboxStatus.RESOLVED.value if accepted else OwnerInboxStatus.REJECTED.value
            )
            item.resolved_at = datetime.now(UTC)

    async def sync_central_inbox(self, session: AsyncSession, *, limit: int = 100) -> int:
        """Materialize legacy/support sources into the single owner inbox.

        The source tables remain authoritative. This function is idempotent due to
        the unique (source_type, source_id) key on the inbox table.
        """
        created = 0
        missing = list((await session.scalars(
            select(MissingServiceRequest)
            .where(MissingServiceRequest.status == "new")
            .order_by(MissingServiceRequest.id)
            .limit(limit)
        )).all())
        for item in missing:
            before = await session.scalar(select(OwnerInboxItem.id).where(
                OwnerInboxItem.source_type == "missing_service",
                OwnerInboxItem.source_id == item.id,
            ))
            await self.ensure_owner_inbox_item(
                session, kind=OwnerInboxKind.MISSING_SERVICE.value,
                source_type="missing_service", source_id=item.id, user_id=item.user_id,
                summary=f"خدمة مقترحة: {item.service_name}",
                payload={"service_name": item.service_name, "details": item.details}, priority=60,
            )
            created += int(before is None)

        issues = list((await session.scalars(
            select(BotIssueReport)
            .where(BotIssueReport.status.in_(["open", "in_progress"]))
            .order_by(BotIssueReport.id)
            .limit(limit)
        )).all())
        for issue in issues:
            before = await session.scalar(select(OwnerInboxItem.id).where(
                OwnerInboxItem.source_type == "bot_issue",
                OwnerInboxItem.source_id == issue.id,
            ))
            await self.ensure_owner_inbox_item(
                session, kind=OwnerInboxKind.BOT_ISSUE.value,
                source_type="bot_issue", source_id=issue.id, user_id=issue.user_id,
                summary=f"بلاغ بوت: {issue.category}",
                payload={"description": issue.description, "file_id": issue.file_id}, priority=30,
            )
            created += int(before is None)

        tickets = list((await session.scalars(
            select(SupportTicket)
            .where(
                SupportTicket.provider_id.is_(None),
                SupportTicket.status.in_([
                    TicketStatus.OPEN.value, TicketStatus.IN_PROGRESS.value,
                    TicketStatus.WAITING_USER.value, TicketStatus.WAITING_PROVIDER.value,
                ]),
            )
            .order_by(SupportTicket.id)
            .limit(limit)
        )).all())
        for ticket in tickets:
            kind = (
                OwnerInboxKind.APPEAL.value
                if ticket.category in {"appeal", "refund_appeal"}
                else OwnerInboxKind.CUSTOM_QUESTION.value
            )
            before = await session.scalar(select(OwnerInboxItem.id).where(
                OwnerInboxItem.source_type == "support_ticket",
                OwnerInboxItem.source_id == ticket.id,
            ))
            await self.ensure_owner_inbox_item(
                session, kind=kind, source_type="support_ticket", source_id=ticket.id,
                user_id=ticket.user_id, order_id=ticket.order_id,
                summary=ticket.subject or f"تذكرة {ticket.public_id}",
                payload={"category": ticket.category, "priority": ticket.priority},
                priority=10 if kind == OwnerInboxKind.APPEAL.value else 50,
            )
            created += int(before is None)
        await session.flush()
        return created

    async def create_ad_campaign(
        self,
        session: AsyncSession,
        *,
        provider_id: int | None,
        requested_by_user_id: int,
        campaign_type: str,
        title: str,
        body: str,
        duration_hours: int,
        hourly_rate_iqd: int,
        audience_rule: dict[str, Any],
        offer_id: int | None = None,
        idempotency_key: str,
    ) -> AdCampaign:
        existing = await session.scalar(
            select(AdCampaign).where(AdCampaign.idempotency_key == idempotency_key)
        )
        if existing:
            return existing
        if campaign_type not in {"broadcast", "pinned", "offer", "task"}:
            raise ValueError("نوع الإعلان غير مدعوم")
        if not 1 <= duration_hours <= 24 * 90:
            raise ValueError("مدة الإعلان غير صالحة")
        rule = normalize_audience_rule(audience_rule)
        if provider_id is not None:
            provider = await session.get(Provider, provider_id)
            if not provider:
                raise ValueError("المنصة غير موجودة")
            if rule["type"] in {"provider_buyers", "provider_top_buyers", "expired_subscription"}:
                if int(rule["value"]) != int(provider_id):
                    raise PermissionError("لا يمكن استهداف بيانات منصة أخرى")
            if offer_id is not None:
                offer = await session.get(Offer, offer_id)
                if not offer or int(offer.provider_id) != int(provider_id):
                    raise PermissionError("العرض الإعلاني لا يخص المنصة")
            if rule["type"] == "favorite_offer":
                favorite_offer = await session.get(Offer, int(rule["value"]))
                if not favorite_offer or int(favorite_offer.provider_id) != int(provider_id):
                    raise PermissionError("لا يمكن استهداف مفضلات عرض تابع لمنصة أخرى")
        campaign = AdCampaign(
            public_id=public_id("AD"),
            idempotency_key=idempotency_key,
            provider_id=provider_id,
            requested_by_user_id=requested_by_user_id,
            campaign_type=campaign_type,
            title=title[:220],
            body=body,
            offer_id=offer_id,
            audience_rule_json=rule,
            duration_hours=duration_hours,
            hourly_rate_iqd=max(0, int(hourly_rate_iqd)),
            total_iqd=max(0, int(hourly_rate_iqd)) * duration_hours,
            status=CampaignStatus.AWAITING_PAYMENT.value if provider_id else CampaignStatus.UNDER_REVIEW.value,
        )
        session.add(campaign)
        await session.flush()
        await self.ensure_owner_inbox_item(
            session,
            kind=OwnerInboxKind.AD_REQUEST.value,
            source_type="ad_campaign",
            source_id=campaign.id,
            provider_id=provider_id,
            user_id=requested_by_user_id,
            summary=f"طلب إعلان: {campaign.title}",
            payload={"campaign_id": campaign.id, "type": campaign.campaign_type},
            priority=60,
        )
        return campaign

    async def submit_ad_proof(
        self,
        session: AsyncSession,
        *,
        campaign_id: int,
        provider_id: int,
        submitted_by_user_id: int,
        file_id: str,
        file_unique_id: str,
    ) -> AdCampaign:
        campaign = await session.scalar(
            select(AdCampaign).where(AdCampaign.id == campaign_id).with_for_update()
        )
        if not campaign:
            raise ValueError("الحملة غير موجودة")
        if campaign.provider_id != provider_id or campaign.requested_by_user_id != submitted_by_user_id:
            raise PermissionError("الحملة لا تخص هذه المنصة أو المستخدم")
        if campaign.status not in {CampaignStatus.AWAITING_PAYMENT.value, CampaignStatus.DRAFT.value}:
            raise ValueError("لا يمكن رفع إثبات لهذه الحملة حالياً")
        fingerprint = await self._claim_financial_proof(
            session, file_unique_id=file_unique_id, source_type="ad_campaign",
            source_id=campaign.id, submitted_by_user_id=submitted_by_user_id,
            provider_id=provider_id,
        )
        duplicate = await session.scalar(
            select(AdCampaign.id).where(
                AdCampaign.proof_fingerprint == fingerprint,
                AdCampaign.id != campaign.id,
            )
        )
        if duplicate:
            raise ValueError("تم استخدام هذا الإثبات في حملة أخرى")
        campaign.proof_file_id = file_id
        campaign.proof_fingerprint = fingerprint
        campaign.status = CampaignStatus.UNDER_REVIEW.value
        return campaign

    async def approve_ad_campaign(
        self,
        session: AsyncSession,
        *,
        campaign_id: int,
        admin_user_id: int,
        approved: bool,
        reason: str = "",
    ) -> AdCampaign:
        campaign = await session.scalar(
            select(AdCampaign).where(AdCampaign.id == campaign_id).with_for_update()
        )
        if not campaign:
            raise ValueError("الحملة غير موجودة")
        if campaign.status in {CampaignStatus.ACTIVE.value, CampaignStatus.REJECTED.value}:
            return campaign
        campaign.approved_by_user_id = admin_user_id
        if not approved:
            campaign.status = CampaignStatus.REJECTED.value
            campaign.rejection_reason = reason[:1000]
            await self.resolve_owner_inbox_source(
                session, source_type="ad_campaign", source_id=campaign.id, accepted=False
            )
            return campaign
        if campaign.provider_id is not None and not campaign.proof_file_id:
            raise ValueError("إثبات دفع الإعلان مطلوب")
        user_ids = await self.audience_user_ids(
            session, campaign.audience_rule_json, marketing_only=True
        )
        if not user_ids:
            raise ValueError("لا يوجد مستخدمون مؤهلون لهذه الحملة")
        for user_id in user_ids:
            exists = await session.scalar(
                select(AdCampaignRecipient.id).where(
                    AdCampaignRecipient.campaign_id == campaign.id,
                    AdCampaignRecipient.user_id == user_id,
                )
            )
            if not exists:
                session.add(AdCampaignRecipient(campaign_id=campaign.id, user_id=user_id))
        now = datetime.now(UTC)
        announcement = Announcement(
            title=campaign.title,
            body=campaign.body,
            button_text="🛒 مشاهدة العرض" if campaign.offer_id else None,
            button_url="action:offers" if campaign.offer_id else None,
            target_scope="campaign",
            target_value=str(campaign.id),
            starts_at=now,
            ends_at=now + timedelta(hours=campaign.duration_hours),
            pin_message=campaign.campaign_type == "pinned",
            status=AnnouncementStatus.ACTIVE.value,
            created_by_user_id=admin_user_id,
        )
        session.add(announcement)
        await session.flush()
        campaign.announcement_id = announcement.id
        campaign.starts_at = now
        campaign.ends_at = announcement.ends_at
        campaign.status = CampaignStatus.ACTIVE.value
        await self.resolve_owner_inbox_source(
            session, source_type="ad_campaign", source_id=campaign.id, accepted=True
        )
        await session.flush()
        return campaign

    async def dispatch_ad_campaign(
        self, session: AsyncSession, *, campaign_id: int, limit: int = 100
    ) -> tuple[int, int]:
        campaign = await session.get(AdCampaign, campaign_id)
        if not campaign or not campaign.announcement_id:
            raise ValueError("الحملة غير جاهزة للإرسال")
        announcement = await session.get(Announcement, campaign.announcement_id)
        if not announcement:
            raise ValueError("رسالة الإعلان غير موجودة")
        recipients = list(
            (
                await session.scalars(
                    select(AdCampaignRecipient).where(
                        AdCampaignRecipient.campaign_id == campaign.id,
                        AdCampaignRecipient.status == "pending",
                    ).order_by(AdCampaignRecipient.id).limit(max(1, min(int(limit), 500)))
                )
            ).all()
        )
        sent = failed = 0
        for recipient in recipients:
            user = await session.get(User, recipient.user_id)
            if not user:
                recipient.status = "failed"
                recipient.error = "user_not_found"
                failed += 1
                continue
            delivery = await self.announcements.send_one(session, announcement, user)
            if delivery.sent_at:
                recipient.status = "sent"
                recipient.message_id = delivery.message_id
                sent += 1
            else:
                recipient.status = "failed"
                recipient.error = delivery.error or "telegram_error"
                failed += 1
        await session.flush()
        return sent, failed

    async def process_ad_campaigns(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
        campaign_limit: int = 3,
        recipient_batch: int = 100,
    ) -> dict[str, int]:
        moment = now or datetime.now(UTC)
        expired = list(
            (
                await session.scalars(
                    select(AdCampaign)
                    .where(
                        AdCampaign.status == CampaignStatus.ACTIVE.value,
                        AdCampaign.ends_at.is_not(None),
                        AdCampaign.ends_at <= moment,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for campaign in expired:
            campaign.status = CampaignStatus.FINISHED.value
            if campaign.announcement_id:
                announcement = await session.get(Announcement, campaign.announcement_id)
                if announcement:
                    announcement.status = AnnouncementStatus.ENDED.value

        active = list(
            (
                await session.scalars(
                    select(AdCampaign)
                    .where(
                        AdCampaign.status == CampaignStatus.ACTIVE.value,
                        AdCampaign.starts_at <= moment,
                        AdCampaign.ends_at > moment,
                    )
                    .order_by(AdCampaign.id)
                    .limit(max(1, min(int(campaign_limit), 20)))
                )
            ).all()
        )
        sent = failed = 0
        for campaign in active:
            batch_sent, batch_failed = await self.dispatch_ad_campaign(
                session, campaign_id=campaign.id, limit=recipient_batch
            )
            sent += batch_sent
            failed += batch_failed
        await session.flush()
        return {"campaigns": len(active), "sent": sent, "failed": failed, "expired": len(expired)}

    async def create_coupon_campaign(
        self,
        session: AsyncSession,
        *,
        code: str,
        coupon_type: str,
        value_int: int,
        provider_id: int | None,
        created_by_user_id: int,
        audience_rule: dict[str, Any],
        max_uses: int | None = None,
        per_user_limit: int = 1,
    ) -> CouponCampaign:
        coupon = await self.order_coupons.create(
            session,
            code=code,
            coupon_type=coupon_type,
            value_int=value_int,
            provider_id=provider_id,
            created_by_user_id=created_by_user_id,
            max_uses=max_uses,
            per_user_limit=per_user_limit,
        )
        rule = normalize_audience_rule(audience_rule)
        if provider_id is not None:
            if rule["type"] in {"provider_buyers", "provider_top_buyers", "expired_subscription"}:
                if int(rule["value"]) != int(provider_id):
                    raise PermissionError("لا يمكن استهداف طلاب منصة أخرى")
            if rule["type"] == "favorite_offer":
                favorite_offer = await session.get(Offer, int(rule["value"]))
                if not favorite_offer or int(favorite_offer.provider_id) != int(provider_id):
                    raise PermissionError("العرض لا يخص المنصة")
        campaign = CouponCampaign(
            coupon_id=coupon.id,
            provider_id=provider_id,
            created_by_user_id=created_by_user_id,
            audience_rule_json=rule,
        )
        session.add(campaign)
        await session.flush()
        user_ids = await self.audience_user_ids(session, rule, marketing_only=False)
        if not user_ids:
            raise ValueError("لا يوجد طلاب يطابقون شريحة الحملة")
        for user_id in user_ids:
            session.add(
                CouponAssignment(
                    campaign_id=campaign.id,
                    coupon_id=coupon.id,
                    user_id=user_id,
                )
            )
        campaign.assigned_count = len(user_ids)
        if max_uses is None or max_uses > len(user_ids):
            coupon.max_uses = len(user_ids)
        await session.flush()
        return campaign

    async def create_hybrid_bundle(
        self,
        session: AsyncSession,
        *,
        title: str,
        description: str,
        price_iqd: int,
        bot_fee_iqd: int,
        components: list[HybridAllocation],
        created_by_user_id: int,
    ) -> HybridBundle:
        validate_hybrid_allocations(
            bundle_price_iqd=price_iqd,
            bot_fee_iqd=bot_fee_iqd,
            allocations=components,
        )
        for component in components:
            offer = await session.get(Offer, component.offer_id)
            if not offer or offer.provider_id != component.provider_id:
                raise ValueError("أحد مكونات الباقة لا يطابق المنصة المحددة")
        bundle = HybridBundle(
            public_id=public_id("HB"),
            title=title[:220],
            description=description,
            price_iqd=int(price_iqd),
            bot_fee_iqd=int(bot_fee_iqd),
            status=HybridBundleStatus.DRAFT.value,
            created_by_user_id=created_by_user_id,
        )
        session.add(bundle)
        await session.flush()
        for index, component in enumerate(components):
            session.add(
                HybridBundleComponent(
                    bundle_id=bundle.id,
                    provider_id=component.provider_id,
                    offer_id=component.offer_id,
                    provider_share_iqd=component.amount_iqd,
                    sort_order=index,
                )
            )
        await session.flush()
        return bundle

    async def activate_hybrid_bundle(self, session: AsyncSession, bundle_id: int) -> HybridBundle:
        bundle = await session.scalar(
            select(HybridBundle).where(HybridBundle.id == bundle_id).with_for_update()
        )
        if not bundle:
            raise ValueError("الباقة غير موجودة")
        components = list(
            (
                await session.scalars(
                    select(HybridBundleComponent).where(
                        HybridBundleComponent.bundle_id == bundle.id
                    )
                )
            ).all()
        )
        validate_hybrid_allocations(
            bundle_price_iqd=bundle.price_iqd,
            bot_fee_iqd=bundle.bot_fee_iqd,
            allocations=[
                HybridAllocation(
                    provider_id=item.provider_id,
                    offer_id=item.offer_id,
                    amount_iqd=item.provider_share_iqd,
                )
                for item in components
            ],
        )
        bundle.status = HybridBundleStatus.ACTIVE.value
        return bundle

    async def create_hybrid_purchase(
        self,
        session: AsyncSession,
        *,
        bundle_id: int,
        user_id: int,
        idempotency_key: str,
    ) -> HybridBundlePurchase:
        existing = await session.scalar(
            select(HybridBundlePurchase).where(
                HybridBundlePurchase.idempotency_key == idempotency_key
            )
        )
        if existing:
            return existing
        now = datetime.now(UTC)
        bundle = await session.scalar(
            select(HybridBundle).where(HybridBundle.id == bundle_id).with_for_update()
        )
        if not bundle or bundle.status != HybridBundleStatus.ACTIVE.value:
            raise ValueError("الباقة غير متاحة")
        components = list((await session.scalars(
            select(HybridBundleComponent)
            .where(HybridBundleComponent.bundle_id == bundle.id)
            .order_by(HybridBundleComponent.sort_order, HybridBundleComponent.id)
        )).all())
        if not components:
            raise ValueError("الباقة لا تحتوي خدمات")
        purchase = HybridBundlePurchase(
            public_id=public_id("HP"),
            idempotency_key=idempotency_key,
            bundle_id=bundle.id,
            user_id=user_id,
            total_iqd=bundle.price_iqd,
            bot_fee_iqd=bundle.bot_fee_iqd,
            expires_at=now + timedelta(hours=24),
        )
        session.add(purchase)
        await session.flush()
        for component in components:
            offer = await session.get(Offer, component.offer_id)
            if (
                not offer
                or offer.provider_id != component.provider_id
                or offer.status != OfferStatus.ACTIVE.value
            ):
                raise ValueError("أحد عروض الباقة غير متاح حالياً")
            if offer.delivery_type not in {
                DeliveryType.INVENTORY_CODE.value,
                DeliveryType.INVENTORY_ACCOUNT.value,
            }:
                continue
            item = await session.scalar(
                select(InventoryItem)
                .where(
                    InventoryItem.offer_id == offer.id,
                    InventoryItem.status == InventoryStatus.AVAILABLE.value,
                    or_(InventoryItem.expires_at.is_(None), InventoryItem.expires_at > now),
                )
                .order_by(InventoryItem.expires_at.asc().nullslast(), InventoryItem.id.asc())
                .with_for_update(skip_locked=True)
            )
            if not item:
                raise ValueError(f"نفد مخزون أحد مكونات الباقة: {offer.title}")
            item.status = InventoryStatus.RESERVED.value
            item.reserved_at = now
            item.reserved_order_id = None
            session.add(HybridInventoryHold(
                purchase_id=purchase.id,
                component_id=component.id,
                inventory_item_id=item.id,
                status="held",
                expires_at=purchase.expires_at,
            ))
        await session.flush()
        return purchase

    async def submit_hybrid_purchase_proof(
        self,
        session: AsyncSession,
        *,
        purchase_id: int,
        user_id: int,
        file_id: str,
        file_type: str,
        file_unique_id: str,
        claimed_amount_iqd: int,
    ) -> HybridPurchaseProof:
        purchase = await session.scalar(
            select(HybridBundlePurchase)
            .where(HybridBundlePurchase.id == purchase_id)
            .with_for_update()
        )
        if not purchase or purchase.user_id != user_id:
            raise ValueError("عملية الشراء لا تخص هذا الطالب")
        if purchase.status != HybridPurchaseStatus.PENDING.value:
            raise ValueError("لا يمكن رفع إثبات لهذه العملية حالياً")
        if purchase.expires_at <= datetime.now(UTC):
            await self._release_hybrid_holds(session, purchase.id)
            purchase.status = HybridPurchaseStatus.FAILED.value
            raise ValueError("انتهت مهلة حجز مكونات الباقة؛ أعد إنشاء الطلب")
        if int(claimed_amount_iqd) < int(purchase.total_iqd):
            raise ValueError("المبلغ المذكور أقل من قيمة الباقة")
        fingerprint = await self._claim_financial_proof(
            session, file_unique_id=file_unique_id, source_type="hybrid_purchase",
            source_id=purchase.id, submitted_by_user_id=user_id, provider_id=None,
        )
        existing = await session.scalar(
            select(HybridPurchaseProof).where(
                HybridPurchaseProof.file_fingerprint == fingerprint
            )
        )
        if existing:
            return existing
        proof = HybridPurchaseProof(
            purchase_id=purchase.id,
            user_id=user_id,
            file_id=file_id,
            file_type=file_type,
            file_fingerprint=fingerprint,
            claimed_amount_iqd=int(claimed_amount_iqd),
        )
        session.add(proof)
        await session.flush()
        await self.ensure_owner_inbox_item(
            session, kind=OwnerInboxKind.BILLING_PROOF.value,
            source_type="hybrid_purchase_proof", source_id=proof.id,
            user_id=user_id, summary=f"دفع باقة هجينة {purchase.public_id}",
            payload={"purchase_id": purchase.id, "proof_id": proof.id}, priority=20,
        )
        return proof

    async def review_hybrid_purchase_proof(
        self,
        session: AsyncSession,
        *,
        proof_id: int,
        admin_user_id: int,
        approved: bool,
        reason: str = "",
    ) -> HybridPurchaseProof:
        proof = await session.scalar(
            select(HybridPurchaseProof)
            .where(HybridPurchaseProof.id == proof_id)
            .with_for_update()
        )
        if not proof:
            raise ValueError("إثبات الباقة غير موجود")
        if proof.status in {"approved", "rejected"}:
            return proof
        purchase = await session.scalar(
            select(HybridBundlePurchase)
            .where(HybridBundlePurchase.id == proof.purchase_id)
            .with_for_update()
        )
        if not purchase:
            raise ValueError("عملية شراء الباقة غير موجودة")
        proof.reviewed_by_user_id = admin_user_id
        proof.reviewed_at = datetime.now(UTC)
        if approved:
            if proof.claimed_amount_iqd < purchase.total_iqd:
                raise ValueError("المبلغ أقل من قيمة الباقة")
            proof.status = "approved"
            await self.allocate_hybrid_purchase(session, purchase_id=purchase.id)
        else:
            proof.status = "rejected"
            proof.rejection_reason = reason[:1000]
            purchase.status = HybridPurchaseStatus.FAILED.value
            await self._release_hybrid_holds(session, purchase.id)
        await self.resolve_owner_inbox_source(
            session, source_type="hybrid_purchase_proof", source_id=proof.id, accepted=approved
        )
        await session.flush()
        return proof

    async def allocate_hybrid_purchase(
        self,
        session: AsyncSession,
        *,
        purchase_id: int,
    ) -> HybridBundlePurchase:
        purchase = await session.scalar(
            select(HybridBundlePurchase)
            .where(HybridBundlePurchase.id == purchase_id)
            .with_for_update()
        )
        if not purchase:
            raise ValueError("عملية الشراء غير موجودة")
        if purchase.status in {
            HybridPurchaseStatus.ALLOCATED.value,
            HybridPurchaseStatus.FULFILLING.value,
            HybridPurchaseStatus.COMPLETED.value,
        }:
            return purchase
        bundle = await session.get(HybridBundle, purchase.bundle_id)
        if not bundle:
            raise ValueError("الباقة غير موجودة")
        components = list(
            (
                await session.scalars(
                    select(HybridBundleComponent).where(
                        HybridBundleComponent.bundle_id == bundle.id
                    )
                )
            ).all()
        )
        validate_hybrid_allocations(
            bundle_price_iqd=bundle.price_iqd,
            bot_fee_iqd=bundle.bot_fee_iqd,
            allocations=[
                HybridAllocation(
                    provider_id=item.provider_id,
                    offer_id=item.offer_id,
                    amount_iqd=item.provider_share_iqd,
                )
                for item in components
            ],
        )
        now = datetime.now(UTC)
        if purchase.expires_at <= now:
            await self._release_hybrid_holds(session, purchase.id)
            purchase.status = HybridPurchaseStatus.FAILED.value
            raise ValueError("انتهت مهلة حجز مكونات الباقة")
        holds = {
            hold.component_id: hold
            for hold in (await session.scalars(
                select(HybridInventoryHold)
                .where(HybridInventoryHold.purchase_id == purchase.id)
                .with_for_update()
            )).all()
        }
        purchase.status = HybridPurchaseStatus.PAID.value
        purchase.paid_at = now
        for component in components:
            key = f"hybrid:{purchase.id}:component:{component.id}"
            allocation = await session.scalar(
                select(HybridRevenueAllocation).where(
                    HybridRevenueAllocation.idempotency_key == key
                )
            )
            if not allocation:
                child_order = Order(
                    public_id=public_id("ORD"),
                    idempotency_key=f"hybrid-order:{purchase.id}:component:{component.id}",
                    user_id=purchase.user_id,
                    provider_id=component.provider_id,
                    offer_id=component.offer_id,
                    status=OrderStatus.WAITING_FULFILLMENT.value,
                    activation_data={
                        "source": "hybrid_bundle",
                        "hybrid_purchase_id": purchase.id,
                        "hybrid_component_id": component.id,
                    },
                    payment_snapshot={
                        "source": "hybrid_bundle",
                        "bundle_id": bundle.id,
                        "bundle_public_id": bundle.public_id,
                    },
                    subtotal_iqd=component.provider_share_iqd,
                    service_fee_iqd=0,
                    total_iqd=component.provider_share_iqd,
                    management_fee_iqd=0,
                    provider_net_iqd=component.provider_share_iqd,
                    owner_net_iqd=0,
                )
                session.add(child_order)
                await session.flush()
                offer = await session.get(Offer, component.offer_id)
                if offer and offer.delivery_type in {
                    DeliveryType.INVENTORY_CODE.value,
                    DeliveryType.INVENTORY_ACCOUNT.value,
                }:
                    hold = holds.get(component.id)
                    if not hold or hold.status != "held" or hold.expires_at <= now:
                        raise ValueError("فُقد حجز أحد مكونات الباقة قبل التوزيع")
                    item = await session.scalar(
                        select(InventoryItem)
                        .where(InventoryItem.id == hold.inventory_item_id)
                        .with_for_update()
                    )
                    if not item or item.status != InventoryStatus.RESERVED.value:
                        raise ValueError("مخزون أحد مكونات الباقة لم يعد محجوزاً")
                    item.reserved_order_id = child_order.id
                    session.add(PurchaseReservation(
                        order_id=child_order.id,
                        offer_id=component.offer_id,
                        inventory_item_id=item.id,
                        status=ReservationStatus.CONFIRMED.value,
                        held_at=hold.created_at,
                        expires_at=now + timedelta(hours=24),
                        confirmed_at=now,
                    ))
                    session.add(DeliveryJob(
                        order_id=child_order.id,
                        inventory_item_id=item.id,
                        job_type="hybrid_bundle_delivery",
                        idempotency_key=f"hybrid:{purchase.id}:component:{component.id}:delivery",
                        status=DeliveryJobStatus.PENDING.value,
                    ))
                    hold.status = "consumed"
                    hold.consumed_order_id = child_order.id
                allocation = HybridRevenueAllocation(
                    purchase_id=purchase.id,
                    component_id=component.id,
                    provider_id=component.provider_id,
                    order_id=child_order.id,
                    amount_iqd=component.provider_share_iqd,
                    idempotency_key=key,
                )
                session.add(allocation)
                await session.flush()
                await self.wallets.post(
                    session,
                    owner_type=WalletOwnerType.PROVIDER.value,
                    owner_id=component.provider_id,
                    amount_iqd=component.provider_share_iqd,
                    direction="credit",
                    entry_type=WalletEntryType.COMMISSION.value,
                    idempotency_key=key,
                    provider_id=component.provider_id,
                    description=f"حصة منصة من الباقة الهجينة {purchase.public_id}",
                    metadata={"hybrid_purchase_id": purchase.id, "component_id": component.id},
                )
                allocation.posted_at = datetime.now(UTC)

        ledger_entries = [
            {
                "account_code": "hybrid_bundle_cash",
                "direction": "debit",
                "amount_iqd": bundle.price_iqd,
            }
        ]
        ledger_entries.extend(
            {
                "account_code": "provider_payable",
                "direction": "credit",
                "amount_iqd": component.provider_share_iqd,
                "provider_id": component.provider_id,
            }
            for component in components
        )
        if bundle.bot_fee_iqd:
            ledger_entries.append(
                {
                    "account_code": "bot_fee_revenue",
                    "direction": "credit",
                    "amount_iqd": bundle.bot_fee_iqd,
                }
            )
        await self.enterprise.post_balanced_transaction(
            session,
            idempotency_key=f"hybrid-ledger:{purchase.id}",
            reference_type="hybrid_bundle_purchase",
            reference_id=str(purchase.id),
            description=f"توزيع الباقة الهجينة {purchase.public_id}",
            entries=ledger_entries,
        )
        purchase.status = HybridPurchaseStatus.FULFILLING.value
        await session.flush()
        return purchase

    async def _release_hybrid_holds(
        self, session: AsyncSession, purchase_id: int
    ) -> int:
        now = datetime.now(UTC)
        holds = list((await session.scalars(
            select(HybridInventoryHold)
            .where(
                HybridInventoryHold.purchase_id == purchase_id,
                HybridInventoryHold.status == "held",
            )
            .with_for_update(skip_locked=True)
        )).all())
        released = 0
        for hold in holds:
            item = await session.scalar(
                select(InventoryItem)
                .where(InventoryItem.id == hold.inventory_item_id)
                .with_for_update()
            )
            if item and item.status == InventoryStatus.RESERVED.value and item.reserved_order_id is None:
                item.status = InventoryStatus.AVAILABLE.value
                item.reserved_at = None
            hold.status = "released"
            hold.released_at = now
            released += 1
        return released

    async def expire_hybrid_purchases(
        self, session: AsyncSession, *, now: datetime | None = None, limit: int = 100
    ) -> int:
        current = now or datetime.now(UTC)
        purchases = list((await session.scalars(
            select(HybridBundlePurchase)
            .where(
                HybridBundlePurchase.status == HybridPurchaseStatus.PENDING.value,
                HybridBundlePurchase.expires_at <= current,
            )
            .order_by(HybridBundlePurchase.expires_at, HybridBundlePurchase.id)
            .limit(max(1, min(int(limit), 500)))
            .with_for_update(skip_locked=True)
        )).all())
        for purchase in purchases:
            await self._release_hybrid_holds(session, purchase.id)
            purchase.status = HybridPurchaseStatus.FAILED.value
        return len(purchases)

    async def create_reward_campaign(
        self,
        session: AsyncSession,
        *,
        provider_id: int,
        requested_by_user_id: int,
        title: str,
        channel_chat_id: int,
        channel_url: str,
        reward_iqd: int,
        requested_count: int,
        budget_iqd: int,
        idempotency_key: str,
    ) -> RewardTaskCampaign:
        existing = await session.scalar(
            select(RewardTaskCampaign).where(
                RewardTaskCampaign.idempotency_key == idempotency_key
            )
        )
        if existing:
            return existing
        provider = await session.get(Provider, provider_id)
        if not provider:
            raise ValueError("المنصة غير موجودة")
        capacity = reward_campaign_capacity(
            budget_iqd=budget_iqd,
            reward_iqd=reward_iqd,
            requested_count=requested_count,
        )
        campaign = RewardTaskCampaign(
            public_id=public_id("RT"),
            idempotency_key=idempotency_key,
            provider_id=provider_id,
            requested_by_user_id=requested_by_user_id,
            title=title[:220],
            channel_chat_id=channel_chat_id,
            channel_url=channel_url,
            reward_iqd=reward_iqd,
            requested_count=requested_count,
            capacity_count=capacity,
            budget_iqd=budget_iqd,
            status=RewardTaskStatus.DRAFT.value,
        )
        session.add(campaign)
        await session.flush()
        await self.ensure_owner_inbox_item(
            session,
            kind=OwnerInboxKind.AD_REQUEST.value,
            source_type="reward_task_campaign",
            source_id=campaign.id,
            provider_id=provider_id,
            user_id=requested_by_user_id,
            summary=f"إعلان مهام: {campaign.title}",
            payload={"campaign_id": campaign.id, "budget_iqd": campaign.budget_iqd},
            priority=50,
        )
        return campaign

    async def submit_reward_campaign_proof(
        self, session: AsyncSession, *, campaign_id: int, provider_id: int,
        file_id: str, file_unique_id: str
    ) -> RewardTaskCampaign:
        campaign = await session.scalar(
            select(RewardTaskCampaign)
            .where(RewardTaskCampaign.id == campaign_id)
            .with_for_update()
        )
        if not campaign or campaign.provider_id != provider_id:
            raise ValueError("الحملة لا تخص هذه المنصة")
        fingerprint = await self._claim_financial_proof(
            session, file_unique_id=file_unique_id, source_type="reward_campaign",
            source_id=campaign.id, submitted_by_user_id=campaign.requested_by_user_id,
            provider_id=provider_id,
        )
        duplicate = await session.scalar(
            select(RewardTaskCampaign.id).where(
                RewardTaskCampaign.proof_fingerprint == fingerprint,
                RewardTaskCampaign.id != campaign.id,
            )
        )
        if duplicate:
            raise ValueError("تم استخدام هذا الإثبات في حملة أخرى")
        campaign.proof_file_id = file_id
        campaign.proof_fingerprint = fingerprint
        campaign.status = RewardTaskStatus.UNDER_REVIEW.value
        return campaign

    async def approve_reward_campaign(
        self,
        session: AsyncSession,
        *,
        campaign_id: int,
        admin_user_id: int,
        approved: bool,
        reason: str = "",
    ) -> RewardTaskCampaign:
        campaign = await session.scalar(
            select(RewardTaskCampaign)
            .where(RewardTaskCampaign.id == campaign_id)
            .with_for_update()
        )
        if not campaign:
            raise ValueError("حملة المهام غير موجودة")
        campaign.approved_by_user_id = admin_user_id
        if approved:
            if not campaign.proof_file_id:
                raise ValueError("إثبات تمويل حملة المهام مطلوب")
            campaign.status = RewardTaskStatus.ACTIVE.value
        else:
            campaign.status = RewardTaskStatus.REJECTED.value
            campaign.rejection_reason = reason[:1000]
        await self.resolve_owner_inbox_source(
            session,
            source_type="reward_task_campaign",
            source_id=campaign.id,
            accepted=approved,
        )
        return campaign

    async def reward_verified_student(
        self,
        session: AsyncSession,
        *,
        campaign_id: int,
        user_id: int,
        verified: bool,
    ) -> RewardTaskCompletion:
        if not verified:
            raise ValueError("تعذر التحقق من تنفيذ المهمة")
        campaign = await session.scalar(
            select(RewardTaskCampaign)
            .where(RewardTaskCampaign.id == campaign_id)
            .with_for_update()
        )
        if not campaign or campaign.status != RewardTaskStatus.ACTIVE.value:
            raise ValueError("الحملة غير فعالة")
        existing = await session.scalar(
            select(RewardTaskCompletion).where(
                RewardTaskCompletion.campaign_id == campaign.id,
                RewardTaskCompletion.user_id == user_id,
            )
        )
        if existing:
            return existing
        if campaign.completed_count >= campaign.capacity_count:
            campaign.status = RewardTaskStatus.COMPLETED.value
            raise ValueError("اكتمل العدد المطلوب")
        if campaign.spent_iqd + campaign.reward_iqd > campaign.budget_iqd:
            campaign.status = RewardTaskStatus.COMPLETED.value
            raise ValueError("انتهت ميزانية الحملة")
        key = f"reward-task:{campaign.id}:user:{user_id}"
        completion = RewardTaskCompletion(
            campaign_id=campaign.id,
            user_id=user_id,
            idempotency_key=key,
            status="verified",
            verified_at=datetime.now(UTC),
        )
        session.add(completion)
        await session.flush()
        entry = await self.wallets.post(
            session,
            owner_type=WalletOwnerType.USER.value,
            owner_id=user_id,
            amount_iqd=campaign.reward_iqd,
            direction="credit",
            entry_type=WalletEntryType.ADJUSTMENT.value,
            idempotency_key=key,
            provider_id=campaign.provider_id,
            description=f"مكافأة تنفيذ مهمة: {campaign.title}",
            metadata={"reward_campaign_id": campaign.id},
        )
        completion.wallet_entry_id = entry.id
        campaign.completed_count += 1
        campaign.spent_iqd += campaign.reward_iqd
        if campaign.completed_count >= campaign.capacity_count:
            campaign.status = RewardTaskStatus.COMPLETED.value
        await session.flush()
        return completion
