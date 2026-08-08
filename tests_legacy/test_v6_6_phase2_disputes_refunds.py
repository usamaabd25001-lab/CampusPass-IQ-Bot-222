from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

from app import __version__
from app.core.config import Settings
from app.core.release import is_release_at_least
from app.db.migrations import MIGRATIONS
from app.db.models import Base, Dispute, InventoryRemediation, Refund, SupportTicket

ROOT = Path(__file__).resolve().parents[1]

BASE = {
    "BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
    "ADMIN_IDS": "1001",
    "DATABASE_URL": "postgresql://user:pass@db.example.com:5432/postgres",
    "ENVIRONMENT": "production",
    "RELEASE_ID": "test-release",
    "REQUIRE_EXTERNAL_DATABASE": True,
    "ENCRYPTION_KEY": "x" * 48,
}


def test_v10_keeps_phase2_schema_for_audit_compatibility() -> None:
    assert is_release_at_least(__version__, "6.6.0-disputes-refunds-phase2")
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == __version__
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert {
        "cp_disputes",
        "cp_dispute_events",
        "cp_refunds",
        "cp_inventory_remediations",
        "cp_support_tickets",
    } <= tables
    assert len(tables) >= 75
    assert Dispute.__table__.c.order_id.unique is True or any(
        tuple(constraint.columns.keys()) == ("order_id",)
        for constraint in Dispute.__table__.constraints
        if getattr(constraint, "columns", None) is not None
    )
    assert Refund.__table__.c.transfer_reference_fingerprint.unique is True
    assert hasattr(InventoryRemediation, "status")
    assert hasattr(SupportTicket, "provider_id")


def test_v10_disables_new_complex_disputes_by_default() -> None:
    settings = Settings(**BASE)
    assert settings.feature_disputes is False
    service = (ROOT / "app/services/disputes.py").read_text(encoding="utf-8")
    handler = (ROOT / "app/bot/handlers/disputes.py").read_text(encoding="utf-8")
    assert "open_direct_support" in service
    assert 'category="direct_provider_support"' in service
    assert "no new dispute is created" in service
    assert 'Command("disputes")' in handler
    assert 'Command("dispute")' in handler
    assert "تم استبدال نظام النزاعات المعقد بالدعم المباشر" in handler
    for removed_method in (
        "async def open_dispute",
        "async def report_refund_transfer",
        "async def complete_refund",
    ):
        assert removed_method not in service


def test_direct_support_is_paginated_and_sent_to_provider_accounts() -> None:
    service = (ROOT / "app/services/disputes.py").read_text(encoding="utf-8")
    handler = (ROOT / "app/bot/handlers/disputes.py").read_text(encoding="utf-8")
    notifications = (ROOT / "app/services/notifications.py").read_text(encoding="utf-8")
    assert "user_disputes_page" in service
    assert ".offset(safe_page * safe_size)" in service
    assert "provider_support_ids" in service
    assert "copy_message" in handler
    assert "can_support.is_(True)" in notifications


def test_inventory_security_and_financial_history_are_preserved() -> None:
    dispute_service = (ROOT / "app/services/disputes.py").read_text(encoding="utf-8")
    finance = (ROOT / "app/services/finance.py").read_text(encoding="utf-8")
    reports = (ROOT / "app/services/reports.py").read_text(encoding="utf-8")
    assert "close_inventory_remediation" in dispute_service
    remediation = dispute_service[
        dispute_service.index("async def close_inventory_remediation") :
        dispute_service.index("async def auto_complete_eligible_orders")
    ]
    assert "InventoryStatus.AVAILABLE" not in remediation
    for token in ("provider_payable_refund", "owner_revenue_refund"):
        assert token in finance
    assert "provider_payable_refund" in reports


def test_phase2_migration_and_historical_documents_remain_registered() -> None:
    versions = [migration.version for migration in MIGRATIONS]
    assert "6.6.0-disputes-refunds-phase2" in versions
    assert versions.index("6.6.0-disputes-refunds-phase2") > versions.index(
        "6.5.0-commercial-hardening-phase1"
    )
    for name in (
        "CHANGELOG_V6_6_PHASE2_AR.md",
        "PHASE2_ACCEPTANCE_AR.md",
        "PROJECT_STATE_AR.md",
        "DECISIONS_AR.md",
        "RUNBOOK_AR.md",
        "DEPLOYMENT_AR.md",
    ):
        assert (ROOT / name).is_file()
