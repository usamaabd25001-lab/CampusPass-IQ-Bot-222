from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order, OrderStatus, SupportTicket, User
from app.services.notifications import NotificationService
from app.services.orders import OrderService
from app.services.student_subscriptions import StudentSubscriptionService
from app.services.support import SupportService


class DirectSupportService:
    """Provider-facing student support without the legacy dispute workflow."""

    def __init__(
        self,
        orders: OrderService,
        subscriptions: StudentSubscriptionService,
        support: SupportService,
        notifications: NotificationService,
    ) -> None:
        self.orders = orders
        self.subscriptions = subscriptions
        self.support = support
        self.notifications = notifications

    async def open(
        self,
        session: AsyncSession,
        user: User,
        order: Order,
        details: str,
    ) -> tuple[SupportTicket, list[int]]:
        clean = " ".join((details or "").split())
        if len(clean) < 5:
            raise ValueError("اكتب تفاصيل المشكلة بشكل أوضح")
        clean = clean[:4000]

        ticket = await self.support.create_ticket(
            session,
            user,
            subject=f"دعم مباشر للطلب {order.public_id}",
            message=clean,
            category="direct_provider_support",
            provider_id=order.provider_id,
            order_id=order.id,
        )
        if order.status not in {
            OrderStatus.COMPLETED.value,
            OrderStatus.REFUNDED.value,
            OrderStatus.CANCELLED.value,
        }:
            await self.orders.change_status(
                session,
                order,
                OrderStatus.NEEDS_SUPPORT.value,
                actor_user_id=user.id,
                note=f"تم فتح دعم مباشر {ticket.public_id}",
            )
            await self.subscriptions.mark_needs_support(
                session,
                order,
                f"direct support {ticket.public_id}",
            )

        targets = await self.notifications.provider_support_ids(session, order.provider_id)
        await session.flush()
        return ticket, targets
