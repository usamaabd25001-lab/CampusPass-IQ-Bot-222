from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import __version__
from app.core.config import Settings
from app.db.migrations import MIGRATIONS

EXPECTED = "11.7.1-all-features-ready"

if __version__ != EXPECTED:
    raise SystemExit(f"Unexpected version: {__version__}")
if MIGRATIONS[-1].version != EXPECTED:
    raise SystemExit("V11.7.1 custom migration is not last")
if not (ROOT / "alembic/versions/1171_all_features_ready.py").exists():
    raise SystemExit("Alembic 1171 migration is missing")

settings = Settings(
    BOT_TOKEN="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
    ADMIN_IDS="1",
    DATABASE_URL="sqlite+aiosqlite:///:memory:",
    ENVIRONMENT="test",
    REQUIRE_EXTERNAL_DATABASE=False,
)
requested = {
    "gemini": settings.feature_gemini,
    "mastercard": settings.feature_mastercard,
    "provider_withdrawals": settings.feature_provider_withdrawals,
    "backup": settings.backup_enabled,
    "image_moderation": settings.image_moderation_enabled,
    "evidence_storage": settings.evidence_external_storage_enabled,
}
if not all(requested.values()):
    raise SystemExit(f"Optional feature was not requested: {requested}")
if settings.gemini_ready or settings.mastercard_ready or settings.backup_ready:
    raise SystemExit("Missing credentials must keep external connectors pending")
if not settings.image_moderation_ready:
    raise SystemExit("Local image moderation must remain operational")

render = (ROOT / "render.production.yaml").read_text(encoding="utf-8")
for key in requested:
    env_key = {
        "gemini": "FEATURE_GEMINI",
        "mastercard": "FEATURE_MASTERCARD",
        "provider_withdrawals": "FEATURE_PROVIDER_WITHDRAWALS",
        "backup": "BACKUP_ENABLED",
        "image_moderation": "IMAGE_MODERATION_ENABLED",
        "evidence_storage": "EVIDENCE_EXTERNAL_STORAGE_ENABLED",
    }[key]
    if render.count(f"- key: {env_key}") != 2:
        raise SystemExit(f"{env_key} must be present for Web and Worker")

print("V11.7.1 all-features readiness OK")
