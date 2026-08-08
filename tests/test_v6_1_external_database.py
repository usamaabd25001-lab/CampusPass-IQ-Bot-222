from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.db_url import normalize_async_database_url, safe_database_label


BASE = {
    "BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
    "ADMIN_IDS": "1001",
    "ENVIRONMENT": "production",
    "RELEASE_ID": "test-release",
    "ENCRYPTION_KEY": "x" * 48,
}


def test_external_url_normalizes_libpq_parameters() -> None:
    value = normalize_async_database_url(
        "postgresql://user:pass@example.supabase.co:5432/postgres"
        "?sslmode=require&channel_binding=require&application_name=test"
    )
    assert value.startswith("postgresql+asyncpg://")
    assert "sslmode=" not in value
    assert "channel_binding=" not in value
    assert "application_name=test" in value


def test_production_rejects_railway_internal_database() -> None:
    with pytest.raises(ValidationError, match="Railway-internal"):
        Settings(
            **BASE,
            DATABASE_URL="postgresql://user:pass@postgres.railway.internal:5432/railway",
            REQUIRE_EXTERNAL_DATABASE=True,
        )


def test_production_accepts_external_database() -> None:
    settings = Settings(
        **BASE,
        DATABASE_URL="postgresql://user:pass@db.example.com:5432/postgres?sslmode=require",
        REQUIRE_EXTERNAL_DATABASE=True,
    )
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.db_ssl_mode == "verify-full"


def test_safe_database_label_never_contains_credentials() -> None:
    label = safe_database_label(
        "postgresql+asyncpg://secret-user:secret-pass@db.example.com:5432/campuspass"
    )
    assert label == "db.example.com:5432/campuspass"
    assert "secret" not in label
