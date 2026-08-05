from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from app.db.models import Base
from app.domain.owner_commerce import (
    HybridAllocation,
    billing_decision,
    normalize_audience_rule,
    reward_campaign_capacity,
    validate_hybrid_allocations,
)

ROOT = Path(__file__).resolve().parents[1]


def test_targeting_rules_are_normalized_and_bounded() -> None:
    assert normalize_audience_rule({"type": "college", "value": "طب", "limit": 500}) == {
        "type": "college",
        "value": "طب",
        "limit": 500,
    }
    assert normalize_audience_rule({"type": "provider_buyers", "value": "7"})["value"] == 7
    with pytest.raises(ValueError):
        normalize_audience_rule({"type": "unknown"})
    with pytest.raises(ValueError):
        normalize_audience_rule({"type": "college"})


def test_billing_decision_supports_only_weekly_or_monthly() -> None:
    now = datetime(2026, 8, 4, tzinfo=UTC)
    decision = billing_decision(
        next_invoice_at=now - timedelta(minutes=1), cycle_days=7, due_hours=48, now=now
    )
    assert decision.should_issue
    assert decision.due_at == now + timedelta(hours=48)
    assert decision.next_invoice_at == now + timedelta(days=7)
    with pytest.raises(ValueError):
        billing_decision(next_invoice_at=now, cycle_days=14, due_hours=48, now=now)


def test_hybrid_bundle_must_balance_to_the_last_iqd() -> None:
    allocations = [
        HybridAllocation(provider_id=1, offer_id=10, amount_iqd=13_000),
        HybridAllocation(provider_id=2, offer_id=20, amount_iqd=8_000),
    ]
    validate_hybrid_allocations(
        bundle_price_iqd=22_000, bot_fee_iqd=1_000, allocations=allocations
    )
    with pytest.raises(ValueError):
        validate_hybrid_allocations(
            bundle_price_iqd=21_999, bot_fee_iqd=1_000, allocations=allocations
        )


def test_reward_capacity_never_exceeds_budget_or_requested_count() -> None:
    assert reward_campaign_capacity(
        budget_iqd=25_000, reward_iqd=250, requested_count=100
    ) == 100
    assert reward_campaign_capacity(
        budget_iqd=10_000, reward_iqd=250, requested_count=100
    ) == 40
    with pytest.raises(ValueError):
        reward_campaign_capacity(budget_iqd=100, reward_iqd=250, requested_count=1)


def test_v11_4_schema_builds_with_commercial_guards() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert {
        "cp_financial_proof_registry",
        "cp_provider_billing_policies",
        "cp_business_invoice_proofs",
        "cp_owner_inbox_items",
        "cp_ad_campaigns",
        "cp_coupon_campaigns",
        "cp_coupon_assignments",
        "cp_hybrid_bundles",
        "cp_hybrid_bundle_components",
        "cp_hybrid_bundle_purchases",
        "cp_hybrid_purchase_proofs",
        "cp_hybrid_inventory_holds",
        "cp_hybrid_revenue_allocations",
        "cp_reward_task_campaigns",
        "cp_reward_task_completions",
    }.issubset(tables)
    assert len(tables) >= 146


def test_zero_fee_policy_does_not_generate_fake_one_iqd_invoice() -> None:
    source = (ROOT / "app/services/owner_commerce.py").read_text(encoding="utf-8")
    block = source.split("async def issue_due_invoices", 1)[1].split(
        "async def submit_invoice_proof", 1
    )[0]
    assert "fixed_service_fee_iqd) == 0" in block
    assert "amount_iqd=max(1" not in block


def test_hybrid_payment_creates_real_child_orders_and_balanced_ledger() -> None:
    source = (ROOT / "app/services/owner_commerce.py").read_text(encoding="utf-8")
    block = source.split("async def allocate_hybrid_purchase", 1)[1].split(
        "async def create_reward_campaign", 1
    )[0]
    assert "child_order = Order(" in block
    assert "HybridRevenueAllocation(" in block
    assert "order_id=child_order.id" in block
    assert "post_balanced_transaction" in block
    assert "HybridPurchaseStatus.FULFILLING.value" in block


def test_financial_and_campaign_jobs_are_wired_into_scheduler() -> None:
    source = (ROOT / "app/tasks/scheduler.py").read_text(encoding="utf-8")
    for token in (
        "owner_commerce.issue_due_invoices",
        "owner_commerce.enforce_overdue_billing",
        "owner_commerce.expire_hybrid_purchases",
        "owner_commerce.process_ad_campaigns",
        "owner_commerce.sync_central_inbox",
    ):
        assert token in source


def test_reward_tasks_use_telegram_membership_verification() -> None:
    source = (ROOT / "app/bot/handlers/owner_commerce.py").read_text(encoding="utf-8")
    assert "get_chat_member" in source
    assert "reward_verified_student" in source
    assert "reward_tasks" in source


def test_v11_4_migration_contains_uniqueness_and_amount_guards() -> None:
    source = (ROOT / "alembic/versions/1140_owner_commerce.py").read_text(
        encoding="utf-8"
    )
    for token in (
        "uq_cp_business_invoice_proof_fingerprint",
        "uq_cp_owner_inbox_source",
        "uq_cp_ad_campaign_key",
        "uq_cp_coupon_assignment_user",
        "uq_cp_hybrid_allocation_order",
        "uq_cp_financial_proof_fingerprint",
        "uq_cp_reward_completion_user",
        "ck_cp_hybrid_purchase_proof_amount",
    ):
        assert token in source


def test_hybrid_inventory_is_held_before_payment_and_converted_to_delivery() -> None:
    source = (ROOT / "app/services/owner_commerce.py").read_text(encoding="utf-8")
    create_block = source.split("async def create_hybrid_purchase", 1)[1].split(
        "async def submit_hybrid_purchase_proof", 1
    )[0]
    allocate_block = source.split("async def allocate_hybrid_purchase", 1)[1].split(
        "async def _release_hybrid_holds", 1
    )[0]
    assert "HybridInventoryHold(" in create_block
    assert "with_for_update(skip_locked=True)" in create_block
    assert "InventoryStatus.RESERVED.value" in create_block
    assert "PurchaseReservation(" in allocate_block
    assert "DeliveryJob(" in allocate_block
    assert 'job_type="hybrid_bundle_delivery"' in allocate_block


def test_provider_commerce_handlers_recheck_tenant_and_feature_flags() -> None:
    source = (ROOT / "app/bot/handlers/owner_commerce.py").read_text(encoding="utf-8")
    assert "allow_paused: bool = False" in source
    assert 'int(data.get("ad_provider_id") or 0) != int(provider_view.provider_id)' in source
    assert 'int(data.get("rt_provider_id") or 0) != int(provider_view.provider_id)' in source
    assert source.count('features.enabled(session,"reward_tasks",default=False)') >= 2
    assert 'getattr(member.status, "value", str(member.status))' in source


def test_financial_proof_registry_blocks_cross_workflow_receipt_reuse() -> None:
    source = (ROOT / "app/services/owner_commerce.py").read_text(encoding="utf-8")
    assert "async def _claim_financial_proof" in source
    assert "تم استخدام صورة الإثبات نفسها في عملية مالية أخرى" in source
    for source_type in ("business_invoice", "ad_campaign", "hybrid_purchase", "reward_campaign"):
        assert f'source_type="{source_type}"' in source
