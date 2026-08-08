from __future__ import annotations

import io
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from PIL import Image

from app.db.models import Provider, ProviderStaff, ProviderStatus
from app.services.image_moderation import ImageModerationService
from app.services.platform_access import (
    PERMISSION_NAMES,
    ProviderAccessFailure,
    ProviderActorRole,
    ProviderActorSnapshot,
    ProviderMembershipContext,
    _CONTEXT_CACHE,
    _load_actor_context,
    _membership,
    invalidate_provider_access_cache,
    resolve_provider_access,
)
from app.services.templates import MessageTemplateService, validate_telegram_html


@dataclass
class FakeSettings:
    admins: frozenset[int] = frozenset()

    def is_admin(self, telegram_id: int) -> bool:
        return int(telegram_id) in self.admins


@pytest.fixture(autouse=True)
def clear_provider_cache() -> None:
    invalidate_provider_access_cache()
    yield
    invalidate_provider_access_cache()


def provider(provider_id: int = 10, *, active: bool = True, status: str = ProviderStatus.ACTIVE.value) -> Provider:
    return Provider(
        id=provider_id,
        name_ar=f"منصة {provider_id}",
        name_en="Platform",
        slug=f"provider-{provider_id}",
        status=status,
        is_active=active,
    )


def staff(
    row_id: int,
    provider_id: int,
    *,
    title: str = "staff",
    role: str = "STAFF",
    active: bool = True,
    offers: bool = False,
    branding: bool = False,
) -> ProviderStaff:
    return ProviderStaff(
        id=row_id,
        provider_id=provider_id,
        user_id=100,
        title=title,
        role=role,
        is_active=active,
        can_review_payments=False,
        can_manage_offers=offers,
        can_manage_inventory=False,
        can_manage_branding=branding,
        can_support=False,
        can_view_reports=False,
        can_view_finance=False,
        can_request_withdrawal=False,
        can_manage_payout_accounts=False,
        can_view_pii=False,
        can_export_data=False,
        can_manage_disputes=False,
        can_approve_refunds=False,
    )


def actor(*, terms: bool = True, active: bool = True, banned: bool = False) -> ProviderActorSnapshot:
    return ProviderActorSnapshot(
        user_id=100,
        telegram_id=777,
        telegram_username="owner",
        telegram_name="Owner",
        is_active=active,
        is_banned=banned,
        has_platform_access=terms,
    )


def membership(
    provider_id: int,
    *,
    role: ProviderActorRole = ProviderActorRole.STAFF,
    staff_active: bool = True,
    provider_active: bool = True,
    provider_status: str = ProviderStatus.ACTIVE.value,
    permissions: frozenset[str] = frozenset(),
) -> ProviderMembershipContext:
    return ProviderMembershipContext(
        staff_id=provider_id * 10,
        provider_id=provider_id,
        provider_name=f"منصة {provider_id}",
        provider_status=provider_status,
        provider_is_active=provider_active,
        staff_is_active=staff_active,
        role=role,
        effective_permissions=permissions,
    )


def test_owner_permissions_are_effective_even_when_legacy_booleans_are_false() -> None:
    row = staff(1, 10, title="owner", role="STAFF", offers=False, branding=False)
    resolved = _membership(row, provider())
    assert resolved.role is ProviderActorRole.OWNER
    assert resolved.effective_permissions == frozenset(PERMISSION_NAMES)
    assert resolved.allows("can_manage_offers")
    assert resolved.allows("can_manage_branding")


def test_staff_only_receives_explicit_permissions() -> None:
    row = staff(1, 10, offers=True, branding=False)
    resolved = _membership(row, provider())
    assert resolved.role is ProviderActorRole.STAFF
    assert resolved.allows("can_manage_offers")
    assert not resolved.allows("can_manage_branding")


@pytest.mark.asyncio
async def test_paused_staff_returns_precise_reason_for_legacy_provider_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    paused = membership(10, staff_active=False)

    async def load(_session: object, _telegram_id: int):
        return actor(), (paused,), None

    monkeypatch.setattr("app.services.platform_access._load_actor_context", load)
    context = await resolve_provider_access(
        object(), FakeSettings(), 777, provider_id=10, require_terms=False
    )
    assert context.failure_reason is ProviderAccessFailure.STAFF_PAUSED
    assert context.active_provider is paused
    assert context.selectable_memberships == ()


@pytest.mark.asyncio
async def test_paused_provider_and_stale_context_have_distinct_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    paused_provider = membership(
        10,
        provider_active=False,
        provider_status=ProviderStatus.SUSPENDED.value,
    )

    async def load(_session: object, _telegram_id: int):
        return actor(), (paused_provider,), None

    monkeypatch.setattr("app.services.platform_access._load_actor_context", load)
    paused = await resolve_provider_access(object(), FakeSettings(), 777, provider_id=10, require_terms=False)
    assert paused.failure_reason is ProviderAccessFailure.PROVIDER_PAUSED

    invalidate_provider_access_cache()
    stale = await resolve_provider_access(object(), FakeSettings(), 777, provider_id=999, require_terms=False)
    assert stale.failure_reason is ProviderAccessFailure.STALE_CONTEXT


