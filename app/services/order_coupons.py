from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Order,
    CouponAssignment,
    CouponCampaign,
    OrderCoupon,
    OrderCouponRedemption,
    OrderCouponType,
    OrderStatus,
    User,
    UserBenefit,
)
from app.services.wallets import WalletService


class OrderCouponService:
    """Purchase-level coupons for students.

    Coupons can be global, provider-specific, or restricted to one student.
    Monetary coupons are applied atomically to the locked order. Non-cash
    benefits are granted in an additive entitlement table without rewriting
    historical orders or payment records.
    """

    def __init__(self, wallets: WalletService) -> None:
        self.wallets = wallets

    async def apply(
        self,
        session: AsyncSession,
        order: Order,
        user: User,
        code: str,
    ) -> tuple[OrderCoupon, int]:
        locked = await session.scalar(select(Order).where(Order.id == order.id).with_for_update())
        if not locked or locked.user_id != user.id:
            raise ValueError("الطلب غير موجود أو لا يخص حسابك")
        order = locked
        if order.status not in {
            OrderStatus.WAITING_PAYMENT.value,
            OrderStatus.PAYMENT_REJECTED.value,
        }:
            raise ValueError("لا يمكن تطبيق كود خصم بعد بدء مراجعة الدفع")

        normalized = (code or "").strip().upper()
        coupon = await session.scalar(
            select(OrderCoupon).where(OrderCoupon.code == normalized).with_for_update()
        )
        if not coupon or not coupon.is_active:
            raise ValueError("كود الخصم غير موجود أو متوقف")
        now = datetime.now(UTC)
        if coupon.valid_from and coupon.valid_from > now:
            raise ValueError("كود الخصم لم يبدأ بعد")
        if coupon.valid_until and coupon.valid_until < now:
            raise ValueError("انتهت صلاحية كود الخصم")
        if coupon.provider_id is not None and coupon.provider_id != order.provider_id:
            raise ValueError("هذا الكود مخصص لمنصة أخرى")
        if coupon.target_user_id is not None and coupon.target_user_id != user.id:
            raise ValueError("هذا الكود مخصص لطالب آخر")
        if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
            raise ValueError("اكتمل عدد استخدامات كود الخصم")
        campaign = await session.scalar(
            select(CouponCampaign).where(CouponCampaign.coupon_id == coupon.id)
        )
        assignment = None
        if campaign:
            assignment = await session.scalar(
                select(CouponAssignment)
                .where(
                    CouponAssignment.campaign_id == campaign.id,
                    CouponAssignment.user_id == user.id,
                )
                .with_for_update()
            )
            if not assignment or assignment.status not in {"available", "notified"}:
                raise ValueError("هذا الكود غير مخصص لحسابك")
        if await session.scalar(
            select(OrderCouponRedemption.id).where(OrderCouponRedemption.order_id == order.id)
        ):
            raise ValueError("تم تطبيق كود خصم على هذا الطلب سابقًا")
        used_by_user = int(
            await session.scalar(
                select(func.count())
                .select_from(OrderCouponRedemption)
                .where(
                    OrderCouponRedemption.coupon_id == coupon.id,
                    OrderCouponRedemption.user_id == user.id,
                )
            )
            or 0
        )
        if used_by_user >= max(1, int(coupon.per_user_limit or 1)):
            raise ValueError("وصلت إلى حد استخدام هذا الكود")

        discount = 0
        if coupon.coupon_type in {
            OrderCouponType.FIXED.value,
            OrderCouponType.PERCENT.value,
        }:
            base = max(0, int(order.subtotal_iqd))
            if coupon.coupon_type == OrderCouponType.PERCENT.value:
                if not 1 <= coupon.value_int <= 100:
                    raise ValueError("نسبة الخصم غير صالحة")
                discount = round(base * coupon.value_int / 100)
            else:
                discount = max(0, int(coupon.value_int))
            discount = min(base, discount)
            if discount <= 0:
                raise ValueError("قيمة الخصم لا تؤثر على هذا الطلب")

            old_subtotal = max(1, base)
            new_subtotal = max(0, base - discount)
            old_management = max(0, int(order.management_fee_iqd))
            new_management = min(
                new_subtotal,
                round(old_management * new_subtotal / old_subtotal),
            )
            order.subtotal_iqd = new_subtotal
            order.management_fee_iqd = new_management
            order.provider_net_iqd = max(0, new_subtotal - new_management)
            order.owner_net_iqd = max(0, int(order.service_fee_iqd) + new_management)
            snapshot = dict(order.payment_snapshot or {})
            wallet_fee_used = max(
                0,
                int(snapshot.get("wallet_fee_deduction_iqd", 0) or 0)
                - int(snapshot.get("wallet_fee_refunded_iqd", 0) or 0),
            )
            order.total_iqd = max(
                0, new_subtotal + int(order.service_fee_iqd) - wallet_fee_used
            )
            snapshot["cash_due_iqd"] = int(order.total_iqd)
            order.payment_snapshot = snapshot

        elif coupon.coupon_type == OrderCouponType.FEE_WAIVER.value:
            discount = max(0, int(order.service_fee_iqd))
            if discount <= 0:
                raise ValueError("رسوم البوت مسقطة مسبقًا عن هذا الطلب")
            snapshot = dict(order.payment_snapshot or {})
            wallet_fee_used = max(
                0,
                int(snapshot.get("wallet_fee_deduction_iqd", 0) or 0)
                - int(snapshot.get("wallet_fee_refunded_iqd", 0) or 0),
            )
            if wallet_fee_used:
                await self.wallets.refund_service_fee(
                    session,
                    user_id=user.id,
                    order_id=order.id,
                    amount_iqd=wallet_fee_used,
                    reason="إعادة رسوم البوت بعد تطبيق كود إعفاء",
                )
                snapshot["wallet_fee_refunded_iqd"] = (
                    int(snapshot.get("wallet_fee_refunded_iqd", 0) or 0)
                    + wallet_fee_used
                )
                snapshot["wallet_fee_refund_reason"] = "coupon_fee_waiver"
            order.service_fee_iqd = 0
            order.owner_net_iqd = max(0, int(order.owner_net_iqd) - discount)
            order.total_iqd = max(0, int(order.subtotal_iqd))
            snapshot["cash_due_iqd"] = int(order.total_iqd)
            order.payment_snapshot = snapshot

        elif coupon.coupon_type == OrderCouponType.FREE_REPORT.value:
            existing_benefit = await session.scalar(
                select(UserBenefit.id).where(
                    UserBenefit.user_id == user.id,
                    UserBenefit.source_coupon_id == coupon.id,
                )
            )
            if existing_benefit:
                raise ValueError("تم تفعيل ميزة التقرير المجاني بهذا الكود سابقًا")
            session.add(
                UserBenefit(
                    user_id=user.id,
                    provider_id=order.provider_id,
                    benefit_key="free_report",
                    quantity=1,
                    source_coupon_id=coupon.id,
                    expires_at=coupon.valid_until,
                )
            )
        else:
            raise ValueError("نوع كود الخصم غير مدعوم")

        session.add(
            OrderCouponRedemption(
                coupon_id=coupon.id,
                order_id=order.id,
                user_id=user.id,
                provider_id=order.provider_id,
                discount_iqd=discount,
            )
        )
        coupon.used_count += 1
        if assignment is not None:
            assignment.status = "redeemed"
            assignment.redeemed_at = datetime.now(UTC)
        await session.flush()
        return coupon, discount

    async def create(
        self,
        session: AsyncSession,
        *,
        code: str,
        coupon_type: str,
        value_int: int,
        provider_id: int | None,
        created_by_user_id: int | None,
        target_user_id: int | None = None,
        max_uses: int | None = None,
        per_user_limit: int = 1,
    ) -> OrderCoupon:
        normalized = (code or "").strip().upper()
        if not 3 <= len(normalized) <= 40 or not normalized.replace("-", "").replace(
            "_", ""
        ).isalnum():
            raise ValueError("صيغة كود الخصم غير صالحة")
        if await session.scalar(select(OrderCoupon.id).where(OrderCoupon.code == normalized)):
            raise ValueError("كود الخصم مستخدم مسبقًا")
        allowed = {
            OrderCouponType.FIXED.value,
            OrderCouponType.PERCENT.value,
            OrderCouponType.FEE_WAIVER.value,
            OrderCouponType.FREE_REPORT.value,
        }
        if coupon_type not in allowed:
            raise ValueError("نوع الخصم غير صالح")
        value = int(value_int)
        if coupon_type == OrderCouponType.PERCENT.value and not 1 <= value <= 100:
            raise ValueError("النسبة يجب أن تكون من 1 إلى 100")
        if coupon_type == OrderCouponType.FIXED.value and value <= 0:
            raise ValueError("قيمة الخصم يجب أن تكون أكبر من صفر")
        if coupon_type in {
            OrderCouponType.FEE_WAIVER.value,
            OrderCouponType.FREE_REPORT.value,
        }:
            value = 0
        if target_user_id is not None:
            if not await session.get(User, int(target_user_id)):
                raise ValueError("الطالب المحدد غير موجود")
            max_uses = 1
            per_user_limit = 1
        coupon = OrderCoupon(
            code=normalized,
            coupon_type=coupon_type,
            value_int=value,
            provider_id=provider_id,
            target_user_id=target_user_id,
            max_uses=max_uses,
            per_user_limit=max(1, int(per_user_limit)),
            created_by_user_id=created_by_user_id,
        )
        session.add(coupon)
        await session.flush()
        return coupon
