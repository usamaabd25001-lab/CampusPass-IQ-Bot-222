from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.db.migrations import MIGRATIONS
from app.db.models import Base, DeploymentGateRun, TelegramUpdateInbox
from app.domain.telegram_delivery import canonical_payload_digest, retry_delay_seconds

ROOT = Path(__file__).resolve().parents[1]


def test_update_payload_digest_is_canonical() -> None:
    first = {"update_id": 42, "message": {"text": "hello", "chat": {"id": 7}}}
    second = {"message": {"chat": {"id": 7}, "text": "hello"}, "update_id": 42}
    assert canonical_payload_digest(first) == canonical_payload_digest(second)
    assert len(canonical_payload_digest(first)) == 64
    assert retry_delay_seconds(1) == 2
    assert retry_delay_seconds(20) == 256


def test_v116_tables_are_registered() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert TelegramUpdateInbox.__tablename__ in tables
    assert DeploymentGateRun.__tablename__ in tables
    assert len(tables) >= 155


def test_v116_is_latest_application_migration() -> None:
    assert "11.6.0-render-e2e-hardening" in {item.version for item in MIGRATIONS}
    assert MIGRATIONS[-1].version == "11.7.1-all-features-ready"


def test_webhook_is_authenticated_and_durable() -> None:
    source = (ROOT / "app/api/server.py").read_text(encoding="utf-8")
    assert "x_telegram_bot_api_secret_token" in source
    assert "secrets.compare_digest" in source
    assert "telegram_updates.enqueue" in source
    assert "Update inbox unavailable" in source


def test_render_uses_predeploy_ready_checks_and_ci_gate() -> None:
    for filename in ("render.yaml", "render.production.yaml"):
        source = (ROOT / filename).read_text(encoding="utf-8")
        assert "preDeployCommand: python ops/render_predeploy.py" in source
        assert "healthCheckPath: /health/ready" in source
        assert "autoDeployTrigger: checksPass" in source
        assert "TELEGRAM_DELIVERY_MODE" in source


def test_polling_remains_a_local_fallback() -> None:
    source = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert 'settings.telegram_delivery_mode == "webhook"' in source
    assert 'settings.telegram_delivery_mode == "polling"' in source
    assert "RuntimeLeaseGuard" in source


def test_smoke_test_rejects_forged_webhook() -> None:
    source = (ROOT / "ops/render_smoke.py").read_text(encoding="utf-8")
    assert "invalid-smoke-secret" in source
    assert "forged.status_code not in {403, 404}" in source
    assert '"/health/ready"' in source
