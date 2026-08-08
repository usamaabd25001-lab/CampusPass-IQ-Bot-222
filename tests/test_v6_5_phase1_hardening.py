from __future__ import annotations

from pathlib import Path

import pytest

from app import __version__
from app.core.config import Settings
from app.core.release import is_release_at_least
from app.db.migrations import MIGRATIONS
from app.db.models import DeliveryJob, Notification, Order, ProviderStaff, SupportTicket
from app.services.payments import PaymentService


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


def test_current_version_is_consistent_and_includes_phase1_migration() -> None:
    assert is_release_at_least(__version__, "6.5.0-commercial-hardening-phase1")
    assert Path("VERSION.txt").read_text(encoding="utf-8").strip() == __version__


def test_withdrawals_are_requested_but_not_operational_without_marketplace() -> None:
    settings = Settings(**BASE)
    assert settings.money_flow_model == "provider_direct_prepaid_commission"
    assert settings.feature_provider_withdrawals is True
    assert settings.provider_withdrawals_ready is False


def test_withdrawals_require_a_ready_gateway_before_becoming_operational() -> None:
    pending = Settings(**BASE, MONEY_FLOW_MODEL="gateway_marketplace")
    assert pending.feature_provider_withdrawals is True
    assert pending.provider_withdrawals_ready is False


def test_verify_full_uses_system_ca_by_default() -> None:
    settings = Settings(**BASE)
    assert settings.db_ssl_mode == "verify-full"
    assert settings.db_ca_cert_b64 == ""


def test_payment_reference_normalization_is_stable() -> None:
    assert PaymentService.normalize_reference(" ab-12 ٣٤ ") == "AB12٣٤"


def test_hardening_columns_are_present() -> None:
    assert hasattr(ProviderStaff, "can_view_finance")
    assert hasattr(ProviderStaff, "can_request_withdrawal")
    assert hasattr(Order, "idempotency_key")
    assert hasattr(Order, "payment_snapshot")
    assert hasattr(SupportTicket, "closed_by_user_id")
    assert hasattr(DeliveryJob, "lease_expires_at")
    assert hasattr(Notification, "delivery_status")
    assert hasattr(Notification, "idempotency_key")


def test_phase1_migration_is_registered() -> None:
    assert any(
        migration.version == "6.5.0-commercial-hardening-phase1"
        for migration in MIGRATIONS
    )


def test_provider_owner_no_longer_bypasses_paid_entitlements() -> None:
    source = Path("app/bot/handlers/provider.py").read_text(encoding="utf-8")
    assert 'if staff.title == "owner":\n        return True' not in source
    assert 'and staff.title != "owner"' not in source


def test_support_callbacks_recheck_authorization() -> None:
    source = Path("app/bot/handlers/support.py").read_text(encoding="utf-8")
    assert "require_owned_order" in source
    assert "ticket_actor" in source
    assert "ticket_sender_role" not in source


def test_phase1_owner_diagnostics_commands_exist() -> None:
    source = (ROOT / "app/bot/handlers/admin/core.py").read_text(encoding="utf-8")
    for command in ("diagnostics", "system_status", "recent_errors", "version"):
        assert f'Command("{command}")' in source


def test_legacy_runtime_files_removed() -> None:
    for path in (
        "app/config.py",
        "app/database.py",
        "app/models.py",
        "app/repositories.py",
        "app/keyboards.py",
        "app/middleware.py",
        "app/states.py",
        "app/handlers",
    ):
        assert not (ROOT / path).exists()


def test_project_memory_and_runbook_files_exist() -> None:
    for name in (
        "PROJECT_STATE_AR.md",
        "DECISIONS_AR.md",
        "ROADMAP_AR.md",
        "KNOWN_ISSUES_AR.md",
        "RUNBOOK_AR.md",
        "DEPLOYMENT_AR.md",
    ):
        assert (ROOT / name).is_file()
