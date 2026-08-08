from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AuthorizationError, ResourceNotFoundError
from app.db.models import Dispute, Order, ProviderStaff, SupportTicket, User
from app.services.platform_access import EffectiveProviderStaff, effective_staff_view, resolve_provider_access


class TicketActorRole(StrEnum):
    USER = "user"
    PROVIDER = "provider"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class ActorContext:
    user: User
    staff: ProviderStaff | EffectiveProviderStaff | None = None
    ticket_role: TicketActorRole | None = None


class AuthorizationService:
    """Central tenant and role authorization.

    Callback ids and FSM data are never treated as permission. Every sensitive
    operation resolves the actor and resource again from the database.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def user_for_telegram(
        self, session: AsyncSession, telegram_id: int
    ) -> User | None:
        cache: dict[int, User | None] = session.info.setdefault(
            "campuspass_auth_users_by_telegram", {}
        )
        key = int(telegram_id)
        if key not in cache:
            cache[key] = await session.scalar(select(User).where(User.telegram_id == key))
        return cache[key]

    async def active_staff(
        self,
        session: AsyncSession,
        user_id: int,
        provider_id: int,
    ) -> EffectiveProviderStaff | None:
        """Legacy method delegated to the central typed provider resolver."""

        user = await session.get(User, int(user_id))
        if user is None:
            return None
        context = await resolve_provider_access(
            session,
            self.settings,
            user.telegram_id,
            provider_id=int(provider_id),
            require_terms=True,
        )
        return await effective_staff_view(session, context) if context.allowed else None

    async def require_order_access(
        self, session: AsyncSession, telegram_id: int, order_id: int
    ) -> tuple[User, Order]:
        user = await self.user_for_telegram(session, telegram_id)
        if not user:
            raise AuthorizationError("الحساب غير مسجل")
        order = await session.get(Order, order_id)
        if not order:
            raise ResourceNotFoundError("الطلب غير موجود")
        if self.settings.is_admin(telegram_id) or order.user_id == user.id:
            return user, order
        context = await resolve_provider_access(
            session,
            self.settings,
            telegram_id,
            provider_id=order.provider_id,
            require_terms=True,
        )
        if context.allowed:
            return user, order
        # Hide tenant resources rather than confirming that the id exists.
        raise ResourceNotFoundError("الطلب غير موجود")

    async def require_owned_order(
        self, session: AsyncSession, telegram_id: int, order_id: int
    ) -> tuple[User, Order]:
        user = await self.user_for_telegram(session, telegram_id)
        if not user:
            raise AuthorizationError("الحساب غير مسجل")
        order = await session.scalar(
            select(Order).where(Order.id == order_id, Order.user_id == user.id)
        )
        if not order:
            raise ResourceNotFoundError("الطلب غير موجود")
        return user, order

    async def ticket_actor(
        self, session: AsyncSession, telegram_id: int, ticket: SupportTicket
    ) -> ActorContext:
        user = await self.user_for_telegram(session, telegram_id)
        if not user:
            raise AuthorizationError("الحساب غير مسجل")
        if self.settings.is_admin(telegram_id):
            return ActorContext(user=user, ticket_role=TicketActorRole.ADMIN)
        if ticket.user_id == user.id:
            return ActorContext(user=user, ticket_role=TicketActorRole.USER)
        if ticket.provider_id is not None:
            context = await resolve_provider_access(
                session,
                self.settings,
                telegram_id,
                provider_id=ticket.provider_id,
                permission="can_support",
                require_terms=True,
            )
            staff = await effective_staff_view(session, context) if context.allowed else None
            if staff:
                return ActorContext(
                    user=user, staff=staff, ticket_role=TicketActorRole.PROVIDER
                )
        raise ResourceNotFoundError("التذكرة غير موجودة")

    async def require_provider_permission(
        self,
        session: AsyncSession,
        telegram_id: int,
        provider_id: int,
        permission: str,
    ) -> ActorContext:
        user = await self.user_for_telegram(session, telegram_id)
        if not user:
            raise AuthorizationError("الحساب غير مسجل")
        context = await resolve_provider_access(
            session,
            self.settings,
            telegram_id,
            provider_id=provider_id,
            permission=permission,
            require_terms=True,
        )
        if not context.allowed:
            raise AuthorizationError("ليس لديك صلاحية لتنفيذ هذه العملية")
        staff = await effective_staff_view(session, context)
        return ActorContext(user=user, staff=staff)


    async def dispute_actor(
        self, session: AsyncSession, telegram_id: int, dispute: Dispute
    ) -> ActorContext:
        user = await self.user_for_telegram(session, telegram_id)
        if not user:
            raise AuthorizationError("الحساب غير مسجل")
        if self.settings.is_admin(telegram_id):
            return ActorContext(user=user, ticket_role=TicketActorRole.ADMIN)
        if dispute.user_id == user.id:
            return ActorContext(user=user, ticket_role=TicketActorRole.USER)
        context = await resolve_provider_access(
            session,
            self.settings,
            telegram_id,
            provider_id=dispute.provider_id,
            permission="can_manage_disputes",
            require_terms=True,
        )
        staff = await effective_staff_view(session, context) if context.allowed else None
        if staff:
            return ActorContext(
                user=user, staff=staff, ticket_role=TicketActorRole.PROVIDER
            )
        raise ResourceNotFoundError("النزاع غير موجود")

    async def require_dispute_management(
        self, session: AsyncSession, telegram_id: int, provider_id: int
    ) -> ActorContext:
        return await self.require_provider_permission(
            session, telegram_id, provider_id, "can_manage_disputes"
        )

    async def require_refund_approval(
        self, session: AsyncSession, telegram_id: int, provider_id: int
    ) -> ActorContext:
        return await self.require_provider_permission(
            session, telegram_id, provider_id, "can_approve_refunds"
        )

    async def require_finance_access(
        self, session: AsyncSession, telegram_id: int, provider_id: int
    ) -> ActorContext:
        return await self.require_provider_permission(
            session, telegram_id, provider_id, "can_view_finance"
        )


    async def require_pii_access(
        self, session: AsyncSession, telegram_id: int, provider_id: int
    ) -> ActorContext:
        return await self.require_provider_permission(
            session, telegram_id, provider_id, "can_view_pii"
        )

    async def can_view_pii(
        self, session: AsyncSession, telegram_id: int, provider_id: int
    ) -> bool:
        try:
            await self.require_pii_access(session, telegram_id, provider_id)
            return True
        except AuthorizationError:
            return False

    async def require_withdrawal_permission(
        self, session: AsyncSession, telegram_id: int, provider_id: int
    ) -> ActorContext:
        if not self.settings.provider_withdrawals_ready:
            raise AuthorizationError(
                "طلبات السحب مفعلة لكنها تنتظر إعداد بوابة الدفع المركزية ونموذج marketplace"
            )
        return await self.require_provider_permission(
            session, telegram_id, provider_id, "can_request_withdrawal"
        )
