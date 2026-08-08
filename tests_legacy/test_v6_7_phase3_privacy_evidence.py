from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

from app import __version__
from app.core.config import Settings
from app.core.release import is_release_at_least
from app.core.security import SecretBox
from app.db.migrations import MIGRATIONS
from app.db.models import Base, EvidenceAsset, PrivacyRequest, StudentProfile
from app.services.privacy import PrivacyService

ROOT = Path(__file__).resolve().parents[1]

BASE = {
    "BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
    "ADMIN_IDS": "1001",
    "DATABASE_URL": "postgresql://user:pass@db.example.com:5432/postgres",
    "ENVIRONMENT": "production",
    "RELEASE_ID": "test-release",
    "REQUIRE_EXTERNAL_DATABASE": True,
    "ENCRYPTION_KEY": "phase3-test-key-with-more-than-thirty-two-characters",
}


def test_phase3_version_is_consistent() -> None:
    assert is_release_at_least(__version__, "6.7.0-privacy-evidence-phase3")
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == __version__


def test_phase3_schema_builds_and_contains_privacy_tables() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert {
        "cp_evidence_assets",
        "cp_evidence_access_logs",
        "cp_secret_access_logs",
        "cp_privacy_requests",
    } <= tables
    assert len(tables) >= 82


def test_phase3_migration_is_registered_after_phase2() -> None:
    versions = [migration.version for migration in MIGRATIONS]
    assert "6.6.0-disputes-refunds-phase2" in versions
    assert "6.7.0-privacy-evidence-phase3" in versions
    assert versions.index("6.7.0-privacy-evidence-phase3") > versions.index(
        "6.6.0-disputes-refunds-phase2"
    )


def test_profile_masking_and_encryption_round_trip() -> None:
    settings = Settings(**BASE)
    privacy = PrivacyService(settings, SecretBox(settings))
    profile = StudentProfile(
        user_id=1,
        full_name="علي محمد حسن",
        phone="07701234567",
        governorate="بغداد",
        university="جامعة",
        college="كلية",
        department="قسم",
        stage="الأولى",
    )
    encrypted = privacy._encrypt_json({"full_name": profile.full_name, "phone": profile.phone})
    profile.private_data_encrypted = encrypted
    profile.full_name = privacy.mask_name(profile.full_name)
    profile.phone = privacy.mask_phone(profile.phone)
    assert profile.full_name != "علي محمد حسن"
    assert profile.phone == "***4567"
    restored = privacy.profile_data(profile)
    assert restored["full_name"] == "علي محمد حسن"
    assert restored["phone"] == "07701234567"


def test_ai_redaction_removes_common_sensitive_values() -> None:
    text = (
        "بريدي ali@example.com وهاتفي 07701234567\n"
        "رقم البطاقة: 4111 1111 1111 1111\n"
        "password: secret-value\nرقم العملية 123456789012"
    )
    redacted = PrivacyService.redact_for_ai(text)
    assert "ali@example.com" not in redacted
    assert "07701234567" not in redacted
    assert "4111 1111 1111 1111" not in redacted
    assert "secret-value" not in redacted
    assert "123456789012" not in redacted
    assert "REDACTED" in redacted


def test_export_masks_activation_secrets() -> None:
    source = (ROOT / "app/services/privacy.py").read_text(encoding="utf-8")
    assert "mask_mapping(self.order_activation_data(order))" in source
    assert '"activation_data": self.order_activation_data(order)' not in source


def test_evidence_registry_encrypts_telegram_references_and_audits_access() -> None:
    source = (ROOT / "app/services/evidence.py").read_text(encoding="utf-8")
    for token in (
        "self.secrets.encrypt(file_id)",
        "EvidenceAccessLog",
        "self.secrets.decrypt(asset.encrypted_telegram_file_id)",
        "encrypt_bytes(raw)",
        "purge_expired",
    ):
        assert token in source
    assert EvidenceAsset.__table__.c.public_id.unique is True


def test_privacy_requests_and_secret_access_are_wired_to_handlers() -> None:
    privacy_handler = (ROOT / "app/bot/handlers/privacy.py").read_text(encoding="utf-8")
    router_source = (ROOT / "app/bot/handlers/__init__.py").read_text(encoding="utf-8")
    admin_source = (ROOT / "app/bot/handlers/admin/operations.py").read_text(encoding="utf-8")
    menu_source = (ROOT / "app/bot/handlers/menu.py").read_text(encoding="utf-8")
    for token in ('Command("privacy")', 'Command("my_data")', "privacy:delete_request"):
        assert token in privacy_handler
    assert "privacy.router" in router_source
    assert "reveal_order_activation" in admin_source
    assert '"privacy"' in menu_source
    assert PrivacyRequest.__tablename__ == "cp_privacy_requests"


def test_external_evidence_storage_can_be_required_in_production() -> None:
    settings = Settings(**BASE)
    assert settings.evidence_external_storage_enabled is False
    assert settings.require_external_evidence_storage_in_production is False
    invalid = dict(BASE)
    invalid["REQUIRE_EXTERNAL_EVIDENCE_STORAGE_IN_PRODUCTION"] = True
    try:
        Settings(**invalid)
    except ValueError as exc:
        assert "external evidence storage" in str(exc)
    else:
        raise AssertionError("production requirement must reject missing external evidence storage")


def test_health_diagnostics_include_privacy_and_evidence_backlogs() -> None:
    health = (ROOT / "app/services/health.py").read_text(encoding="utf-8")
    admin = (ROOT / "app/bot/handlers/admin/core.py").read_text(encoding="utf-8")
    for token in ("pending_privacy_deletions", "evidence_failed", "evidence_expired"):
        assert token in health
    assert "طلبات حذف بيانات معلقة" in admin
    assert "أدلة فشلت أرشفتها" in admin


def test_legacy_plaintext_evidence_is_migrated_and_new_payment_reviews_use_registry() -> None:
    evidence = (ROOT / "app/services/evidence.py").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    scheduler = (ROOT / "app/tasks/scheduler.py").read_text(encoding="utf-8")
    payments = (ROOT / "app/bot/handlers/payments.py").read_text(encoding="utf-8")
    assert "async def migrate_legacy_references" in evidence
    assert "proof.photo_file_id = None" in evidence
    assert "item.file_id = None" in evidence
    assert "dispute.evidence_file_id = None" in evidence
    assert "refund.proof_file_id = None" in evidence
    assert "migrate_legacy_references(session, limit=500)" in main
    assert "migrate_legacy_references(session, limit=25)" in scheduler
    assert "await services.evidence.send(" in payments
