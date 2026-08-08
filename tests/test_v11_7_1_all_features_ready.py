from __future__ import annotations

from app import __version__
from app.core.config import Settings
from app.db.migrations import MIGRATIONS


BASE = {
    "BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
    "ADMIN_IDS": "1001",
    "DATABASE_URL": "postgresql://user:pass@db.example.com:5432/postgres",
    "ENVIRONMENT": "production",
    "RELEASE_ID": "test-release",
    "REQUIRE_EXTERNAL_DATABASE": True,
    "ENCRYPTION_KEY": "x" * 48,
}


def test_all_optional_features_are_requested_by_default() -> None:
    settings = Settings(**BASE)
    assert settings.feature_gemini is True
    assert settings.feature_mastercard is True
    assert settings.feature_provider_withdrawals is True
    assert settings.backup_enabled is True
    assert settings.image_moderation_enabled is True
    assert settings.evidence_external_storage_enabled is True


def test_missing_external_credentials_are_safe_pending_not_startup_failures() -> None:
    settings = Settings(**BASE)
    assert settings.gemini_ready is False
    assert settings.mastercard_ready is False
    assert settings.provider_withdrawals_ready is False
    assert settings.backup_ready is False
    assert settings.evidence_external_storage_ready is False
    assert settings.image_moderation_ready is True
    assert settings.image_moderation_external_ready is False


def test_connectors_become_ready_only_with_complete_configuration() -> None:
    settings = Settings(
        **BASE,
        PUBLIC_BASE_URL="https://campuspass.example",
        GEMINI_API_KEY="gemini-secret",
        PAYMENT_GATEWAY_CREATE_URL="https://payments.example/checkout",
        PAYMENT_GATEWAY_API_KEY="gateway-secret",
        PAYMENT_GATEWAY_MERCHANT_ID="merchant-1",
        PAYMENT_WEBHOOK_SECRET="w" * 48,
        MONEY_FLOW_MODEL="gateway_marketplace",
        BACKUP_S3_BUCKET="backups",
        BACKUP_S3_ACCESS_KEY="access",
        BACKUP_S3_SECRET_KEY="secret",
        EVIDENCE_S3_BUCKET="evidence",
        EVIDENCE_S3_ACCESS_KEY="access",
        EVIDENCE_S3_SECRET_KEY="secret",
        GOOGLE_VISION_API_KEY="vision-secret",
    )
    assert settings.gemini_ready is True
    assert settings.mastercard_ready is True
    assert settings.provider_withdrawals_ready is True
    assert settings.backup_ready is True
    assert settings.evidence_external_storage_ready is True
    assert settings.image_moderation_external_ready is True


def test_patch_version_and_migration_are_registered() -> None:
    assert __version__ == "11.7.1-all-features-ready"
    assert MIGRATIONS[-1].version == "11.7.1-all-features-ready"
