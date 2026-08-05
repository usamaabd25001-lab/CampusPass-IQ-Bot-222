import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


BASE = {
    "BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
    "ADMIN_IDS": "9001",
    "DATABASE_URL": "postgresql+asyncpg://user:pass@db/app",
    "ENVIRONMENT": "production",
    "RELEASE_ID": "test-release",
    "ENCRYPTION_KEY": "e" * 48,
}


def test_reports_work_without_public_domain_in_production():
    settings = Settings(**BASE, FEATURE_REPORTS=True, FEATURE_MASTERCARD=False)
    assert settings.feature_reports is True
    assert settings.public_base_url == ""
    assert settings.report_secret_key == ""
    assert settings.api_admin_token == ""


def test_railway_public_domain_is_detected_automatically():
    settings = Settings(**BASE, RAILWAY_PUBLIC_DOMAIN="campuspass.up.railway.app")
    assert settings.public_base_url == "https://campuspass.up.railway.app"


def test_card_payments_still_require_public_url():
    with pytest.raises(ValidationError):
        Settings(
            **BASE,
            FEATURE_MASTERCARD=True,
            PAYMENT_GATEWAY_CREATE_URL="https://gateway.example/create",
            PAYMENT_GATEWAY_API_KEY="key",
            PAYMENT_GATEWAY_MERCHANT_ID="merchant",
            PAYMENT_WEBHOOK_SECRET="w" * 40,
        )


def test_railway_uses_liveness_healthcheck():
    railway = json.loads(Path("railway.json").read_text())
    assert railway["deploy"]["healthcheckPath"] == "/health/live"
    assert railway["deploy"]["healthcheckTimeout"] >= 300
