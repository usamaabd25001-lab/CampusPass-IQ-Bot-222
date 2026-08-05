from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.schema import UniqueConstraint

from app import __version__
from app.core.config import Settings
from app.core.release import is_release_at_least
from app.core.security import SecretBox
from app.db.migrations import MIGRATIONS
from app.db.models import (
    BackupRun,
    Base,
    DeploymentRelease,
    RuntimeIncident,
    ScheduledRun,
    SecretRotationRun,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "6.9.0-operations-reliability-phase5"


def base_settings(**overrides):
    values = {
        "BOT_TOKEN": "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ADMIN_IDS": "123456789",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "REQUIRE_EXTERNAL_DATABASE": False,
        "ENVIRONMENT": "test",
        "ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }
    values.update(overrides)
    return Settings(**values)


def test_phase5_version_migration_and_schema() -> None:
    assert is_release_at_least(__version__, EXPECTED)
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == __version__
    assert any(m.version == EXPECTED for m in MIGRATIONS)
    assert is_release_at_least(MIGRATIONS[-1].version, "7.0.0-pilot-quality-phase6")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert len(tables) >= 87
    assert {
        DeploymentRelease.__tablename__,
        ScheduledRun.__tablename__,
        BackupRun.__tablename__,
        RuntimeIncident.__tablename__,
        SecretRotationRun.__tablename__,
    } <= tables


def test_runtime_modes_and_production_release_guard() -> None:
    for mode in ("combined", "bot", "worker"):
        assert base_settings(RUNTIME_MODE=mode).runtime_mode == mode
    try:
        base_settings(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql+asyncpg://user:pass@db.example.net/campuspass",
            DB_SSL_MODE="verify-full",
            RELEASE_ID="local",
        )
    except ValidationError as exc:
        assert "stable RELEASE_ID" in str(exc)
    else:
        raise AssertionError("production local release must be rejected")



def test_railway_release_metadata_is_adopted_automatically() -> None:
    settings = base_settings(
        RAILWAY_DEPLOYMENT_ID="deploy-123",
        RAILWAY_GIT_COMMIT_SHA="abc123",
    )
    assert settings.release_id == "deploy-123"
    assert settings.git_sha == "abc123"


def test_release_identity_is_scoped_per_runtime_component() -> None:
    constraints = {
        item.name
        for item in DeploymentRelease.__table__.constraints
        if isinstance(item, UniqueConstraint)
    }
    assert "uq_cp_deployment_release_component" in constraints
    source = (ROOT / "app/services/operations.py").read_text(encoding="utf-8")
    assert "DeploymentRelease.runtime_mode == self.settings.runtime_mode" in source

def test_staging_cannot_use_production_bot_token() -> None:
    token = "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    fingerprint = __import__("hashlib").sha256(token.encode()).hexdigest()
    try:
        base_settings(
            ENVIRONMENT="staging",
            BOT_TOKEN=token,
            STAGING_BOT_TOKEN_FINGERPRINT=fingerprint,
        )
    except ValidationError as exc:
        assert "different BOT_TOKEN" in str(exc)
    else:
        raise AssertionError("staging must reject production token")


def test_multikey_decryption_and_rotation() -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    old_token = Fernet(old_key.encode()).encrypt(b"secret").decode()
    settings = base_settings(
        ENCRYPTION_KEY=new_key,
        ENCRYPTION_KEYRING=old_key,
        ENCRYPTION_KEY_VERSION=2,
    )
    box = SecretBox(settings)
    assert box.decrypt(old_token) == "secret"
    assert box.needs_rotation(old_token) is True
    rotated = box.rotate(old_token)
    assert box.decrypt(rotated) == "secret"
    assert box.needs_rotation(rotated) is False


def test_scheduler_uses_persistent_runs_and_verified_backups() -> None:
    source = (ROOT / "app/tasks/scheduler.py").read_text(encoding="utf-8")
    for token in (
        'claim_scheduled_run(',
        '"daily_reports"',
        '"database_backup"',
        '"hourly_lifecycle"',
        "BackupRunStatus.VERIFIED.value",
        'code="SCH-MAIN"',
    ):
        assert token in source
    assert "self.last_report_date" not in source[source.index("async def run"):]


def test_backup_does_not_place_password_in_process_arguments() -> None:
    source = (ROOT / "app/services/backups.py").read_text(encoding="utf-8")
    assert 'env["PGPASSWORD"] = password' in source
    assert 'password=None' in source
    assert 'client.put_object' in source
    assert 'backup verification hash mismatch' in source


def test_main_supports_split_runtime_and_predeploy_backup() -> None:
    source = (ROOT / "app/main.py").read_text(encoding="utf-8")
    for token in (
        'bot_mode = settings.runtime_mode in {"combined", "bot"}',
        'worker_mode = settings.runtime_mode in {"combined", "worker"}',
        "Creating verified pre-deploy backup before migrations",
        "mark_release_ready",
        "mark_release_failed",
    ):
        assert token in source


def test_observability_metrics_and_alembic_baseline_exist() -> None:
    api = (ROOT / "app/api/server.py").read_text(encoding="utf-8")
    observability = (ROOT / "app/core/observability.py").read_text(encoding="utf-8")
    assert '@app.get("/metrics"' in api
    assert "campuspass_backup_stale" in api
    assert "send_default_pii=False" in observability
    assert (ROOT / "alembic.ini").is_file()
    baseline = ROOT / "alembic/versions/690_operations_baseline.py"
    assert baseline.is_file()
    assert "Destructive downgrade is disabled" in baseline.read_text(encoding="utf-8")


def test_phase5_operational_documents_and_scripts_exist() -> None:
    for name in (
        "PHASE5_IMPLEMENTATION_REPORT_AR.md",
        "PHASE5_ACCEPTANCE_AR.md",
        "CHANGELOG_V6_9_PHASE5_AR.md",
        "PROJECT_STATE_AR.md",
        "ROADMAP_AR.md",
        "RUNBOOK_AR.md",
        "ops/preflight.py",
        "ops/backup_now.py",
        "ops/restore_backup.py",
    ):
        assert (ROOT / name).is_file(), name
