from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from app.db.models import Base
from app.domain.friend_packages import (
    FriendPackageInvoice,
    FriendPackageProgress,
    hash_join_token,
    issue_join_token,
    service_share_for_index,
)

ROOT = Path(__file__).resolve().parents[1]


def test_friend_service_shares_never_lose_an_iqd() -> None:
    shares = [service_share_for_index(20_003, 4, index) for index in range(4)]
    assert shares == [5_001, 5_001, 5_001, 5_000]
    assert sum(shares) == 20_003


def test_every_friend_pays_the_full_bot_fee() -> None:
    invoice = FriendPackageInvoice(member_share_iqd=5_000, bot_fee_iqd=500)
    assert invoice.amount_due_iqd == 5_500
    with pytest.raises(ValueError):
        FriendPackageInvoice(member_share_iqd=-1, bot_fee_iqd=500)


def test_friend_progress_is_bounded_and_clear() -> None:
    progress = FriendPackageProgress(required_members=4, paid_members=3)
    assert progress.remaining_members == 1
    assert not progress.is_complete
    assert "المتبقي 1" in progress.status_text
    assert FriendPackageProgress(4, 4).is_complete
    with pytest.raises(ValueError):
        FriendPackageProgress(4, 5)


def test_friend_deep_link_tokens_are_random_and_only_hashes_are_stored() -> None:
    token_a, digest_a = issue_join_token()
    token_b, digest_b = issue_join_token()
    assert token_a != token_b
    assert digest_a != digest_b
    assert digest_a == hash_join_token(token_a)
    assert len(digest_a) == 64
    with pytest.raises(ValueError):
        hash_join_token("short")


def test_v11_3_models_build_cleanly_in_sqlite_schema_smoke_test() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert {
        "cp_friend_package_configs",
        "cp_friend_groups",
        "cp_friend_group_members",
        "cp_friend_escrow_entries",
        "cp_warranty_policies",
        "cp_warranty_claims",
        "cp_warranty_claim_events",
        "cp_warranty_replacements",
    }.issubset(tables)
    assert len(tables) >= 133


def test_warranty_cannot_be_closed_from_generic_provider_inbox() -> None:
    source = (ROOT / "app/bot/handlers/provider_operations.py").read_text(encoding="utf-8")
    assert "item.kind != ProviderInboxKind.WARRANTY.value" in source
    assert "تبقى مفتوحة حتى تأكيد الطالب" in source
    assert "p:wartext:" in source


def test_replacement_is_bound_only_after_student_confirmation() -> None:
    source = (ROOT / "app/services/warranties.py").read_text(encoding="utf-8")
    allocate = source.split("async def allocate_replacement", 1)[1].split(
        "async def provider_text_response", 1
    )[0]
    confirm = source.split("async def student_confirm_success", 1)[1].split(
        "async def student_reports_problem", 1
    )[0]
    assert "subscription.inventory_item_id = item.id" not in allocate
    assert "subscription.inventory_item_id = replacement.new_inventory_item_id" in confirm
    assert "with_for_update()" in source.split("async def open_claim", 1)[1].split(
        "async def allow_new_otp", 1
    )[0]


def test_warranty_otp_callback_reads_the_claim_id_not_the_action_name() -> None:
    source = (ROOT / "app/bot/handlers/subscriptions.py").read_text(encoding="utf-8")
    block = source.split("async def subscription_code_from_warranty", 1)[1].split(
        "@router", 1
    )[0]
    assert 'split(":")[3]' in block


def test_friend_expiry_precedes_generic_reservation_expiry() -> None:
    source = (ROOT / "app/tasks/scheduler.py").read_text(encoding="utf-8")
    friend_pos = source.index("friend_packages.expire_groups")
    generic_pos = source.index("orders.expire_reservations")
    assert friend_pos < generic_pos


def test_migration_contains_database_level_financial_guards() -> None:
    source = (ROOT / "alembic/versions/1130_friends_warranty.py").read_text(
        encoding="utf-8"
    )
    for token in (
        "ck_cp_friend_package_members",
        "ck_cp_friend_package_window",
        "ck_cp_friend_group_paid",
        "ck_cp_friend_member_payments",
        "uq_cp_warranty_active_subscription",
        "postgresql_where",
    ):
        assert token in source
