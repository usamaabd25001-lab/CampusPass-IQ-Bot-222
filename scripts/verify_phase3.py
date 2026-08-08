from __future__ import annotations

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, inspect

from app import __version__
from app.core.release import require_release_at_least
from app.db.migrations import MIGRATIONS
from app.db.models import Base, EvidenceAsset, PrivacyRequest

PHASE3 = "6.7.0-privacy-evidence-phase3"


def main() -> None:
    require_release_at_least(__version__, PHASE3, context="phase3 verification")
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
    required_tables = {
        "cp_evidence_assets",
        "cp_evidence_access_logs",
        "cp_secret_access_logs",
        "cp_privacy_requests",
    }
    if not required_tables <= tables:
        raise SystemExit(f"missing phase3 tables: {required_tables - tables}")

    versions = [migration.version for migration in MIGRATIONS]
    if PHASE3 not in versions:
        raise SystemExit("phase3 migration is not registered")

    if EvidenceAsset.__table__.c.public_id.unique is not True:
        raise SystemExit("evidence public id uniqueness is missing")
    if not PrivacyRequest.__table__.c.execute_after.index:
        raise SystemExit("privacy execution index is missing")

    privacy = (ROOT / "app/services/privacy.py").read_text(encoding="utf-8")
    evidence = (ROOT / "app/services/evidence.py").read_text(encoding="utf-8")
    health = (ROOT / "app/services/health.py").read_text(encoding="utf-8")
    for token in (
        "private_data_encrypted",
        "activation_data_encrypted",
        "redact_for_ai",
        "SecretAccessLog",
        "mask_mapping(self.order_activation_data(order))",
    ):
        if token not in privacy:
            raise SystemExit(f"missing privacy safety token: {token}")
    for token in (
        "encrypted_telegram_file_id",
        "EvidenceAccessLog",
        "archive_pending",
        "purge_expired",
        "encrypt_bytes",
    ):
        if token not in evidence:
            raise SystemExit(f"missing evidence safety token: {token}")
    for token in ("pending_privacy_deletions", "evidence_failed", "evidence_expired"):
        if token not in health:
            raise SystemExit(f"missing health diagnostic: {token}")

    print(
        f"Phase 3 verification passed: {parsed} Python files, "
        f"{len(tables)} tables, migration={PHASE3}, release={__version__}"
    )


if __name__ == "__main__":
    main()
