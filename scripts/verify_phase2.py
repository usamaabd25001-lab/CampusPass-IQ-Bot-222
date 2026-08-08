from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, inspect

from app import __version__
from app.core.release import require_release_at_least
from app.db.migrations import MIGRATIONS
from app.db.models import Base, Dispute, Refund

EXPECTED = "6.6.0-disputes-refunds-phase2"


def main() -> None:
    require_release_at_least(__version__, EXPECTED, context="phase2 compatibility verification")
    if (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() != __version__:
        raise SystemExit("VERSION.txt mismatch")

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    required_tables = {
        "cp_disputes",
        "cp_dispute_events",
        "cp_refunds",
        "cp_inventory_remediations",
        "cp_support_tickets",
    }
    if not required_tables <= tables:
        raise SystemExit(f"missing phase2 compatibility tables: {required_tables - tables}")

    versions = [migration.version for migration in MIGRATIONS]
    if EXPECTED not in versions:
        raise SystemExit("phase2 migration is not registered")

    dispute_unique = {
        tuple(constraint.columns.keys())
        for constraint in Dispute.__table__.constraints
        if getattr(constraint, "columns", None) is not None
    }
    if ("order_id",) not in dispute_unique:
        raise SystemExit("historical one-dispute-per-order constraint is missing")
    if Refund.__table__.c.transfer_reference_fingerprint.unique is not True:
        raise SystemExit("historical refund fingerprint uniqueness is missing")

    service = (ROOT / "app/services/disputes.py").read_text(encoding="utf-8")
    handler = (ROOT / "app/bot/handlers/disputes.py").read_text(encoding="utf-8")
    for token in (
        "open_direct_support",
        'category="direct_provider_support"',
        "user_disputes_page",
        "close_inventory_remediation",
    ):
        if token not in service:
            raise SystemExit(f"missing V10 direct-support compatibility token: {token}")
    for token in ('Command("disputes")', 'Command("dispute")', "copy_message"):
        if token not in handler:
            raise SystemExit(f"missing V10 support handler token: {token}")
    for removed in (
        "async def open_dispute",
        "async def report_refund_transfer",
        "async def complete_refund",
    ):
        if removed in service:
            raise SystemExit(f"legacy complex dispute method is still active: {removed}")

    print(
        f"Phase 2 compatibility verification passed: {len(tables)} tables, "
        f"migration={EXPECTED}, release={__version__}, direct-support=enabled"
    )


if __name__ == "__main__":
    main()
