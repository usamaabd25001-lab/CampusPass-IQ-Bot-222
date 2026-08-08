from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.db.models import (
    Provider,
    ProviderStaff,
    ProviderStatus,
    ProviderTermsAcceptance,
    SystemSetting,
    User,
)

logger = logging.getLogger(__name__)


class ProviderActorRole(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    OWNER = "OWNER"
    MANAGER = "MANAGER"
    STAFF = "STAFF"


class ProviderAccessFailure(StrEnum):
    NONE = "none"
    USER_MISSING = "user_missing"
    USER_INACTIVE = "user_inactive"
    USER_BANNED = "user_banned"
    MEMBERSHIP_MISSING = "membership_missing"
    STAFF_PAUSED = "staff_paused"
    PROVIDER_PAUSED = "provider_paused"
    TERMS_REQUIRED = "terms_required"
    SELECTION_REQUIRED = "selection_required"
    STALE_CONTEXT = "stale_context"
    PERMISSION_DENIED = "permission_denied"


PERMISSION_NAMES: tuple[str, ...] = (
    "can_review_payments",
    "can_manage_offers",
    "can_manage_inventory",
    "can_manage_branding",
    "can_support",
    "can_view_reports",
    "can_view_finance",
    "can_request_withdrawal",
    "can_manage_payout_accounts",
    "can_view_pii",
    "can_export_data",
    "can_manage_disputes",
    "can_approve_refunds",
)

_OWNER_TITLES = {"owner", "مالك", "platform_owner", "provider_owner"}
_MANAGER_TITLES = {"manager", "مدير", "admin", "administrator"}
_ACTIVE_PROVIDER_STATUSES = {ProviderStatus.ACTIVE.value}


@dataclass(frozen=True, slots=True)
class ProviderMembershipContext:
    staff_id: int | None
    provider_id: int
    provider_name: str
    provider_status: str
    provider_is_active: bool
    staff_is_active: bool
    role: ProviderActorRole
    effective_permissions: frozenset[str]

    @property
    def provider_available(self) -> bool:
        return self.provider_is_active and self.provider_status in _ACTIVE_PROVIDER_STATUSES

    def allows(self, permission: str | None) -> bool:
        return permission is None or permission in self.effective_permissions


@dataclass(frozen=True, slots=True)
class ProviderActorSnapshot:
    user_id: int
    telegram_id: int
    telegram_username: str | None
    telegram_name: str
    is_active: bool
    is_banned: bool
    has_platform_access: bool


@dataclass(frozen=True, slots=True)
class ProviderAccessContext:
    actor: ProviderActorSnapshot | None
    is_super_admin: bool
    memberships: tuple[ProviderMembershipContext, ...]
    active_provider: ProviderMembershipContext | None
    role: ProviderActorRole | None
    effective_permissions: frozenset[str]
    provider_status: str | None
    terms_access_state: str
    failure_reason: ProviderAccessFailure
    requested_provider_id: int | None = None

    @property
    def allowed(self) -> bool:
        return self.failure_reason is ProviderAccessFailure.NONE and self.active_provider is not None

    def allows(self, permission: str | None) -> bool:
        return self.allowed and (permission is None or permission in self.effective_permissions)

    @property
    def selectable_memberships(self) -> tuple[ProviderMembershipContext, ...]:
        """Memberships safe to expose in the provider picker.

        Inactive staff rows remain in ``memberships`` so stale callbacks can return
        the precise ``STAFF_PAUSED`` reason, but they are never offered as a new
        navigation target. Super administrators may inspect paused providers.
        """

        if self.is_super_admin:
            return self.memberships
        return tuple(item for item in self.memberships if item.staff_is_active)


@dataclass(frozen=True, slots=True)
class EffectiveProviderStaff:
    """Read-only compatibility view used by legacy handlers.

    Existing handlers expect ``staff.provider_id``, ``staff.provider`` and boolean
    permission attributes. OWNER/SUPER_ADMIN permissions are calculated here and
    never written back into historic boolean columns.
    """

    row: ProviderStaff | None
    provider: Provider
    role: ProviderActorRole
    effective_permissions: frozenset[str]

    @property
    def id(self) -> int | None:
        return self.row.id if self.row is not None else None

    @property
    def provider_id(self) -> int:
        return int(self.provider.id)

    @property
    def user_id(self) -> int | None:
        return self.row.user_id if self.row is not None else None

    @property
    def title(self) -> str:
        return self.row.title if self.row is not None else self.role.value.lower()

    @property
    def is_active(self) -> bool:
        return True if self.row is None else bool(self.row.is_active)

    def __getattr__(self, name: str) -> Any:
        if name in PERMISSION_NAMES:
            return name in self.effective_permissions
        if self.row is not None:
            return getattr(self.row, name)
        raise AttributeError(name)


# Backward-compatible hot-path set used by existing menu code/tests.
AUTHORIZED_PLATFORMS: set[str] = set()
_AUTHORIZED_PLATFORMS_READY = False
_CACHE_LOCK = asyncio.Lock()
_CACHE_TTL_SECONDS = 8.0
_CONTEXT_CACHE: dict[str, tuple[float, ProviderActorSnapshot, tuple[ProviderMembershipContext, ...], int | None]] = {}


def normalize_telegram_user_id(user_id: int | str | object) -> str | None:
    raw = str(user_id).strip()
    if not raw or not raw.lstrip("-").isdigit():
        return None
    try:
        return str(int(raw))
    except (TypeError, ValueError, OverflowError):
        return None


def _role_for_title(title: str | None) -> ProviderActorRole:
    normalized = (title or "").strip().lower()
    if normalized in _OWNER_TITLES:
        return ProviderActorRole.OWNER
    if normalized in _MANAGER_TITLES:
        return ProviderActorRole.MANAGER
    return ProviderActorRole.STAFF


def _effective_permissions(staff: ProviderStaff | None, role: ProviderActorRole) -> frozenset[str]:
    if role in {ProviderActorRole.SUPER_ADMIN, ProviderActorRole.OWNER}:
        return frozenset(PERMISSION_NAMES)
    if staff is None:
        return frozenset()
    return frozenset(name for name in PERMISSION_NAMES if bool(getattr(staff, name, False)))


def _snapshot(user: User) -> ProviderActorSnapshot:
    return ProviderActorSnapshot(
        user_id=int(user.id),
        telegram_id=int(user.telegram_id),
        telegram_username=user.telegram_username,
        telegram_name=user.telegram_name or "",
        is_active=bool(user.is_active),
        is_banned=bool(user.is_banned),
        has_platform_access=bool(user.has_platform_access),
    )


def _membership(staff: ProviderStaff, provider: Provider) -> ProviderMembershipContext:
    stored_role = str(getattr(staff, "role", "") or "").strip().upper()
    title_role = _role_for_title(staff.title)
    if stored_role == ProviderActorRole.OWNER.value or title_role is ProviderActorRole.OWNER:
        role = ProviderActorRole.OWNER
    elif stored_role == ProviderActorRole.MANAGER.value or title_role is ProviderActorRole.MANAGER:
        role = ProviderActorRole.MANAGER
    else:
        role = ProviderActorRole.STAFF
    return ProviderMembershipContext(
        staff_id=int(staff.id),
        provider_id=int(provider.id),
        provider_name=provider.name_ar,
        provider_status=provider.status,
        provider_is_active=bool(provider.is_active),
        staff_is_active=bool(staff.is_active),
        role=role,
        effective_permissions=_effective_permissions(staff, role),
    )


def _replace_authorized_platforms(values: Iterable[int | str | object]) -> None:
    normalized = {
        value
        for item in values
        if (value := normalize_telegram_user_id(item)) is not None
    }
    AUTHORIZED_PLATFORMS.clear()
    AUTHORIZED_PLATFORMS.update(normalized)


async def _active_selection_for_user(session: AsyncSession, user_id: int) -> int | None:
    raw = await session.scalar(
        select(SystemSetting.value).where(SystemSetting.key == f"provider.active.{int(user_id)}")
    )
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


async def _load_actor_context(
    session: AsyncSession,
    telegram_id: int,
) -> tuple[ProviderActorSnapshot | None, tuple[ProviderMembershipContext, ...], int | None]:
    user = await session.scalar(select(User).where(User.telegram_id == int(telegram_id)))
    if user is None:
        return None, (), None
    rows = list(
        (
            await session.scalars(
                select(ProviderStaff)
                .options(selectinload(ProviderStaff.provider))
                .where(ProviderStaff.user_id == user.id)
                .order_by(ProviderStaff.id)
            )
        ).all()
    )
    memberships = tuple(
        _membership(row, row.provider)
        for row in rows
        if row.provider is not None
    )
    selected = await _active_selection_for_user(session, int(user.id)) if len(memberships) > 1 else None
    return _snapshot(user), memberships, selected


async def refresh_authorized_platforms(session: AsyncSession) -> frozenset[str]:
    """Warm the compatibility set and typed cache from the database once at startup."""

    global _AUTHORIZED_PLATFORMS_READY
    async with _CACHE_LOCK:
        rows = list(
            (
                await session.execute(
                    select(User, ProviderStaff, Provider)
                    .join(ProviderStaff, ProviderStaff.user_id == User.id)
                    .join(Provider, Provider.id == ProviderStaff.provider_id)
                    .where(User.is_active.is_(True), User.is_banned.is_(False))
                    .order_by(User.id, ProviderStaff.id)
                )
            ).all()
        )
        grouped: dict[int, tuple[User, list[ProviderMembershipContext]]] = {}
        for user, staff, provider in rows:
            bucket = grouped.setdefault(int(user.telegram_id), (user, []))
            bucket[1].append(_membership(staff, provider))
        selected_rows = list(
            (
                await session.execute(
                    select(SystemSetting.key, SystemSetting.value).where(
                        SystemSetting.key.like("provider.active.%")
                    )
                )
            ).all()
        )
        selections: dict[int, int] = {}
        for key, value in selected_rows:
            try:
                selections[int(str(key).rsplit(".", 1)[1])] = int(value)
            except (TypeError, ValueError, IndexError):
                continue
        now = time.monotonic()
        _CONTEXT_CACHE.clear()
        authorized: list[int] = []
        for telegram_id, (user, memberships) in grouped.items():
            if any(m.staff_is_active for m in memberships):
                authorized.append(telegram_id)
            _CONTEXT_CACHE[str(telegram_id)] = (
                now + _CACHE_TTL_SECONDS,
                _snapshot(user),
                tuple(memberships),
                selections.get(int(user.id)),
            )
        _replace_authorized_platforms(authorized)
        _AUTHORIZED_PLATFORMS_READY = True
        logger.info(
            "Provider access cache warmed actors=%s authorized=%s",
            len(_CONTEXT_CACHE),
            len(AUTHORIZED_PLATFORMS),
        )
        return frozenset(AUTHORIZED_PLATFORMS)


def invalidate_provider_access_cache(
    *,
    telegram_ids: Iterable[int | str | object] = (),
    provider_ids: Iterable[int] = (),
) -> None:
    telegram_ids = tuple(telegram_ids)
    provider_ids = tuple(provider_ids)
    if not telegram_ids and not provider_ids:
        _CONTEXT_CACHE.clear()
        AUTHORIZED_PLATFORMS.clear()
        return
    normalized_ids = {
        item for value in telegram_ids if (item := normalize_telegram_user_id(value)) is not None
    }
    if provider_ids:
        providers = {int(value) for value in provider_ids}
        normalized_ids.update(
            telegram_id
            for telegram_id, (_expiry, _actor, memberships, _selected) in _CONTEXT_CACHE.items()
            if any(m.provider_id in providers for m in memberships)
        )
    for telegram_id in normalized_ids:
        _CONTEXT_CACHE.pop(telegram_id, None)
        AUTHORIZED_PLATFORMS.discard(telegram_id)


def mark_platform_authorization_dirty(
    session: AsyncSession,
    *,
    telegram_id: int | str | object | None = None,
    provider_id: int | None = None,
) -> None:
    dirty = session.info.setdefault(
        "campuspass_platform_auth_dirty",
        {"telegram_ids": set(), "provider_ids": set()},
    )
    if telegram_id is not None:
        normalized = normalize_telegram_user_id(telegram_id)
        if normalized is not None:
            dirty["telegram_ids"].add(normalized)
    if provider_id is not None:
        dirty["provider_ids"].add(int(provider_id))


def authorize_platform_user(user_id: int | str | object) -> bool:
    normalized = normalize_telegram_user_id(user_id)
    if normalized is None:
        return False
    AUTHORIZED_PLATFORMS.add(normalized)
    _CONTEXT_CACHE.pop(normalized, None)
    return True


def deauthorize_platform_user(user_id: int | str | object) -> bool:
    normalized = normalize_telegram_user_id(user_id)
    if normalized is None:
        return False
    existed = normalized in AUTHORIZED_PLATFORMS
    AUTHORIZED_PLATFORMS.discard(normalized)
    _CONTEXT_CACHE.pop(normalized, None)
    return existed


async def _super_admin_memberships(session: AsyncSession) -> tuple[ProviderMembershipContext, ...]:
    providers = list(
        (
            await session.scalars(
                select(Provider).order_by(Provider.name_ar, Provider.id)
            )
        ).all()
    )
    return tuple(
        ProviderMembershipContext(
            staff_id=None,
            provider_id=int(provider.id),
            provider_name=provider.name_ar,
            provider_status=provider.status,
            provider_is_active=bool(provider.is_active),
            staff_is_active=True,
            role=ProviderActorRole.SUPER_ADMIN,
            effective_permissions=frozenset(PERMISSION_NAMES),
        )
        for provider in providers
    )


async def resolve_provider_access(
    session: AsyncSession,
    settings: Settings,
    user_id: int | str | object,
    *,
    provider_id: int | None = None,
    permission: str | None = None,
    require_terms: bool = True,
    allow_paused_provider: bool = False,
) -> ProviderAccessContext:
    normalized = normalize_telegram_user_id(user_id)
    if normalized is None:
        return ProviderAccessContext(
            actor=None,
            is_super_admin=False,
            memberships=(),
            active_provider=None,
            role=None,
            effective_permissions=frozenset(),
            provider_status=None,
            terms_access_state="unknown",
            failure_reason=ProviderAccessFailure.USER_MISSING,
            requested_provider_id=provider_id,
        )
    telegram_id = int(normalized)
    is_super_admin = bool(settings.is_admin(telegram_id))
    cached = _CONTEXT_CACHE.get(normalized)
    if cached is None or cached[0] <= time.monotonic():
        actor, memberships, selected_id = await _load_actor_context(session, telegram_id)
        if actor is not None:
            _CONTEXT_CACHE[normalized] = (
                time.monotonic() + _CACHE_TTL_SECONDS,
                actor,
                memberships,
                selected_id,
            )
    else:
        _expiry, actor, memberships, selected_id = cached

    # Super administrators can inspect any provider without synthetic staff rows.
    # The database remains the source of truth; this list is cached only through
    # the same short-lived actor context.
    if (
        is_super_admin
        and actor is not None
        and (not memberships or any(item.role is not ProviderActorRole.SUPER_ADMIN for item in memberships))
    ):
        memberships = await _super_admin_memberships(session)
        cached_selected = await _active_selection_for_user(session, actor.user_id) if len(memberships) > 1 else None
        selected_id = cached_selected
        _CONTEXT_CACHE[normalized] = (
            time.monotonic() + _CACHE_TTL_SECONDS,
            actor,
            memberships,
            selected_id,
        )

    if actor is None:
        return ProviderAccessContext(
            actor=None,
            is_super_admin=is_super_admin,
            memberships=(),
            active_provider=None,
            role=ProviderActorRole.SUPER_ADMIN if is_super_admin else None,
            effective_permissions=frozenset(PERMISSION_NAMES) if is_super_admin else frozenset(),
            provider_status=None,
            terms_access_state="unknown",
            failure_reason=ProviderAccessFailure.USER_MISSING,
            requested_provider_id=provider_id,
        )
    if not actor.is_active:
        failure = ProviderAccessFailure.USER_INACTIVE
    elif actor.is_banned:
        failure = ProviderAccessFailure.USER_BANNED
    else:
        failure = ProviderAccessFailure.NONE

    selectable_memberships = memberships if is_super_admin else tuple(
        item for item in memberships if item.staff_is_active
    )
    active: ProviderMembershipContext | None = None
    if provider_id is not None:
        # Resolve against every stored membership first. This preserves an exact
        # STAFF_PAUSED response for an old callback instead of misreporting that
        # the membership disappeared.
        active = next((m for m in memberships if m.provider_id == int(provider_id)), None)
        if active is None and failure is ProviderAccessFailure.NONE:
            failure = (
                ProviderAccessFailure.STALE_CONTEXT
                if memberships
                else ProviderAccessFailure.MEMBERSHIP_MISSING
            )
    elif len(selectable_memberships) == 1:
        active = selectable_memberships[0]
    elif len(selectable_memberships) > 1:
        active = next((m for m in selectable_memberships if m.provider_id == selected_id), None)
        if active is None and failure is ProviderAccessFailure.NONE:
            failure = ProviderAccessFailure.SELECTION_REQUIRED
    elif len(memberships) == 1:
        active = memberships[0]
    elif memberships and failure is ProviderAccessFailure.NONE:
        failure = ProviderAccessFailure.STAFF_PAUSED
    elif failure is ProviderAccessFailure.NONE:
        failure = ProviderAccessFailure.MEMBERSHIP_MISSING

    role = ProviderActorRole.SUPER_ADMIN if is_super_admin else (active.role if active else None)
    effective = frozenset(PERMISSION_NAMES) if is_super_admin else (
        active.effective_permissions if active else frozenset()
    )
    provider_terms_accepted = bool(is_super_admin)
    if active is not None and actor is not None and not is_super_admin:
        provider_terms_accepted = bool(
            await session.scalar(
                select(ProviderTermsAcceptance.id).where(
                    ProviderTermsAcceptance.provider_id == active.provider_id,
                    ProviderTermsAcceptance.user_id == actor.user_id,
                    ProviderTermsAcceptance.terms_version == settings.provider_terms_version,
                    ProviderTermsAcceptance.revoked_at.is_(None),
                )
            )
        )
    if active is not None and failure is ProviderAccessFailure.NONE:
        if not active.staff_is_active and not is_super_admin:
            failure = ProviderAccessFailure.STAFF_PAUSED
        elif not active.provider_available and not allow_paused_provider:
            failure = ProviderAccessFailure.PROVIDER_PAUSED
        elif require_terms and not provider_terms_accepted:
            failure = ProviderAccessFailure.TERMS_REQUIRED
        elif permission and permission not in effective:
            failure = ProviderAccessFailure.PERMISSION_DENIED

    if failure is ProviderAccessFailure.NONE:
        AUTHORIZED_PLATFORMS.add(normalized)
    return ProviderAccessContext(
        actor=actor,
        is_super_admin=is_super_admin,
        memberships=memberships,
        active_provider=active,
        role=role,
        effective_permissions=effective,
        provider_status=active.provider_status if active else None,
        terms_access_state="accepted" if provider_terms_accepted else "required",
        failure_reason=failure,
        requested_provider_id=provider_id,
    )


async def effective_staff_view(
    session: AsyncSession,
    context: ProviderAccessContext,
) -> EffectiveProviderStaff | None:
    membership = context.active_provider
    if membership is None:
        return None
    row: ProviderStaff | None
    provider: Provider | None
    if membership.staff_id is None:
        row = None
        provider = await session.get(Provider, membership.provider_id)
    else:
        joined = (
            await session.execute(
                select(ProviderStaff, Provider)
                .join(Provider, Provider.id == ProviderStaff.provider_id)
                .where(
                    ProviderStaff.id == membership.staff_id,
                    Provider.id == membership.provider_id,
                )
            )
        ).first()
        if joined is None:
            return None
        row, provider = joined
    if provider is None:
        return None
    return EffectiveProviderStaff(
        row=row,
        provider=provider,
        role=context.role or membership.role,
        effective_permissions=context.effective_permissions,
    )


async def set_active_provider_selection(
    session: AsyncSession,
    *,
    user_id: int,
    telegram_id: int,
    provider_id: int,
) -> None:
    key = f"provider.active.{int(user_id)}"
    setting = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if setting is None:
        session.add(SystemSetting(key=key, value=str(int(provider_id)), updated_by_user_id=user_id))
    else:
        setting.value = str(int(provider_id))
        setting.updated_by_user_id = user_id
    await session.flush()
    invalidate_provider_access_cache(telegram_ids=(telegram_id,))


async def is_platform_authorized(
    session: AsyncSession,
    user_id: int | str | object,
    settings: Settings | None = None,
) -> bool:
    """Compatibility gate.

    New code should use :func:`resolve_provider_access`. Without settings this
    answers only whether an active membership exists; it intentionally does not
    grant super-admin access because ADMIN_IDS is unavailable.
    """

    normalized = normalize_telegram_user_id(user_id)
    if normalized is None:
        return False
    if settings is not None:
        context = await resolve_provider_access(
            session,
            settings,
            normalized,
            require_terms=False,
            allow_paused_provider=False,
        )
        return context.failure_reason in {
            ProviderAccessFailure.NONE,
            ProviderAccessFailure.TERMS_REQUIRED,
            ProviderAccessFailure.SELECTION_REQUIRED,
        }
    if normalized in AUTHORIZED_PLATFORMS:
        return True
    actor, memberships, selected = await _load_actor_context(session, int(normalized))
    if actor is None:
        return False
    _CONTEXT_CACHE[normalized] = (
        time.monotonic() + _CACHE_TTL_SECONDS,
        actor,
        memberships,
        selected,
    )
    allowed = actor.is_active and not actor.is_banned and any(
        m.staff_is_active and m.provider_available for m in memberships
    )
    if allowed:
        AUTHORIZED_PLATFORMS.add(normalized)
    return allowed


def access_failure_message(context: ProviderAccessContext) -> str:
    mapping = {
        ProviderAccessFailure.USER_MISSING: "تعذر استعادة حسابك تلقائيًا.",
        ProviderAccessFailure.USER_INACTIVE: "حساب المستخدم غير فعّال.",
        ProviderAccessFailure.USER_BANNED: "حساب المستخدم موقوف.",
        ProviderAccessFailure.MEMBERSHIP_MISSING: "لا توجد عضوية منصة مرتبطة بحسابك.",
        ProviderAccessFailure.STAFF_PAUSED: "عضوية الموظف موقوفة في هذه المنصة.",
        ProviderAccessFailure.PROVIDER_PAUSED: "المنصة متوقفة أو غير مفعّلة حاليًا.",
        ProviderAccessFailure.TERMS_REQUIRED: "يلزم قبول شروط لوحة المنصة أولًا.",
        ProviderAccessFailure.SELECTION_REQUIRED: "اختر المنصة التي تريد إدارتها.",
        ProviderAccessFailure.STALE_CONTEXT: "هذا الزر يعود إلى منصة قديمة أو غير مرتبطة بحسابك.",
        ProviderAccessFailure.PERMISSION_DENIED: "لا تملك الصلاحية المطلوبة داخل هذه المنصة.",
        ProviderAccessFailure.NONE: "",
    }
    return mapping[context.failure_reason]
