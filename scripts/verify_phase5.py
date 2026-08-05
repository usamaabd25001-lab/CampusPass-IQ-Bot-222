from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, inspect

from app import __version__
from app.core.release import require_release_at_least
from app.db.migrations import MIGRATIONS
from app.db.models import Base

EXPECTED = "6.9.0-operations-reliability-phase5"


def require_tokens(path: str, tokens: tuple[str, ...]) -> None:
    source = (ROOT / path).read_text(encoding="utf-8")
    for token in tokens:
        if token not in source:
            raise SystemExit(f"missing phase5 token in {path}: {token}")


def main() -> None:
    require_release_at_least(__version__, EXPECTED, context="phase5 verification")
    if (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() != __version__:
        raise SystemExit("VERSION.txt mismatch")

    parsed = 0
    for base in ("app", "tests", "scripts", "ops"):
        directory = ROOT / base
        if not directory.exists():
            continue
        for path in directory.rglob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            parsed += 1

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    required = {
        "cp_deployment_releases",
        "cp_scheduled_runs",
        "cp_backup_runs",
        "cp_runtime_incidents",
        "cp_secret_rotation_runs",
    }
    if not required <= tables:
        raise SystemExit(f"missing phase5 tables: {required - tables}")
    if len(tables) < 87:
        raise SystemExit(f"unexpected table count: {len(tables)}")
    if not any(m.version == EXPECTED for m in MIGRATIONS):
        raise SystemExit("phase5 migration is missing")

    require_tokens(
        "app/main.py",
        (
            "auto_pre_deploy_backup",
            "runtime_mode",
            "mark_release_ready",
            "mark_release_failed",
        ),
    )
    require_tokens(
        "app/tasks/scheduler.py",
        (
            "claim_scheduled_run",
            "database_backup",
            "operations_cleanup",
            "SCH-MAIN",
        ),
    )
    require_tokens(
        "app/services/backups.py",
        ("PGPASSWORD", "put_object", "VERIFIED", "verification hash mismatch"),
    )
    require_tokens(
        "app/core/security.py",
        ("MultiFernet", "needs_rotation", "def rotate"),
    )
    require_tokens(
        "app/api/server.py",
        ('@app.get("/metrics"', "campuspass_backup_stale", "X-CampusPass-Release"),
    )
    require_tokens(
        "app/core/observability.py",
        ("sentry_sdk.init", "send_default_pii=False"),
    )
    if not (ROOT / "alembic/versions/690_operations_baseline.py").is_file():
        raise SystemExit("Alembic V6.9 baseline is missing")
    for name in (
        "PHASE5_IMPLEMENTATION_REPORT_AR.md",
        "PHASE5_ACCEPTANCE_AR.md",
        "CHANGELOG_V6_9_PHASE5_AR.md",
        "PROJECT_STATE_AR.md",
        "ROADMAP_AR.md",
        "RUNBOOK_AR.md",
    ):
        if not (ROOT / name).is_file():
            raise SystemExit(f"missing phase5 document: {name}")

    print(
        f"Phase 5 verification passed: {parsed} Python files, "
        f"{len(tables)} tables, migration={EXPECTED}"
    )


if __name__ == "__main__":
    main()
