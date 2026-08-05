from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.utils import public_id
from app.db.models import (
    LedgerEntry,
    Offer,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    PointsTransaction,
    Provider,
    Refund,
    User,
    WithdrawalRequest,
    WithdrawalStatus,
)
from app.services.orders import OrderService
from app.services.notifications import NotificationService
from app.services.users import UserService


class FinanceService:
    """Legacy accounting facade hardened for idempotency.

    Phase 1 keeps historical ledger reports compatible, while new provider
    withdrawals are disabled by default because students pay providers directly.
    """

    def __init__(
        self,
        settings: Settings,
        orders: OrderService,
        users: UserService,
        notifications: NotificationService,
    ) -> None:
        self.settings = settings
        self.orders = orders
        self.users = users
        self.notifications = notifications

    async def _ensure_order_entry(
        self,
        session: AsyncSession,
        order: Order,
        account_code: str,
        direction: str,
        amount_iqd: int,
        description: str,
    ) -> LedgerEntry:
        key = f"order:{order.id}:ledger:{account_code}"
        row = await session.scalar(
            select(LedgerEntry).where(LedgerEntry.idempotency_key == key)
        )
        if row:
            return row
        row = await session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.order_id == order.id,
                LedgerEntry.account_code == account_code,
            )
        )
        if row:
            row.idempotency_key = row.idempotency_key or key
            return row
        row = LedgerEntry(
            provider_id=order.provider_id,
            order_id=order.id,
            user_id=order.user_id,
            account_code=account_code,
            direction=direction,
            amount_iqd=max(0, int(amount_iqd)),
            description=description,
            idempotency_key=key,
        )
        session.add(row)
        await session.flush()
        return row

    async def finalize_order(
        self,
        session: AsyncSession,
        order: Order,
        actor_user_id: int | None = None,
    ) -> None:
        locked = await session.scalar(
            select(Order).where(Order.id == order.id).with_for_update()
        )
        if not locked:
            raise ValueError("الطلب غير موجود")
        order = locked
        was_completed = order.status == OrderStatus.COMPLETED.value

        await self._ensure_order_entry(
            session,
            order,
            "provider_payable",
            "credit",
            order.provider_net_iqd,
            f"مستحق المنصة عن {order.public_id}",
        )
        await self._ensure_order_entry(
            session,
            order,
            "owner_revenue",
            "credit",
            order.owner_net_iqd,
            f"رسوم وعمولة {order.public_id}",
        )

        order.completed_at = order.completed_at or datetime.now(UTC)
        if not was_completed:
            await self.orders.change_status(
                session,
                order,
                OrderStatus.COMPLETED.value,
                actor_user_id=actor_user_id,
                note="تم تأكيد نجاح التفعيل",
            )
            offer = await session.get(Offer, order.offer_id)
            if offer:
                offer.sold_today += 1

        user = await session.get(User, order.user_id)
        if user:
            await self.users.add_points(
                session,
                user,
                5,
                "طلب مكتمل",
                "order",
                order.id,
                idempotency_key=f"order:{order.id}:points:buyer",
            )
            if self.settings.feature_referrals and user.referred_by_user_id:
                # V11 status-and-rewards: the first completed purchase from a
                # referral grants configurable activity points. Monetary rewards
                # are campaign-driven; no automatic fee-waiver coupon is created.
                completed_count = int(
                    await session.scalar(
                        select(func.count(Order.id)).where(
                            Order.user_id == user.id,
                            Order.status == OrderStatus.COMPLETED.value,
                        )
                    )
                    or 0
                )
                if completed_count == 1:
                    referrer = await session.scalar(
                        select(User)
                        .where(User.id == user.referred_by_user_id)
                        .with_for_update()
                    )
                    if referrer:
                        success_key = (
                            f"referral:success:{user.id}:referrer:{referrer.id}"
                        )
                        awarded = await self.users.add_points(
                            session,
                            referrer,
                            max(0, int(self.settings.referral_reward_points)),
                            "إحالة أكملت أول اشتراك ناجح",
                            "referral",
                            order.id,
                            idempotency_key=success_key,
                        )
                        if awarded:
                            await self.notifications.send_user(
                                session,
                                referrer,
                                "🌟 ارتفعت حالتك في نظام المكافآت",
                                "أحد الطلاب الذين دعوتهم أكمل أول اشتراك ناجح. "
                                f"تمت إضافة {max(0, int(self.settings.referral_reward_points))} "
                                "نقطة نشاط إلى حالتك.",
                                idempotency_key=(
                                    f"status-reward-notify:{referrer.id}:{user.id}"
                                ),
                            )
                        await self._ensure_order_entry(
                            session,
                            order,
                            "referral_awarded",
                            "debit",
                            0,
                            "علامة منع تكرار تقدم الإحالة",
                        )

        await session.flush()


    async def apply_refund_reversal(
        self,
        session: AsyncSession,
        order: Order,
        refund: Refund,
        actor_user_id: int | None = None,
    ) -> tuple[int, int]:
        """Post one idempotent reversal for an approved refund.

        The launch model is provider-direct: the provider returns cash to the
        student outside the bot. This method only corrects the bot's accounting
        after transfer confirmation; it never claims that the bot moved money.
        """
        locked_order = await session.scalar(
            select(Order).where(Order.id == order.id).with_for_update()
        )
        if not locked_order:
            raise ValueError("الطلب غير موجود")
        order = locked_order
        locked_refund = await session.scalar(
            select(Refund).where(Refund.id == refund.id).with_for_update()
        )
        if not locked_refund:
            raise ValueError("سجل الاسترجاع غير موجود")
        refund = locked_refund
        amount = max(0, min(int(refund.amount_iqd), int(order.total_iqd)))
        if amount <= 0:
            raise ValueError("مبلغ الاسترجاع غير صالح")

        ratio = amount / max(1, int(order.total_iqd))
        owner_reversal = min(int(order.owner_net_iqd), round(int(order.owner_net_iqd) * ratio))
        provider_reversal = min(int(order.provider_net_iqd), amount - owner_reversal)
        remainder = amount - owner_reversal - provider_reversal
        if remainder > 0:
            provider_reversal += remainder

        for account_code, reversal_amount, description in (
            (
                "provider_payable_refund",
                provider_reversal,
                f"عكس مستحق المنصة بسبب الاسترجاع {refund.public_id}",
            ),
            (
                "owner_revenue_refund",
                owner_reversal,
                f"عكس رسوم وعمولة بسبب الاسترجاع {refund.public_id}",
            ),
        ):
            key = f"refund:{refund.id}:ledger:{account_code}"
            existing = await session.scalar(
                select(LedgerEntry).where(LedgerEntry.idempotency_key == key)
            )
            if not existing:
                session.add(
                    LedgerEntry(
                        provider_id=order.provider_id,
                        order_id=order.id,
                        user_id=order.user_id,
                        account_code=account_code,
                        direction="debit",
                        amount_iqd=max(0, reversal_amount),
                        description=description,
                        idempotency_key=key,
                    )
                )

        payment = await session.scalar(
            select(Payment)
            .where(Payment.order_id == order.id, Payment.status == PaymentStatus.CONFIRMED.value)
            .order_by(Payment.id.desc())
            .with_for_update()
        )
        if payment:
            payment.refunded_amount_iqd = max(
                int(payment.refunded_amount_iqd or 0), amount
            )
            payment.last_refunded_at = datetime.now(UTC)
            if amount >= order.total_iqd:
                payment.status = PaymentStatus.REFUNDED.value

        order.refund_total_iqd = max(int(order.refund_total_iqd or 0), amount)
        order.refunded_at = order.refunded_at or datetime.now(UTC)

        if amount >= order.total_iqd:
            user = await session.get(User, order.user_id)
            if user:
                buyer_tx = await session.scalar(
                    select(PointsTransaction).where(
                        PointsTransaction.idempotency_key == f"order:{order.id}:points:buyer"
                    )
                )
                if buyer_tx and not await session.scalar(
                    select(PointsTransaction.id).where(
                        PointsTransaction.idempotency_key == f"refund:{refund.id}:points:buyer"
                    )
                ):
                    # Reverse the full earned amount even if the points were already
                    # spent. A negative balance represents loyalty debt and prevents a
                    # refund-after-spend exploit from preserving an unearned benefit.
                    deduction = max(0, int(buyer_tx.amount))
                    user.points -= deduction
                    session.add(
                        PointsTransaction(
                            user_id=user.id,
                            amount=-deduction,
                            reason="عكس نقاط طلب مسترجع",
                            reference_type="refund",
                            reference_id=refund.id,
                            idempotency_key=f"refund:{refund.id}:points:buyer",
                        )
                    )
                if user.referred_by_user_id:
                    referrer = await session.get(User, user.referred_by_user_id)
                    referral_tx = await session.scalar(
                        select(PointsTransaction).where(
                            PointsTransaction.idempotency_key
                            == f"order:{order.id}:points:referrer:{user.referred_by_user_id}"
                        )
                    )
                    if referrer and referral_tx and not await session.scalar(
                        select(PointsTransaction.id).where(
                            PointsTransaction.idempotency_key
                            == f"refund:{refund.id}:points:referrer:{referrer.id}"
                        )
                    ):
                        deduction = max(0, int(referral_tx.amount))
                        referrer.points -= deduction
                        session.add(
                            PointsTransaction(
                                user_id=referrer.id,
                                amount=-deduction,
                                reason="عكس مكافأة إحالة لطلب مسترجع",
                                reference_type="refund",
                                reference_id=refund.id,
                                idempotency_key=f"refund:{refund.id}:points:referrer:{referrer.id}",
                            )
                        )
        await session.flush()
        return provider_reversal, owner_reversal

    async def provider_balance(self, session: AsyncSession, provider_id: int) -> int:
        credits = await session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount_iqd), 0)).where(
                LedgerEntry.provider_id == provider_id,
                LedgerEntry.account_code == "provider_payable",
                LedgerEntry.direction == "credit",
                LedgerEntry.status == "posted",
            )
        )
        debits = await session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount_iqd), 0)).where(
                LedgerEntry.provider_id == provider_id,
                LedgerEntry.account_code.in_(
                    ["provider_withdrawal", "provider_payable_refund"]
                ),
                LedgerEntry.direction == "debit",
                LedgerEntry.status == "posted",
            )
        )
        return int(credits or 0) - int(debits or 0)

    async def request_withdrawal(
        self,
        session: AsyncSession,
        provider_id: int,
        user: User,
        amount_iqd: int,
        method: str,
        destination: str,
    ) -> WithdrawalRequest:
        if not self.settings.provider_withdrawals_ready:
            raise ValueError(
                "طلبات السحب مفعلة لكنها تنتظر ربط بوابة الدفع وتحويل نموذج الأموال إلى marketplace"
            )
        # Serialize requests for the same provider. This preserves old deployments
        # that deliberately enable marketplace payouts.
        provider = await session.scalar(
            select(Provider).where(Provider.id == provider_id).with_for_update()
        )
        if not provider:
            raise ValueError("المنصة غير موجودة")
        balance = await self.provider_balance(session, provider_id)
        pending = await session.scalar(
            select(func.coalesce(func.sum(WithdrawalRequest.amount_iqd), 0)).where(
                WithdrawalRequest.provider_id == provider_id,
                WithdrawalRequest.status.in_(
                    [
                        WithdrawalStatus.PENDING.value,
                        WithdrawalStatus.APPROVED.value,
                    ]
                ),
            )
        )
        available = balance - int(pending or 0)
        if amount_iqd <= 0 or amount_iqd > available:
            raise ValueError("المبلغ أكبر من الرصيد المتاح")
        request = WithdrawalRequest(
            public_id=public_id("WD"),
            provider_id=provider_id,
            requested_by_user_id=user.id,
            amount_iqd=amount_iqd,
            method=method[:80],
            destination=destination[:255],
        )
        session.add(request)
        await session.flush()
        return request

    async def mark_withdrawal_paid(
        self,
        session: AsyncSession,
        request: WithdrawalRequest,
        actor: User,
        proof_file_id: str | None = None,
    ) -> None:
        locked = await session.scalar(
            select(WithdrawalRequest)
            .where(WithdrawalRequest.id == request.id)
            .with_for_update()
        )
        if not locked:
            raise ValueError("طلب السحب غير موجود")
        request = locked
        if request.status == WithdrawalStatus.PAID.value:
            return
        if request.status not in {
            WithdrawalStatus.PENDING.value,
            WithdrawalStatus.APPROVED.value,
        }:
            raise ValueError("لا يمكن تعليم طلب مرفوض أو ملغى بأنه مدفوع")
        request.status = WithdrawalStatus.PAID.value
        request.processed_by_user_id = actor.id
        request.processed_at = datetime.now(UTC)
        request.proof_file_id = proof_file_id
        key = f"withdrawal:{request.id}:paid"
        if not await session.scalar(
            select(LedgerEntry.id).where(LedgerEntry.idempotency_key == key)
        ):
            session.add(
                LedgerEntry(
                    provider_id=request.provider_id,
                    account_code="provider_withdrawal",
                    direction="debit",
                    amount_iqd=request.amount_iqd,
                    description=f"سحب {request.public_id}",
                    idempotency_key=key,
                )
            )
        await session.flush()
