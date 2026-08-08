from pathlib import Path

from app import __version__
from app.core.release import is_release_at_least

ROOT = Path(__file__).resolve().parents[1]


def test_phase6_version_and_files():
    assert is_release_at_least(__version__, "7.0.0-pilot-quality-phase6")
    assert (ROOT / "app/services/pilot.py").exists()
    assert (ROOT / "ops/pilot_validate.py").exists()


def test_phase6_models_and_migration_are_additive():
    models = (ROOT / "app/db/models.py").read_text()
    migrations = (ROOT / "app/db/migrations.py").read_text()
    assert "cp_pilot_validation_runs" in models
    assert "cp_recovery_drills" in models
    assert "7.0.0-pilot-quality-phase6" in migrations
    assert "DROP TABLE" not in migrations.upper()


def test_pilot_validation_has_required_dependency_gates():
    source = (ROOT / "app/services/pilot.py").read_text()
    for name in ("database", "redis", "telegram", "storage", "verified_backup"):
        assert f'checks["{name}"]' in source
    assert "blocking_failures" in source
    assert "pilot_backup_max_age_hours" in source


def test_chaos_hooks_are_disabled_by_default():
    config = (ROOT / "app/core/config.py").read_text()
    assert 'chaos_testing_enabled: bool = Field(default=False' in config
    assert 'pilot_mode: bool = Field(default=False' in config
    assert 'pilot_strict_startup: bool = Field(default=False' in config


def test_readiness_can_enforce_latest_pilot_validation():
    server = (ROOT / "app/api/server.py").read_text()
    assert "pilot_validation_required" in server
    assert "context.settings.pilot_strict_startup" in server
    assert '@app.get("/admin/pilot")' in server
