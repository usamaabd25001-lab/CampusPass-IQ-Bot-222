from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.time import as_utc
from app.core.utils import calculate_order_amounts, public_id
from app.db.models import (
    DeliveryType,
    InventoryItem,
    InventoryStatus,
    Offer,
    OfferStatus,
    Order,
    OrderEvent,
    OrderStatus,
    PaymentMethod,
    Provider,
    ProviderStatus,
    PurchaseReservation,
    ReservationStatus,
    User,
    ValidityType,
)

if TYPE_CHECKING:
    from app.services.student_subscriptions import StudentSubscriptionService
    from app.services.data_protection import DataProtectionService
    from app.services.subscriptions import SubscriptionService
    from app.services.wallets import WalletService
    from app.services.workflows import WorkflowService


class OrderService:
    def __init__(
        self,
        settings: Settings,
        subscriptions: SubscriptionService,
        student_subscriptions: StudentSubscriptionService,
        workflows: WorkflowService,
        data_protection: DataProtectionService,
        wallets: WalletService,
    ) -> None:
        self.settings = settings
        self.subscriptions = subscriptions
        self.student_subscriptions = student_subscriptions
        self.workflows = workflows
        self.data_protection = data_protection
        self.wallets = wallets

    async def validate_offer(self, session: AsyncSession, offer: Offer) -> Provider:
        provider = offer.provider or await session.get(Provider, offer.provider_id)
        if not provider or not provider.is_active or provider.status != ProviderStatus.ACTIVE.value:
            raise ValueError("المنصة غير متاحة حاليًا")
        now = datetime.now(UTC)
        if not offer.is_active or offer.status != OfferStatus.ACTIVE.value:
            raise ValueError("العرض غير متاح حاليًا")
        start_at = as_utc(offer.start_at)
        end_at = as_utc(offer.end_at)
        if start_at and start_at > now:
            raise ValueError("لم يبدأ هذا العرض بعد")
        if end_at and end_at < now:
            raise ValueError("انتهى هذا العرض")
        await self.student_subscriptions.validate_sale(session, offer)
        sales = await self.subscriptions.effective_entitlement(session, provider.id, "sales.accept")
        if not sales.enabled:
            raise ValueError("المنصة لا تستقبل طلبات جديدة حاليًا")
        return provider

    async def _assert_limits(self, session: AsyncSession, provider: Provider, offer: Offer) -> None:
        monthly_limit = await self.subscriptions.effective_entitlement(
            session, provider.id, "orders.monthly"
        )
        if monthly_limit.limit is not None and monthly_limit.limit >= 0:
            now = datetime.now(UTC)
            month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
            monthly_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(Order)
                    .where(
                        Order.provider_id == provider.id,
                        Order.created_at >= month_start,
                        Order.status.notin_(
                            [
                                OrderStatus.CANCELLED.value,
                                OrderStatus.PAYMENT_REJECTED.value,
                                OrderStatus.REFUNDED.value,
                            ]
                        ),
                    )
                )
                or 0
            )
            if monthly_count >= monthly_limit.limit:
                raise ValueError("وصلت المنصة إلى حد الطلبات الشهري في باقتها")
        if offer.daily_limit is not None:
            today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=UTC)
            daily_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(Order)
                    .where(
                        Order.offer_id == offer.id,
                        Order.created_at >= today_start,
                        Order.status.notin_(
                            [
                                OrderStatus.CANCELLED.value,
                                OrderStatus.PAYMENT_REJECTED.value,
                                OrderStatus.REFUNDED.value,
                            ]
                        ),
                    )
                )
                or 0
            )
            if daily_count >= offer.daily_limit:
                raise ValueError("وصل العرض إلى الحد اليومي")

    async def _reserve_inventory(
        self, session: AsyncSession, offer: Offer, order: Order
    ) -> PurchaseReservation | None:
        if offer.delivery_type not in {
            DeliveryType.INVENTORY_CODE.value,
            DeliveryType.INVENTORY_ACCOUNT.value,
        }:
            return None
        now = datetime.now(UTC)
        policy = await self.student_subscriptions.policy(session, offer)
        expiry_condition = or_(InventoryItem.expires_at.is_(None), InventoryItem.expires_at > now)
        if policy.validity_type == ValidityType.INVENTORY_END.value:
            minimum_end = now + timedelta(days=max(0, policy.min_remaining_days))
            expiry_condition = InventoryItem.expires_at >= minimum_end
        item = await session.scalar(
            select(InventoryItem)
            .where(
                InventoryItem.offer_id == offer.id,
                InventoryItem.status == InventoryStatus.AVAILABLE.value,
                expiry_condition,
            )
            .order_by(InventoryItem.expires_at.asc().nullslast(), InventoryItem.id.asc())
            .with_for_update(skip_locked=True)
        )
        if not item:
            raise ValueError("نفد مخزون هذا العرض حاليًا")
        item.status = InventoryStatus.RESERVED.value
        item.reserved_order_id = order.id
        item.reserved_at = now
        reservation = PurchaseReservation(
            order_id=order.id,
            offer_id=offer.id,
            inventory_item_id=item.id,
            status=ReservationStatus.HELD.value,
            held_at=now,
            expires_at=now + timedelta(minutes=self.settings.purchase_reservation_minutes),
        )
        session.add(reservation)
        await session.flush()
        return reservation

    async def create(
        self,
        session: AsyncSession,
        user: User,
        offer: Offer,
        activation_data: dict,
        idempotency_key: str | None = None,
    ) -> Order:
        normalized_key = (idempotency_key or "").strip()[:160] or None
        if normalized_key:
            existing = await session.scalar(
                select(Order).where(Order.idempotency_key == normalized_key)
            )
            if existing:
                if existing.user_id != user.id or existing.offer_id != offer.id:
                    raise PermissionError("مفتاح إنشاء الطلب مستخدم لعملية أخرى")
                return existing

        provider = await self.validate_offer(session, offer)
        provider = await session.scalar(
            select(Provider).where(Provider.id == provider.id).with_for_update()
        )
        if not provider:
            raise ValueError("المنصة غير متاحة حاليًا")
        if normalized_key:
            existing = await session.scalar(
                select(Order).where(Order.idempotency_key == normalized_key)
            )
            if existing:
                if existing.user_id != user.id or existing.offer_id != offer.id:
                    raise PermissionError("مفتاح إنشاء الطلب مستخدم لعملية أخرى")
                return existing

        methods = await self.payment_methods(session, provider.id)
        if not methods:
            raise ValueError(
                "لا توجد طريقة دفع مفعلة لهذه المنصة؛ لم يتم إنشاء الطلب أو حجز المخزون"
            )

        await self._assert_limits(session, provider, offer)
        management_percent = await self.subscriptions.effective_management_percent(
            session, provider
        )
        amounts = calculate_order_amounts(
            offer.price_iqd,
            offer.service_fee_iqd,
            management_percent,
        )
        order = Order(
            public_id=public_id("CP"),
            idempotency_key=normalized_key,
            user_id=user.id,
            provider_id=offer.provider_id,
            offer_id=offer.id,
            status=OrderStatus.WAITING_PAYMENT.value,
            activation_data=self.data_protection.mask_mapping(activation_data),
            **amounts,
        )
        session.add(order)
        await session.flush()
        wallet_balance_before = await self.wallets.balance(session, "user", user.id)
        wallet_fee_used = await self.wallets.apply_service_fee_only(
            session,
            user_id=user.id,
            order_id=order.id,
            service_fee_iqd=int(order.service_fee_iqd),
        )
        if wallet_fee_used:
            order.total_iqd = max(0, int(order.total_iqd) - wallet_fee_used)
        order.payment_snapshot = {
            **dict(order.payment_snapshot or {}),
            "wallet_balance_before_iqd": int(wallet_balance_before),
            "wallet_fee_deduction_iqd": int(wallet_fee_used),
            "cash_due_iqd": int(order.total_iqd),
            "wallet_rule": "full_bot_fee_only",
        }
        await self.data_protection.protect_order_activation(session, order, activation_data)
        reservation = await self._reserve_inventory(session, offer, order)
        inventory_item = (
            await session.get(InventoryItem, reservation.inventory_item_id)
            if reservation and reservation.inventory_item_id
            else None
        )
        await self.student_subscriptions.ensure_for_order(session, order, inventory_item)
        await self.workflows.ensure_order(session, order)
        session.add(
            OrderEvent(
                order_id=order.id,
                actor_user_id=user.id,
                old_status=OrderStatus.DRAFT.value,
                new_status=OrderStatus.WAITING_PAYMENT.value,
                note="تم إنشاء الطلب وحجز المورد مؤقتًا",
                metadata_json={"idempotency_key": normalized_key or ""},
            )
        )
        await session.flush()
        return order

    async def get(self, session: AsyncSession, order_id: int) -> Order | None:
        return await session.scalar(
            select(Order)
            .options(
                selectinload(Order.user).selectinload(User.profile),
                selectinload(Order.offer).selectinload(Offer.provider),
                selectinload(Order.payment_method),
            )
            .where(Order.id == order_id)
        )

    async def get_by_public_id(self, session: AsyncSession, public_id_value: str) -> Order | None:
        return await session.scalar(
            select(Order)
            .options(
                selectinload(Order.user).selectinload(User.profile),
                selectinload(Order.offer).selectinload(Offer.provider),
                selectinload(Order.provider),
                selectinload(Order.payment_method),
            )
            .where(Order.public_id == public_id_value)
        )

    async def user_orders(self, session: AsyncSession, user: User, limit: int = 20) -> list[Order]:
        items, _total = await self.user_orders_page(
            session, user, page=0, page_size=max(1, min(limit, 100))
        )
        return items

    async def user_orders_page(
        self,
        session: AsyncSession,
        user: User,
        *,
        page: int = 0,
        page_size: int = 8,
    ) -> tuple[list[Order], int]:
        page = max(0, int(page))
        page_size = max(1, min(int(page_size), 20))
        total = int(
            await session.scalar(
                select(func.count(Order.id)).where(Order.user_id == user.id)
            )
            or 0
        )
        rows = list(
            (
                await session.scalars(
                    select(Order)
                    .options(selectinload(Order.offer), selectinload(Order.provider))
                    .where(Order.user_id == user.id)
                    .order_by(Order.created_at.desc(), Order.id.desc())
                    .offset(page * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return rows, total

    async def acknowledge_delivery(
        self, session: AsyncSession, order: Order, user: User
    ) -> Order:
        locked = await session.scalar(
            select(Order).where(Order.id == order.id).with_for_update()
        )
        if not locked or locked.user_id != user.id:
            raise PermissionError("الطلب غير موجود")
        if locked.status not in {OrderStatus.DELIVERED.value, OrderStatus.COMPLETED.value}:
            raise ValueError("لا يمكن تأكيد الاستلام قبل تسليم بيانات الخدمة")
        if locked.delivery_acknowledged_at is None:
            locked.delivery_acknowledged_at = datetime.now(UTC)
            session.add(
                OrderEvent(
                    order_id=locked.id,
                    actor_user_id=user.id,
                    old_status=locked.status,
                    new_status=locked.status,
                    note="أكد المستخدم استلام بيانات الخدمة",
                    metadata_json={"event": "delivery_acknowledged"},
                )
            )
        await session.flush()
        return locked

    async def confirm_activation(
        self, session: AsyncSession, order: Order, user: User
    ) -> Order:
        locked = await session.scalar(
            select(Order).where(Order.id == order.id).with_for_update()
        )
        if not locked or locked.user_id != user.id:
            raise PermissionError("الطلب غير موجود")
        if locked.status == OrderStatus.COMPLETED.value:
            return locked
        if locked.status != OrderStatus.DELIVERED.value:
            raise ValueError("لا يمكن تأكيد التفعيل قبل تسليم بيانات الخدمة")
        if locked.delivery_acknowledged_at is None:
            raise ValueError("أكد استلام البيانات أولاً ثم جرّب التفعيل")
        if locked.activation_confirmed_at is None:
            locked.activation_confirmed_at = datetime.now(UTC)
            session.add(
                OrderEvent(
                    order_id=locked.id,
                    actor_user_id=user.id,
                    old_status=locked.status,
                    new_status=locked.status,
                    note="أكد المستخدم نجاح التفعيل",
                    metadata_json={"event": "activation_confirmed"},
                )
            )
        await session.flush()
        return locked

    async def payment_methods(self, session: AsyncSession, provider_id: int) -> list[PaymentMethod]:
        return list(
            (
                await session.scalars(
                    select(PaymentMethod)
                    .where(
                        PaymentMethod.is_active.is_(True),
                        or_(
                            PaymentMethod.provider_id == provider_id,
                            PaymentMethod.provider_id.is_(None),
                        ),
                    )
                    .order_by(PaymentMethod.provider_id.desc(), PaymentMethod.sort_order)
                )
            ).all()
        )

    async def set_payment_method(
        self, session: AsyncSession, order: Order, payment_method: PaymentMethod
    ) -> None:
        locked = await session.scalar(
            select(Order).where(Order.id == order.id).with_for_update()
        )
        if not locked:
            raise ValueError("الطلب غير موجود")
        if locked.status not in {
            OrderStatus.WAITING_PAYMENT.value,
            OrderStatus.PAYMENT_REJECTED.value,
        }:
            raise ValueError("لا يمكن تغيير طريقة الدفع بعد بدء مراجعة الدفع أو تأكيده")
        if not payment_method.is_active:
            raise ValueError("طريقة الدفع غير مفعلة")
        if payment_method.provider_id not in {None, locked.provider_id}:
            raise PermissionError("طريقة الدفع لا تخص هذه المنصة")
        locked.payment_method_id = payment_method.id
        locked.payment_snapshot = {
            "payment_method_id": payment_method.id,
            "name": payment_method.name,
            "method_type": payment_method.method_type,
            "recipient": payment_method.recipient,
            "instructions": payment_method.instructions,
            "selected_at": datetime.now(UTC).isoformat(),
        }
        await session.flush()

    async def reservation(self, session: AsyncSession, order_id: int) -> PurchaseReservation | None:
        return await session.scalar(
            select(PurchaseReservation).where(PurchaseReservation.order_id == order_id)
        )

    async def extend_reservation_for_review(
        self, session: AsyncSession, order: Order, hours: int = 24
    ) -> None:
        reservation = await self.reservation(session, order.id)
        if reservation and reservation.status == ReservationStatus.HELD.value:
            now = datetime.now(UTC)
            current_expiry = as_utc(reservation.expires_at) or now
            reservation.expires_at = max(
                current_expiry,
                now + timedelta(hours=max(1, hours)),
            )
            await session.flush()

    async def confirm_reservation(self, session: AsyncSession, order: Order) -> None:
        reservation = await session.scalar(
            select(PurchaseReservation)
            .where(PurchaseReservation.order_id == order.id)
            .with_for_update()
        )
        if not reservation:
            return
        if reservation.status == ReservationStatus.CONFIRMED.value:
            return
        now = datetime.now(UTC)
        expires_at = as_utc(reservation.expires_at)
        if reservation.status != ReservationStatus.HELD.value or (
            expires_at is not None and expires_at <= now
        ):
            reservation.status = ReservationStatus.EXPIRED.value
            reservation.released_at = now
            if reservation.inventory_item_id:
                item = await session.get(InventoryItem, reservation.inventory_item_id)
                if item and item.status == InventoryStatus.RESERVED.value:
                    item.status = InventoryStatus.AVAILABLE.value
                    item.reserved_order_id = None
                    item.reserved_at = None
            raise ValueError(
                "انتهى حجز المورد؛ يحتاج الطلب إلى مراجعة ولا يمكن تثبيته"
            )
        reservation.status = ReservationStatus.CONFIRMED.value
        reservation.confirmed_at = now
        await session.flush()

    async def release_reservation(
        self, session: AsyncSession, order: Order, reason: str = ""
    ) -> None:
        reservation = await self.reservation(session, order.id)
        if not reservation or reservation.status in {
            ReservationStatus.RELEASED.value,
            ReservationStatus.EXPIRED.value,
        }:
            return
        if reservation.inventory_item_id:
            item = await session.get(InventoryItem, reservation.inventory_item_id)
            if item and item.status == InventoryStatus.RESERVED.value:
                item.status = InventoryStatus.AVAILABLE.value
                item.reserved_order_id = None
                item.reserved_at = None
        reservation.status = ReservationStatus.RELEASED.value
        reservation.released_at = datetime.now(UTC)
        await session.flush()

    async def refund_wallet_fee_if_unpaid(
        self, session: AsyncSession, order: Order, *, reason: str
    ) -> int:
        snapshot = dict(order.payment_snapshot or {})
        used = max(0, int(snapshot.get("wallet_fee_deduction_iqd", 0) or 0))
        refunded = max(0, int(snapshot.get("wallet_fee_refunded_iqd", 0) or 0))
        amount = max(0, used - refunded)
        if amount == 0:
            return 0
        await self.wallets.refund_service_fee(
            session,
            user_id=order.user_id,
            order_id=order.id,
            amount_iqd=amount,
            reason=reason,
        )
        snapshot["wallet_fee_refunded_iqd"] = refunded + amount
        snapshot["wallet_fee_refund_reason"] = reason[:300]
        order.payment_snapshot = snapshot
        return amount

    async def expire_reservations(self, session: AsyncSession) -> int:
        now = datetime.now(UTC)
        reservations = list(
            (
                await session.scalars(
                    select(PurchaseReservation).where(
                        PurchaseReservation.status == ReservationStatus.HELD.value,
                        PurchaseReservation.expires_at <= now,
                    )
                )
            ).all()
        )
        for reservation in reservations:
            order = await session.get(Order, reservation.order_id)
            if order and order.status in {
                OrderStatus.WAITING_PAYMENT.value,
                OrderStatus.PAYMENT_REJECTED.value,
            }:
                await self.refund_wallet_fee_if_unpaid(
                    session, order, reason="إعادة رسوم البوت بعد انتهاء مهلة الدفع"
                )
                await self.change_status(
                    session,
                    order,
                    OrderStatus.CANCELLED.value,
                    note="انتهت مهلة حجز المخزون قبل الدفع",
                )
            if reservation.inventory_item_id:
                item = await session.get(InventoryItem, reservation.inventory_item_id)
                if item and item.status == InventoryStatus.RESERVED.value:
                    item.status = InventoryStatus.AVAILABLE.value
                    item.reserved_order_id = None
                    item.reserved_at = None
            reservation.status = ReservationStatus.EXPIRED.value
            reservation.released_at = now
        await session.flush()
        return len(reservations)

    async def change_status(
        self,
        session: AsyncSession,
        order: Order,
        new_status: str,
        actor_user_id: int | None = None,
        note: str = "",
        metadata: dict | None = None,
    ) -> None:
        old = order.status
        if old == new_status:
            return
        await self.workflows.assert_transition(session, order, new_status)
        order.status = new_status
        await self.workflows.record_transition(session, order, new_status)
        session.add(
            OrderEvent(
                order_id=order.id,
                actor_user_id=actor_user_id,
                old_status=old,
                new_status=new_status,
                note=note,
                metadata_json=metadata or {},
            )
        )
        await session.flush()
