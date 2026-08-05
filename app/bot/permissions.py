from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Order, User
from app.services.container import Services
from app.services.platform_access import EffectiveProviderStaff, effective_staff_view, resolve_provider_access


async def current_user(session: AsyncSession, services: Services, telegram_id: int) -> User | None:
    return await services.users.get(session, telegram_id)


async def provider_staff(
    session: AsyncSession,
    user_id: int,
    provider_id: int | None = None,
) -> EffectiveProviderStaff | None:
    """Legacy compatibility wrapper around the central Provider Access Resolver."""

    settings = session.info.get("campuspass_settings")
    if not isinstance(settings, Settings):
        return None
    user = await session.get(User, int(user_id))
    if user is None:
        return None
    context = await resolve_provider_access(
        session,
        settings,
        user.telegram_id,
        provider_id=provider_id,
        require_terms=True,
    )
    return await effective_staff_view(session, context) if context.allowed else None


async def can_access_order(
    session: AsyncSession,
    settings: Settings,
    services: Services,
    telegram_id: int,
    order: Order,
) -> bool:
    if settings.is_admin(telegram_id):
        return True
    user = await services.users.get(session, telegram_id)
    if not user:
        return False
    if order.user_id == user.id:
        return True
    context = await resolve_provider_access(
        session,
        settings,
        telegram_id,
        provider_id=order.provider_id,
        require_terms=True,
    )
    return context.allowed


async def can_manage_provider(
    session: AsyncSession,
    settings: Settings,
    services: Services,
    telegram_id: int,
    provider_id: int,
    permission: str | None = None,
) -> bool:
    context = await resolve_provider_access(
        session,
        settings,
        telegram_id,
        provider_id=provider_id,
        permission=permission,
        require_terms=True,
    )
    return context.allowed