@pytest.mark.asyncio
async def test_multiple_platforms_require_selection_then_resolve_selected_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    one = membership(10, role=ProviderActorRole.OWNER, permissions=frozenset(PERMISSION_NAMES))
    two = membership(20, permissions=frozenset({"can_view_reports"}))

    async def load_without_selection(_session: object, _telegram_id: int):
        return actor(), (one, two), None

    monkeypatch.setattr("app.services.platform_access._load_actor_context", load_without_selection)
    unresolved = await resolve_provider_access(object(), FakeSettings(), 777, require_terms=False)
    assert unresolved.failure_reason is ProviderAccessFailure.SELECTION_REQUIRED
    assert unresolved.active_provider is None

    invalidate_provider_access_cache()

    async def load_selected(_session: object, _telegram_id: int):
        return actor(), (one, two), 20

    monkeypatch.setattr("app.services.platform_access._load_actor_context", load_selected)
    selected = await resolve_provider_access(object(), FakeSettings(), 777, require_terms=False)
    assert selected.allowed
    assert selected.active_provider is two
    assert selected.role is ProviderActorRole.STAFF


@pytest.mark.asyncio
async def test_short_cache_removes_repeated_database_resolution_and_targeted_invalidation_reloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    member = membership(10, permissions=frozenset({"can_view_reports"}))

    async def load(_session: object, _telegram_id: int):
        nonlocal calls
        calls += 1
        return actor(), (member,), None

    monkeypatch.setattr("app.services.platform_access._load_actor_context", load)
    first = await resolve_provider_access(object(), FakeSettings(), 777, require_terms=False)
    second = await resolve_provider_access(object(), FakeSettings(), 777, require_terms=False)
    assert first.allowed and second.allowed
    assert calls == 1

    invalidate_provider_access_cache(provider_ids=(10,))
    third = await resolve_provider_access(object(), FakeSettings(), 777, require_terms=False)
    assert third.allowed
    assert calls == 2


@pytest.mark.asyncio
async def test_super_admin_has_effective_full_permissions_without_staff_row(monkeypatch: pytest.MonkeyPatch) -> None:
    admin_membership = membership(
        10,
        role=ProviderActorRole.SUPER_ADMIN,
        permissions=frozenset(PERMISSION_NAMES),
    )

    async def load(_session: object, _telegram_id: int):
        return actor(), (), None

    async def load_admin_providers(_session: object):
        return (admin_membership,)

    monkeypatch.setattr("app.services.platform_access._load_actor_context", load)
    monkeypatch.setattr("app.services.platform_access._super_admin_memberships", load_admin_providers)
    context = await resolve_provider_access(
        object(), FakeSettings(frozenset({777})), 777, provider_id=10, require_terms=False
    )
    assert context.allowed
    assert context.role is ProviderActorRole.SUPER_ADMIN
    assert context.effective_permissions == frozenset(PERMISSION_NAMES)



@pytest.mark.asyncio
async def test_actor_context_query_budget_is_two_for_one_platform_and_three_for_multiple() -> None:
    class ScalarRows:
        def __init__(self, values: list[object]) -> None:
            self.values = values

        def all(self) -> list[object]:
            return self.values

    class Session:
        def __init__(self, memberships: list[object], selected: int | None = None) -> None:
            self.calls: list[str] = []
            self.memberships = memberships
            self.selected = selected
            self.user_reads = 0

        async def scalar(self, _statement: object):
            self.calls.append("scalar")
            self.user_reads += 1
            if self.user_reads == 1:
                return SimpleNamespace(
                    id=100, telegram_id=777, telegram_username="u", telegram_name="U",
                    is_active=True, is_banned=False, has_platform_access=True,
                )
            return self.selected

        async def scalars(self, _statement: object):
            self.calls.append("scalars")
            return ScalarRows(self.memberships)

    one_row = staff(1, 10, offers=True)
    one_row.provider = provider(10)
    single = Session([one_row])
    _actor, memberships, selected = await _load_actor_context(single, 777)
    assert len(memberships) == 1 and selected is None
    assert len(single.calls) == 2

    two_row = staff(2, 20, offers=False)
    two_row.provider = provider(20)
    multiple = Session([one_row, two_row], selected=20)
    _actor, memberships, selected = await _load_actor_context(multiple, 777)
    assert len(memberships) == 2 and selected == 20
    assert len(multiple.calls) == 3

def test_start_template_html_validation_rejects_unsafe_links_and_unbalanced_tags() -> None:
    validate_telegram_html('<b>أهلاً</b> <a href="https://example.com">رابط</a>')
    with pytest.raises(ValueError, match="غير آمن"):
        validate_telegram_html('<a href="javascript:alert(1)">x</a>')
    with pytest.raises(ValueError, match="غير متطابق|غير مغلق"):
        validate_telegram_html("<b>broken")


@pytest.mark.asyncio
async def test_start_template_cache_avoids_query_per_start() -> None:
    class Session:
        def __init__(self) -> None:
            self.calls = 0

        async def scalar(self, _statement: object):
            self.calls += 1
            return SimpleNamespace(body="رسالة مخزنة")

    service = MessageTemplateService(cache_ttl_seconds=60)
    session = Session()
    assert await service.welcome_text(session, "fallback") == "رسالة مخزنة"
    assert await service.welcome_text(session, "fallback") == "رسالة مخزنة"
    assert session.calls == 1
    service.invalidate("start.welcome")
    assert await service.welcome_text(session, "fallback") == "رسالة مخزنة"
    assert session.calls == 2


def test_logo_validation_is_local_and_rejects_non_images() -> None:
    settings = SimpleNamespace()
    service = ImageModerationService(settings)
    buffer = io.BytesIO()
    Image.new("RGB", (256, 256)).save(buffer, format="PNG")
    assert service.validate_image(buffer.getvalue()) == ("PNG", 256, 256)
    with pytest.raises(ValueError, match="ليس صورة"):
        service.validate_image(b"not-an-image")
