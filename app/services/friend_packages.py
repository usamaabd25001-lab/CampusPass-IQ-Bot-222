from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import calculate_order_amounts, public_id
from app.db.models import (
    DeliveryJob,
    DeliveryJobStatus,
    FriendEscrowEntry,
    FriendEscrowEntryType,
    FriendGroup,
    FriendGroupMember,
    FriendGroupStatus,
    FriendMemberStatus,
    FriendPackageConfig,
    InventoryItem,
    InventoryStatus,
    Offer,
    Order,
    OrderStatus,
    PaymentMethod,
    PurchaseReservation,
    ReservationStatus,
    User,
    WalletEntryType,
    WalletOwnerType,
)
from app.domain.friend_packages import (
    FriendPackageProgress,
    hash_join_token,
    issue_join_token,
    service_share_for_index,
)
from app.services.notifications import NotificationService
from app.services.orders import OrderService
from app.services.subscriptions import SubscriptionService
from app.services.wallets import WalletService


@dataclass(slots=True, frozen=True)
class FriendJoinResult:
    group: FriendGroup
    member: FriendGroupMember
    order: Order
    join_token: str | None = None


class FriendPackageService:
    """Transactional engine for «باقة أصدقائي فقط».

    One inventory account is reserved for the entire group. Each member owns a
    separate order and pays the full bot fee. Money is held in the group escrow
    until every required member is confirmed.
    """

    def __init__(
        self,
        orders: OrderService,
        wallets: WalletService,
        subscriptions: SubscriptionService,
        notifications: NotificationService | None = None,
    ) -> None:
        self.orders = orders
        self.wallets = wallets
        self.subscriptions = subscriptions
        self.notifications = notifications

    async def configure(
        self,
        session: AsyncSession,
        *,
        provider_id: int,
        offer_id: int,
        actor_user_id: int,
        enabled: bool,
        required_members: int,
        join_window_hours: int = 24,
        metadata: dict[str, Any] | None = None,
    ) -> FriendPackageConfig:
        if required_members < 2 or required_members > 50:
            raise ValueError("عدد الأصدقاء يجب أن يكون بين 2 و50")
        if join_window_hours != 24:
            raise ValueError("مهلة اكتمال باقة أصدقائي فقط هي 24 ساعة")
        offer = await session.get(Offer, int(offer_id))
        if not offer or offer.provider_id != int(provider_id):
            raise PermissionError("العرض لا يتبع هذه المنصة")
        row = await session.scalar(
            select(FriendPackageConfig)
            .where(FriendPackageConfig.offer_id == int(offer_id))
            .with_for_update()
        )
        if row is None:
            row = FriendPackageConfig(
                provider_id=int(provider_id),
                offer_id=int(offer_id),
                required_members=int(required_members),
            )
            session.add(row)
        row.is_enabled = bool(enabled)
        row.required_members = int(required_members)
        row.join_window_hours = 24
        row.full_bot_fee_per_member = True
        row.accepted_by_user_id = int(actor_user_id) if enabled else row.accepted_by_user_id
        row.accepted_at = datetime.now(UTC) if enabled else row.accepted_at
        row.metadata_json = dict(metadata or row.metadata_json or {})
        await session.flush()
        return row

    async def config_for_offer(
        self, session: AsyncSession, offer_id: int, *, lock: bool = False
    ) -> FriendPackageConfig | None:
        stmt = select(FriendPackageConfig).where(
            FriendPackageConfig.offer_id == int(offer_id),
            FriendPackageConfig.is_enabled.is_(True),
        )
        if lock:
            stmt = stmt.with_for_update()
        return await session.scalar(stmt)

    async def open_group(
        self,
        session: AsyncSession,
        *,
        creator: User,
        offer: Offer,
    ) -> FriendJoinResult:
        config = await self.config_for_offer(session, offer.id, lock=True)
        if config is None:
            raise ValueError("باقة أصدقائي فقط غير مفعلة لهذا العرض")
        existing = await session.scalar(
            select(FriendGroup)
            .where(
                FriendGroup.creator_user_id == creator.id,
                FriendGroup.offer_id == offer.id,
                FriendGroup.status == FriendGroupStatus.OPEN.value,
                FriendGroup.expires_at > datetime.now(UTC),
            )
            .with_for_update()
        )
        if existing:
            member = await session.scalar(
                select(FriendGroupMember).where(
                    FriendGroupMember.group_id == existing.id,
                    FriendGroupMember.user_id == creator.id,
                )
            )
            if not member:
                raise RuntimeError("بيانات منشئ المجموعة غير مكتملة")
            order = await session.get(Order, member.order_id)
            if not order:
                raise RuntimeError("طلب منشئ المجموعة غير موجود")
            return FriendJoinResult(existing, member, order, None)

        item = await session.scalar(
            select(InventoryItem)
            .where(
                InventoryItem.offer_id == offer.id,
                InventoryItem.status == InventoryStatus.AVAILABLE.value,
                (InventoryItem.expires_at.is_(None))
                | (InventoryItem.expires_at > datetime.now(UTC)),
            )
            .order_by(InventoryItem.expires_at.asc().nullslast(), InventoryItem.id.asc())
            .with_for_update(skip_locked=True)
        )
        if item is None:
            raise ValueError("لا يوجد حساب متاح حالياً لإنشاء باقة أصدقاء")
        token, token_hash = issue_join_token()
        group = FriendGroup(
            public_id=public_id("FRIENDS"),
            join_token_hash=token_hash,
            config_id=config.id,
            provider_id=offer.provider_id,
            offer_id=offer.id,
            creator_user_id=creator.id,
            inventory_item_id=item.id,
            required_members=config.required_members,
            service_total_iqd=int(offer.price_iqd),
            bot_fee_per_member_iqd=int(offer.service_fee_iqd),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            metadata_json={"full_bot_fee_per_member": True},
        )
        session.add(group)
        await session.flush()
        result = await self._add_member(session, group=group, user=creator, is_creator=True)
        item.status = InventoryStatus.RESERVED.value
        item.reserved_order_id = result.order.id
        item.reserved_at = datetime.now(UTC)
        group.reservation_order_id = result.order.id
        session.add(
            PurchaseReservation(
                order_id=result.order.id,
                offer_id=offer.id,
                inventory_item_id=item.id,
                status=ReservationStatus.HELD.value,
                held_at=datetime.now(UTC),
                expires_at=group.expires_at,
            )
        )
        await session.flush()
        return FriendJoinResult(group, result.member, result.order, token)

    async def join(
        self,
        session: AsyncSession,
        *,
        token: str,
        user: User,
    ) -> FriendJoinResult:
        group = await session.scalar(
            select(FriendGroup)
            .where(FriendGroup.join_token_hash == hash_join_token(token))
            .with_for_update()
        )
        if group is None:
            raise ValueError("رابط باقة الأصدقاء غير صالح")
        now = datetime.now(UTC)
        if group.status != FriendGroupStatus.OPEN.value or group.expires_at <= now:
            raise ValueError("انتهت أو أُغلقت باقة الأصدقاء")
        existing = await session.scalar(
            select(FriendGroupMember).where(
                FriendGroupMember.group_id == group.id,
                FriendGroupMember.user_id == user.id,
            )
        )
        if existing:
            order = await session.get(Order, existing.order_id)
            if not order:
                raise RuntimeError("طلب عضو المجموعة غير موجود")
            return FriendJoinResult(group, existing, order)
        count = int(
            await session.scalar(
                select(func.count())
                .select_from(FriendGroupMember)
                .where(FriendGroupMember.group_id == group.id)
            )
            or 0
        )
        if count >= group.required_members:
            raise ValueError("اكتمل عدد الأصدقاء في هذه المجموعة")
        return await self._add_member(session, group=group, user=user, is_creator=False)

    async def _add_member(
        self,
        session: AsyncSession,
        *,
        group: FriendGroup,
        user: User,
        is_creator: bool,
    ) -> FriendJoinResult:
        position = int(
            await session.scalar(
                select(func.count())
                .select_from(FriendGroupMember)
                .where(FriendGroupMember.group_id == group.id)
            )
            or 0
        )
        if position >= group.required_members:
            raise ValueError("اكتمل عدد الأصدقاء")
        offer = await session.get(Offer, group.offer_id)
        if offer is None:
            raise ValueError("العرض غير موجود")
        methods = list(
            (
                await session.scalars(
                    select(PaymentMethod).where(
                        PaymentMethod.provider_id == group.provider_id,
                        PaymentMethod.is_active.is_(True),
                    )
                )
            ).all()
        )
        if not methods:
            raise ValueError("لا توجد طريقة دفع مفعلة لهذه المنصة")
        share = service_share_for_index(
            group.service_total_iqd, group.required_members, position
        )
        # Friend-package distribution uses the configured offer price. Existing
        # platform management fees remain zero in this dedicated escrow flow.
        management_percent = 0
        amounts = calculate_order_amounts(share, group.bot_fee_per_member_iqd, management_percent)
        order = Order(
            public_id=public_id("CP"),
            idempotency_key=f"friend-group:{group.id}:user:{user.id}",
            user_id=user.id,
            provider_id=group.provider_id,
            offer_id=group.offer_id,
            status=OrderStatus.WAITING_PAYMENT.value,
            subtotal_iqd=amounts["subtotal_iqd"],
            service_fee_iqd=amounts["service_fee_iqd"],
            total_iqd=amounts["total_iqd"],
            management_fee_iqd=amounts["management_fee_iqd"],
            provider_net_iqd=amounts["provider_net_iqd"],
            owner_net_iqd=amounts["owner_net_iqd"],
            activation_data={"friend_group_id": group.id, "member_index": position},
            payment_snapshot={"scope": "friend_package", "group_id": group.id},
        )
        session.add(order)
        await session.flush()
        wallet_used = await self.wallets.apply_service_fee_only(
            session,
            user_id=user.id,
            order_id=order.id,
            service_fee_iqd=group.bot_fee_per_member_iqd,
        )
        cash_due = share + group.bot_fee_per_member_iqd - wallet_used
        order.total_iqd = cash_due
        order.payment_snapshot = {
            "scope": "friend_package",
            "group_id": group.id,
            "service_price_iqd": share,
            "bot_fee_iqd": group.bot_fee_per_member_iqd,
            "wallet_fee_deduction_iqd": wallet_used,
            "cash_due_iqd": cash_due,
        }
        member = FriendGroupMember(
            group_id=group.id,
            user_id=user.id,
            order_id=order.id,
            member_index=position,
            is_creator=is_creator,
            service_share_iqd=share,
            bot_fee_iqd=group.bot_fee_per_member_iqd,
            wallet_fee_deduction_iqd=wallet_used,
            cash_due_iqd=cash_due,
        )
        session.add(member)
        await session.flush()
        return FriendJoinResult(group, member, order)

    async def member_for_order(
        self, session: AsyncSession, order_id: int, *, lock: bool = False
    ) -> FriendGroupMember | None:
        stmt = select(FriendGroupMember).where(FriendGroupMember.order_id == int(order_id))
        if lock:
            stmt = stmt.with_for_update()
        return await session.scalar(stmt)

    async def mark_order_paid(
        self,
        session: AsyncSession,
        *,
        order: Order,
        confirmed_amount_iqd: int,
    ) -> FriendGroup | None:
        member = await self.member_for_order(session, order.id, lock=True)
        if member is None:
            return None
        group = await session.scalar(
            select(FriendGroup).where(FriendGroup.id == member.group_id).with_for_update()
        )
        if group is None:
            raise RuntimeError("مجموعة الأصدقاء غير موجودة")
        if member.status in {FriendMemberStatus.PAID.value, FriendMemberStatus.DELIVERED.value}:
            return group
        if group.status != FriendGroupStatus.OPEN.value:
            raise ValueError("المجموعة لم تعد تستقبل دفعات")
        member.status = FriendMemberStatus.PAID.value
        member.paid_amount_iqd = int(confirmed_amount_iqd)
        member.paid_at = datetime.now(UTC)
        group.escrow_service_iqd += member.service_share_iqd
        group.escrow_bot_fee_iqd += member.bot_fee_iqd
        session.add(
            FriendEscrowEntry(
                group_id=group.id,
                member_id=member.id,
                order_id=order.id,
                entry_type=FriendEscrowEntryType.DEPOSIT.value,
                service_amount_iqd=member.service_share_iqd,
                bot_fee_iqd=member.bot_fee_iqd,
                total_iqd=member.service_share_iqd + member.bot_fee_iqd,
                idempotency_key=f"friend-group:{group.id}:member:{member.id}:deposit",
                metadata_json={"confirmed_cash_iqd": int(confirmed_amount_iqd)},
            )
        )
        # The current member has already been persisted as PAID in this transaction,
        # therefore the aggregate query includes it. Adding one again would complete
        # groups early under concurrent confirmations.
        group.paid_members = int(
            await session.scalar(
                select(func.count())
                .select_from(FriendGroupMember)
                .where(
                    FriendGroupMember.group_id == group.id,
                    FriendGroupMember.status.in_(
                        [FriendMemberStatus.PAID.value, FriendMemberStatus.DELIVERED.value]
                    ),
                )
            )
            or 0
        )
        group.paid_members = min(group.required_members, group.paid_members)
        if group.paid_members >= group.required_members:
            await self._complete_group(session, group)
        await session.flush()
        return group

    async def _complete_group(self, session: AsyncSession, group: FriendGroup) -> None:
        if group.status in {
            FriendGroupStatus.COMPLETED.value,
            FriendGroupStatus.DELIVERING.value,
            FriendGroupStatus.DELIVERED.value,
        }:
            return
        members = list(
            (
                await session.scalars(
                    select(FriendGroupMember)
                    .where(
                        FriendGroupMember.group_id == group.id,
                        FriendGroupMember.status == FriendMemberStatus.PAID.value,
                    )
                    .with_for_update()
                )
            ).all()
        )
        if len(members) != group.required_members:
            return
        group.status = FriendGroupStatus.DELIVERING.value
        group.completed_at = datetime.now(UTC)
        reservation = await session.scalar(
            select(PurchaseReservation)
            .where(PurchaseReservation.order_id == group.reservation_order_id)
            .with_for_update()
        )
        if reservation:
            reservation.status = ReservationStatus.CONFIRMED.value
            reservation.confirmed_at = datetime.now(UTC)
        service_total = sum(member.service_share_iqd for member in members)
        bot_fee_total = sum(member.bot_fee_iqd for member in members)
        session.add_all(
            [
                FriendEscrowEntry(
                    group_id=group.id,
                    entry_type=FriendEscrowEntryType.RELEASE_PROVIDER.value,
                    service_amount_iqd=service_total,
                    total_iqd=service_total,
                    idempotency_key=f"friend-group:{group.id}:release:provider",
                ),
                FriendEscrowEntry(
                    group_id=group.id,
                    entry_type=FriendEscrowEntryType.RELEASE_OWNER.value,
                    bot_fee_iqd=bot_fee_total,
                    total_iqd=bot_fee_total,
                    idempotency_key=f"friend-group:{group.id}:release:owner",
                ),
            ]
        )
        group.escrow_service_iqd = 0
        group.escrow_bot_fee_iqd = 0
        for member in members:
            order = await session.get(Order, member.order_id)
            if order:
                await self.orders.change_status(
                    session,
                    order,
                    OrderStatus.WAITING_FULFILLMENT.value,
                    note="اكتمل عدد باقة أصدقائي فقط وبدأ التسليم المتزامن",
                    metadata={"friend_group_id": group.id},
                )
            exists = await session.scalar(
                select(DeliveryJob.id).where(
                    DeliveryJob.idempotency_key
                    == f"friend-group:{group.id}:member:{member.id}:delivery"
                )
            )
            if not exists:
                session.add(
                    DeliveryJob(
                        order_id=member.order_id,
                        inventory_item_id=group.inventory_item_id,
                        job_type="friend_group_delivery",
                        idempotency_key=f"friend-group:{group.id}:member:{member.id}:delivery",
                        status=DeliveryJobStatus.PENDING.value,
                    )
                )
        await session.flush()

    async def progress(self, session: AsyncSession, group_id: int) -> FriendPackageProgress:
        group = await session.get(FriendGroup, int(group_id))
        if group is None:
            raise ValueError("المجموعة غير موجودة")
        paid = int(
            await session.scalar(
                select(func.count())
                .select_from(FriendGroupMember)
                .where(
                    FriendGroupMember.group_id == group.id,
                    FriendGroupMember.status.in_(
                        [FriendMemberStatus.PAID.value, FriendMemberStatus.DELIVERED.value]
                    ),
                )
            )
            or 0
        )
        return FriendPackageProgress(group.required_members, paid)

    async def expire_groups(self, session: AsyncSession, *, limit: int = 100) -> int:
        now = datetime.now(UTC)
        groups = list(
            (
                await session.scalars(
                    select(FriendGroup)
                    .where(
                        FriendGroup.status == FriendGroupStatus.OPEN.value,
                        FriendGroup.expires_at <= now,
                    )
                    .order_by(FriendGroup.expires_at)
                    .limit(max(1, min(limit, 500)))
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for group in groups:
            members = list(
                (
                    await session.scalars(
                        select(FriendGroupMember)
                        .where(FriendGroupMember.group_id == group.id)
                        .with_for_update()
                    )
                ).all()
            )
            for member in members:
                order = await session.get(Order, member.order_id)
                if member.status == FriendMemberStatus.PAID.value:
                    refund = member.service_share_iqd + member.bot_fee_iqd
                    await self.wallets.post(
                        session,
                        owner_type=WalletOwnerType.USER.value,
                        owner_id=member.user_id,
                        amount_iqd=refund,
                        direction="credit",
                        entry_type=WalletEntryType.REFUND.value,
                        idempotency_key=f"friend-group:{group.id}:member:{member.id}:refund",
                        order_id=member.order_id,
                        provider_id=group.provider_id,
                        description="استرداد باقة أصدقائي فقط لعدم اكتمال العدد خلال 24 ساعة",
                        metadata={"friend_group_id": group.id},
                    )
                    session.add(
                        FriendEscrowEntry(
                            group_id=group.id,
                            member_id=member.id,
                            order_id=member.order_id,
                            entry_type=FriendEscrowEntryType.REFUND.value,
                            service_amount_iqd=member.service_share_iqd,
                            bot_fee_iqd=member.bot_fee_iqd,
                            total_iqd=refund,
                            idempotency_key=f"friend-group:{group.id}:member:{member.id}:escrow-refund",
                        )
                    )
                    member.status = FriendMemberStatus.REFUNDED.value
                    member.refunded_at = now
                    if order:
                        await self.orders.change_status(
                            session,
                            order,
                            OrderStatus.REFUNDED.value,
                            note="استرداد تلقائي بعد عدم اكتمال باقة الأصدقاء",
                        )
                    if self.notifications is not None:
                        student = await session.get(User, member.user_id)
                        if student is not None:
                            await self.notifications.send_user(
                                session, student,
                                "تم إلغاء باقة الأصدقاء واسترداد المبلغ",
                                f"لم يكتمل العدد خلال 24 ساعة، وأُعيد {refund:,} د.ع إلى محفظتك.",
                                idempotency_key=f"friend-group:{group.id}:member:{member.id}:refund-notice",
                            )
                else:
                    if order:
                        await self.orders.refund_wallet_fee_if_unpaid(
                            session,
                            order,
                            reason="إعادة رسوم البوت بعد انتهاء باقة الأصدقاء غير المكتملة",
                        )
                        await self.orders.change_status(
                            session,
                            order,
                            OrderStatus.CANCELLED.value,
                            note="انتهت مهلة باقة الأصدقاء قبل اكتمال العدد",
                        )
                    member.status = FriendMemberStatus.CANCELLED.value
                    if self.notifications is not None:
                        student = await session.get(User, member.user_id)
                        if student is not None:
                            await self.notifications.send_user(
                                session, student,
                                "انتهت مهلة باقة الأصدقاء",
                                "لم يكتمل العدد خلال 24 ساعة، وأُلغي مقعدك وفُك حجز الحساب.",
                                idempotency_key=f"friend-group:{group.id}:member:{member.id}:expiry-notice",
                            )
            item = await session.get(InventoryItem, group.inventory_item_id)
            if item and item.status == InventoryStatus.RESERVED.value:
                item.status = InventoryStatus.AVAILABLE.value
                item.reserved_order_id = None
                item.reserved_at = None
            reservation = await session.scalar(
                select(PurchaseReservation).where(
                    PurchaseReservation.order_id == group.reservation_order_id
                )
            )
            if reservation:
                reservation.status = ReservationStatus.EXPIRED.value
                reservation.released_at = now
            group.status = FriendGroupStatus.EXPIRED.value
            group.cancelled_at = now
            group.escrow_service_iqd = 0
            group.escrow_bot_fee_iqd = 0
        await session.flush()
        return len(groups)
