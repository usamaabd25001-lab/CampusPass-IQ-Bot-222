from __future__ import annotations

from dataclasses import dataclass
import hashlib
import unicodedata
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.student_commerce import net_wallet_fee_deduction
from app.db.models import (
    Order,
    OrderStatus,
    Payment,
    PaymentAmountConfirmation,
    PaymentProof,
    PaymentProofStatus,
    PaymentReferenceClaim,
    PaymentStatus,
    PaymentWebhookEvent,
    ProviderStaff,
    User,
)
from app.integrations.payments.mastercard import CheckoutSession, GatewayNotification
from app.services.orders import OrderService
from app.services.platform_access import resolve_provider_access
from app.services.wallets import WalletService
from app.services.friend_packages import FriendPackageService


@dataclass(slots=True)
class GatewayPaymentResult:
    event: PaymentWebhookEvent
    order: Order | None
    payment: Payment | None
    accepted: bool
    duplicate: bool = False
    requires_review: bool = False
    message: str = ""


class PaymentService:
    def __init__(
        self,
        settings: Settings,
        orders: OrderService,
        wallets: WalletService,
        friend_packages: FriendPackageService | None = None,
    ) -> None:
        self.settings = settings
        self.orders = orders
        self.wallets = wallets
        self.friend_packages = friend_packages

    @staticmethod
    def normalize_reference(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).strip().upper()
        return "".join(char for char in normalized if char.isalnum())[:120]

    async def _claim_reference(
        self, session: AsyncSession, order: Order, reference: str
    ) -> tuple[str, str]:
        normalized = self.normalize_reference(reference)
        if len(normalized) < 4:
            raise ValueError("رقم العملية قصير أو غير صالح")
        fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        claim = await session.scalar(
            select(PaymentReferenceClaim).where(
                PaymentReferenceClaim.fingerprint == fingerprint
            )
        )
        if not claim:
            try:
                async with session.begin_nested():
                    claim = PaymentReferenceClaim(
                        fingerprint=fingerprint,
                        order_id=order.id,
                        normalized_reference=normalized,
                    )
                    session.add(claim)
                    await session.flush()
            except IntegrityError:
                claim = await session.scalar(
                    select(PaymentReferenceClaim).where(
                        PaymentReferenceClaim.fingerprint == fingerprint
                    )
                )
        if not claim or claim.order_id != order.id:
            raise ValueError(
                "رقم العملية مستخدم في طلب آخر. تحقق من الرقم أو تواصل مع الدعم"
            )
        return normalized, fingerprint

    async def register_checkout(
        self,
        session: AsyncSession,
        order: Order,
        checkout: CheckoutSession,
    ) -> Payment:
        existing = await session.scalar(
            select(Payment).where(Payment.gateway_reference == checkout.reference)
        )
        if existing:
            if existing.order_id != order.id:
                raise ValueError("مرجع بوابة الدفع مرتبط بطلب آخر")
            return existing
        payment = Payment(
            order_id=order.id,
            payment_method_id=order.payment_method_id,
            gateway_reference=checkout.reference,
            amount_iqd=int(order.total_iqd),
            status=PaymentStatus.PENDING.value,
            raw_payload={"checkout": checkout.raw},
        )
        session.add(payment)
        await session.flush()
        return payment

    async def process_gateway_notification(
        self,
        session: AsyncSession,
        notification: GatewayNotification,
    ) -> GatewayPaymentResult:
        event = await session.scalar(
            select(PaymentWebhookEvent).where(
                PaymentWebhookEvent.event_key == notification.event_key
            )
        )
        if event and event.processing_status not in {"received", "processing"}:
            order = (
                await self.orders.get_by_public_id(session, event.order_public_id)
                if event.order_public_id
                else None
            )
            payment = await session.scalar(
                select(Payment).where(Payment.gateway_reference == event.gateway_reference)
            )
            return GatewayPaymentResult(
                event=event,
                order=order,
                payment=payment,
                accepted=event.processing_status in {"confirmed", "failed", "ignored"},
                duplicate=True,
                requires_review=event.processing_status == "review_required",
                message="Webhook processed previously",
            )

        if not event:
            event = PaymentWebhookEvent(
                event_key=notification.event_key,
                gateway_reference=notification.reference,
                order_public_id=notification.order_public_id,
                gateway_status=notification.status,
                processing_status="received",
                raw_payload=notification.raw,
            )
            try:
                async with session.begin_nested():
                    session.add(event)
                    await session.flush()
            except IntegrityError:
                event = await session.scalar(
                    select(PaymentWebhookEvent).where(
                        PaymentWebhookEvent.event_key == notification.event_key
                    )
                )
                if not event:
                    raise
                order = (
                    await self.orders.get_by_public_id(session, event.order_public_id)
                    if event.order_public_id
                    else None
                )
                payment = await session.scalar(
                    select(Payment).where(Payment.gateway_reference == event.gateway_reference)
                )
                return GatewayPaymentResult(
                    event=event,
                    order=order,
                    payment=payment,
                    accepted=event.processing_status in {"confirmed", "failed", "ignored"},
                    duplicate=True,
                    requires_review=event.processing_status == "review_required",
                    message="Concurrent duplicate webhook",
                )

        event.processing_status = "processing"
        event.gateway_reference = notification.reference
        event.order_public_id = notification.order_public_id
        event.gateway_status = notification.status
        event.raw_payload = notification.raw
        event.last_error = None

        order = await session.scalar(
            select(Order).where(Order.public_id == notification.order_public_id).with_for_update()
        )
        payment = await session.scalar(
            select(Payment)
            .where(Payment.gateway_reference == notification.reference)
            .with_for_update()
        )
        if not order and payment:
            order = await session.scalar(
                select(Order).where(Order.id == payment.order_id).with_for_update()
            )
        if not order:
            return await self._reject_event(
                session, event, "لا يوجد طلب يطابق رقم الطلب القادم من بوابة الدفع"
            )
        if payment and payment.order_id != order.id:
            return await self._reject_event(
                session, event, "مرجع الدفع مستخدم لطلب مختلف", order=order, payment=payment
            )
        if notification.currency != "IQD":
            return await self._reject_event(
                session,
                event,
                f"عملة غير مدعومة: {notification.currency}",
                order=order,
                payment=payment,
            )
        if notification.amount_iqd != order.total_iqd:
            return await self._reject_event(
                session,
                event,
                f"مبلغ البوابة {notification.amount_iqd} لا يطابق الطلب {order.total_iqd}",
                order=order,
                payment=payment,
            )

        if not payment:
            payment = Payment(
                order_id=order.id,
                payment_method_id=order.payment_method_id,
                gateway_reference=notification.reference,
                amount_iqd=notification.amount_iqd,
                status=PaymentStatus.PENDING.value,
                raw_payload={},
            )
            session.add(payment)

        raw_payload = dict(payment.raw_payload or {})
        raw_payload["webhook"] = notification.raw
        payment.raw_payload = raw_payload

        if notification.failed:
            if payment.status != PaymentStatus.CONFIRMED.value:
                payment.status = PaymentStatus.FAILED.value
            event.processing_status = "failed"
            event.processed_at = datetime.now(UTC)
            await session.flush()
            return GatewayPaymentResult(
                event=event,
                order=order,
                payment=payment,
                accepted=True,
                message="Gateway reported a failed payment",
            )

        if not notification.successful:
            event.processing_status = "ignored"
            event.processed_at = datetime.now(UTC)
            await session.flush()
            return GatewayPaymentResult(
                event=event,
                order=order,
                payment=payment,
                accepted=True,
                message="Gateway status is not final",
            )

        payment.status = PaymentStatus.CONFIRMED.value
        payment.confirmed_at = payment.confirmed_at or datetime.now(UTC)

        if order.status in {
            OrderStatus.CANCELLED.value,
            OrderStatus.REFUNDED.value,
            OrderStatus.COMPLETED.value,
        }:
            event.processing_status = "review_required"
            event.last_error = f"تم استلام دفع بعد وصول الطلب إلى الحالة {order.status}"
            event.processed_at = datetime.now(UTC)
            await session.flush()
            return GatewayPaymentResult(
                event=event,
                order=order,
                payment=payment,
                accepted=False,
                requires_review=True,
                message=event.last_error,
            )

        if order.status != OrderStatus.PAID.value:
            await self.orders.change_status(
                session,
                order,
                OrderStatus.PAID.value,
                note="تم تأكيد الدفع تلقائيًا عبر بوابة البطاقة",
                metadata={
                    "gateway_reference": notification.reference,
                    "webhook_event": notification.event_key,
                },
            )
        if self.friend_packages is not None:
            await self.friend_packages.mark_order_paid(
                session, order=order, confirmed_amount_iqd=notification.amount_iqd
            )
        event.processing_status = "confirmed"
        event.processed_at = datetime.now(UTC)
        await session.flush()
        return GatewayPaymentResult(
            event=event,
            order=order,
            payment=payment,
            accepted=True,
            message="Payment confirmed",
        )

    async def _reject_event(
        self,
        session: AsyncSession,
        event: PaymentWebhookEvent,
        message: str,
        *,
        order: Order | None = None,
        payment: Payment | None = None,
    ) -> GatewayPaymentResult:
        event.processing_status = "rejected"
        event.last_error = message[:2000]
        event.processed_at = datetime.now(UTC)
        await session.flush()
        return GatewayPaymentResult(
            event=event,
            order=order,
            payment=payment,
            accepted=False,
            requires_review=True,
            message=message,
        )

    async def submit_proof(
        self,
        session: AsyncSession,
        order: Order,
        photo_file_id: str | None,
        document_file_id: str | None,
        sender_phone: str,
        claimed_amount_iqd: int,
        reference: str | None,
        note: str = "",
        evidence_asset_id: int | None = None,
        file_fingerprint: str | None = None,
    ) -> PaymentProof:
        locked = await session.scalar(
            select(Order).where(Order.id == order.id).with_for_update()
        )
        if not locked:
            raise ValueError("الطلب غير موجود")
        order = locked
        if order.status not in {
            OrderStatus.WAITING_PAYMENT.value,
            OrderStatus.PAYMENT_REJECTED.value,
        }:
            raise ValueError("لا يمكن رفع إثبات لهذا الطلب")
        if claimed_amount_iqd <= 0:
            raise ValueError("المبلغ المصرح يجب أن يكون أكبر من صفر")
        existing_for_order = await session.scalar(
            select(PaymentProof.id).where(
                PaymentProof.order_id == order.id,
                PaymentProof.status == PaymentProofStatus.PENDING.value,
            )
        )
        if existing_for_order:
            raise ValueError("يوجد وصل قيد المراجعة لهذا الطلب بالفعل")
        open_reviews = int(
            await session.scalar(
                select(func.count())
                .select_from(PaymentProof)
                .join(Order, Order.id == PaymentProof.order_id)
                .where(
                    Order.user_id == order.user_id,
                    PaymentProof.status == PaymentProofStatus.PENDING.value,
                )
            )
            or 0
        )
        if (
            not existing_for_order
            and open_reviews >= self.settings.max_open_payment_reviews_per_user
        ):
            raise ValueError(
                "لديك عدة إثباتات قيد المراجعة. انتظر نتيجة المراجعة قبل رفع إثبات جديد"
            )

        normalized_file_fingerprint = (file_fingerprint or "").strip().lower()[:64] or None
        if normalized_file_fingerprint:
            duplicate_file = await session.scalar(
                select(PaymentProof.id).where(
                    PaymentProof.file_fingerprint == normalized_file_fingerprint,
                    PaymentProof.order_id != order.id,
                    PaymentProof.status.in_((
                        PaymentProofStatus.PENDING.value,
                        PaymentProofStatus.CONFIRMED.value,
                    )),
                )
            )
            if duplicate_file:
                raise ValueError("صورة الوصل مستخدمة في طلب آخر")

        normalized_reference = None
        reference_fingerprint = None
        if reference and reference.strip():
            normalized_reference, reference_fingerprint = await self._claim_reference(
                session, order, reference
            )
            duplicate_payment = await session.scalar(
                select(Payment.id).where(
                    Payment.gateway_reference == normalized_reference
                )
            )
            if duplicate_payment:
                raise ValueError("رقم العملية مرتبط بدفع إلكتروني مسجل سابقًا")

        proof = PaymentProof(
            order_id=order.id,
            photo_file_id=photo_file_id,
            document_file_id=document_file_id,
            sender_phone=sender_phone,
            claimed_amount_iqd=claimed_amount_iqd,
            reference=normalized_reference,
            reference_fingerprint=reference_fingerprint,
            file_fingerprint=normalized_file_fingerprint,
            note=note,
            evidence_asset_id=evidence_asset_id,
        )
        session.add(proof)
        await session.flush()
        session.add(
            PaymentAmountConfirmation(
                payment_proof_id=proof.id,
                order_id=order.id,
                claimed_amount_iqd=int(claimed_amount_iqd),
                status="pending",
            )
        )
        await self.orders.extend_reservation_for_review(
            session, order, hours=self.settings.payment_review_reservation_hours
        )
        await self.orders.change_status(
            session,
            order,
            OrderStatus.PAYMENT_REVIEW.value,
            actor_user_id=order.user_id,
            note="تم رفع إثبات دفع وينتظر المراجعة",
        )
        await session.flush()
        return proof

    async def latest_proof(self, session: AsyncSession, order_id: int) -> PaymentProof | None:
        return await session.scalar(
            select(PaymentProof)
            .where(PaymentProof.order_id == order_id)
            .order_by(PaymentProof.created_at.desc())
            .limit(1)
        )

    async def can_review(
        self, session: AsyncSession, actor: User, order: Order, is_admin: bool
    ) -> bool:
        if is_admin:
            return True
        context = await resolve_provider_access(
            session,
            self.settings,
            actor.telegram_id,
            provider_id=order.provider_id,
            permission="can_review_payments",
            require_terms=True,
        )
        return context.allowed

    async def confirm(
        self,
        session: AsyncSession,
        order_id: int,
        actor: User,
        is_admin: bool,
        confirmed_amount_iqd: int | None = None,
    ) -> tuple[Order, Payment]:
        order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
        if not order:
            raise ValueError("الطلب غير موجود")
        if not await self.can_review(session, actor, order, is_admin):
            raise PermissionError("غير مصرح")
        if order.status == OrderStatus.PAID.value:
            payment = await session.scalar(
                select(Payment)
                .where(
                    Payment.order_id == order.id, Payment.status == PaymentStatus.CONFIRMED.value
                )
                .order_by(Payment.id.desc())
            )
            if payment:
                return order, payment
        if order.status != OrderStatus.PAYMENT_REVIEW.value:
            raise ValueError("حالة الطلب لا تسمح بالمصادقة")
        proof = await self.latest_proof(session, order.id)
        if not proof:
            raise ValueError("لا يوجد إثبات دفع")
        amount_confirmation = await session.scalar(
            select(PaymentAmountConfirmation)
            .where(PaymentAmountConfirmation.payment_proof_id == proof.id)
            .with_for_update()
        )
        if amount_confirmation is None:
            amount_confirmation = PaymentAmountConfirmation(
                payment_proof_id=proof.id,
                order_id=order.id,
                claimed_amount_iqd=int(proof.claimed_amount_iqd),
                status="pending",
            )
            session.add(amount_confirmation)
            await session.flush()
        claimed = int(proof.claimed_amount_iqd)
        confirmed = int(confirmed_amount_iqd if confirmed_amount_iqd is not None else claimed)
        if confirmed <= 0:
            raise ValueError("المبلغ المؤكد يجب أن يكون أكبر من صفر")
        required = int(order.total_iqd)
        wallet_used = net_wallet_fee_deduction(
            order.payment_snapshot,
            current_bot_fee_iqd=int(order.service_fee_iqd or 0),
        )
        wallet_credit = 0
        if confirmed < required:
            shortfall = required - confirmed
            raise ValueError(
                f"المبلغ المحول ناقص {shortfall:,} د.ع. "
                "المحفظة تغطي رسوم البوت تلقائياً فقط ولا تغطي نقص سعر الخدمة."
            )
        elif confirmed > required:
            wallet_credit = await self.wallets.credit_overpayment(
                session, order.user_id, order.id, confirmed, required
            )

        if proof.reference:
            duplicate = await session.scalar(
                select(Payment).where(
                    Payment.gateway_reference == proof.reference,
                    Payment.order_id != order.id,
                )
            )
            if duplicate:
                raise ValueError("رقم العملية مؤكد مسبقًا لطلب آخر")
        amount_confirmation.confirmed_amount_iqd = confirmed
        amount_confirmation.status = "confirmed"
        amount_confirmation.confirmed_by_user_id = actor.id
        amount_confirmation.confirmed_at = datetime.now(UTC)
        proof.status = PaymentProofStatus.CONFIRMED.value
        proof.reviewed_by_user_id = actor.id
        proof.reviewed_at = datetime.now(UTC)
        payment = Payment(
            order_id=order.id,
            payment_method_id=order.payment_method_id,
            gateway_reference=proof.reference or f"MANUAL-{proof.id}",
            amount_iqd=confirmed,
            status=PaymentStatus.CONFIRMED.value,
            confirmed_by_user_id=actor.id,
            confirmed_at=datetime.now(UTC),
            raw_payload={
                "proof_id": proof.id,
                "sender_phone": proof.sender_phone,
                "required_iqd": required,
                "claimed_iqd": claimed,
                "confirmed_iqd": confirmed,
                "wallet_used_iqd": wallet_used,
                "wallet_credit_iqd": wallet_credit,
            },
        )
        session.add(payment)
        await self.orders.change_status(
            session,
            order,
            OrderStatus.PAID.value,
            actor_user_id=actor.id,
            note="تمت مصادقة الدفع يدويًا",
        )
        if self.friend_packages is not None:
            await self.friend_packages.mark_order_paid(
                session, order=order, confirmed_amount_iqd=confirmed
            )
        await session.flush()
        return order, payment

    async def reject(
        self,
        session: AsyncSession,
        order_id: int,
        actor: User,
        is_admin: bool,
        reason: str,
    ) -> Order:
        order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
        if not order:
            raise ValueError("الطلب غير موجود")
        if not await self.can_review(session, actor, order, is_admin):
            raise PermissionError("غير مصرح")
        if order.status != OrderStatus.PAYMENT_REVIEW.value:
            raise ValueError("تمت معالجة هذا الطلب سابقًا")
        proof = await self.latest_proof(session, order.id)
        if proof:
            proof.status = PaymentProofStatus.REJECTED.value
            proof.reviewed_by_user_id = actor.id
            proof.reviewed_at = datetime.now(UTC)
            amount_confirmation = await session.scalar(
                select(PaymentAmountConfirmation)
                .where(PaymentAmountConfirmation.payment_proof_id == proof.id)
                .with_for_update()
            )
            if amount_confirmation:
                amount_confirmation.status = "rejected"
                amount_confirmation.rejection_reason = reason[:2000]
                amount_confirmation.confirmed_by_user_id = actor.id
                amount_confirmation.confirmed_at = datetime.now(UTC)
        await self.orders.change_status(
            session,
            order,
            OrderStatus.PAYMENT_REJECTED.value,
            actor_user_id=actor.id,
            note=reason,
        )
        return order
