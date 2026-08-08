from pathlib import Path

import pytest
from pydantic import ValidationError

from app import __version__
from app.core.config import Settings


BASE = {
    "BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
    "ADMIN_IDS": "123456789",
    "DATABASE_URL": "postgresql://user:secret@db.example.net:5432/postgres?sslmode=require",
    "ENVIRONMENT": "production",
    "RELEASE_ID": "test-release",
    "REQUIRE_EXTERNAL_DATABASE": True,
    "DB_SSL_MODE": "require",
    "ENCRYPTION_KEY": "x" * 48,
}


def test_runtime_version_matches_release_file():
    assert Path("VERSION.txt").read_text(encoding="utf-8").strip() == __version__


def test_environment_is_normalized_before_runtime_use():
    settings = Settings(**{**BASE, "ENVIRONMENT": " Production "})
    assert settings.environment == "production"


def test_arabic_encryption_placeholder_is_rejected():
    with pytest.raises(ValidationError):
        Settings(**{**BASE, "ENCRYPTION_KEY": "ضع_نفس_المفتاح_الثابت_ولا_تغيره"})


def test_database_placeholder_is_rejected():
    with pytest.raises(ValidationError):
        Settings(**{**BASE, "DATABASE_URL": "postgresql://USER:PASSWORD@HOST:5432/postgres"})


def test_secret_values_are_trimmed():
    settings = Settings(**{**BASE, "BOT_TOKEN": f"  {BASE['BOT_TOKEN']}  ", "ENCRYPTION_KEY": "  " + ("y" * 48) + "  "})
    assert settings.bot_token == BASE["BOT_TOKEN"]
    assert settings.encryption_key == "y" * 48
