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
from app.core.presentation import delivery_estimate_label, order_status_label
from app.db.migrations import MIGRATIONS
from app.db.models import Base, Order

PHASE4 = "6.8.0-user-experience-phase4"


def require_tokens(path: str, tokens: tuple[str, ...]) -> None:
    source = (ROOT / path).read_text(encoding="utf-8")
    for token in tokens:
        if token not in source:
            raise SystemExit(f"missing phase4 token in {path}: {token}")


def main() -> None:
    require_release_at_least(__version__, PHASE4, context="phase4 verification")
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
    columns = {column["name"] for column in inspect(engine).get_columns("cp_orders")}
    required_columns = {"delivery_acknowledged_at", "activation_confirmed_at"}
    if not required_columns <= columns:
        raise SystemExit(f"missing phase4 columns: {required_columns - columns}")
    if not hasattr(Order, "delivery_acknowledged_at") or not hasattr(Order, "activation_confirmed_at"):
        raise SystemExit("phase4 Order attributes are missing")

    versions = [migration.version for migration in MIGRATIONS]
    if PHASE4 not in versions:
        raise SystemExit("phase4 migration is not registered")

    require_tokens(
        "app/bot/handlers/start.py",
        ("quick_registration", "profile:complete", "يُستكمل لاحقاً"),
    )
    require_tokens(
        "app/bot/handlers/catalog.py",
        ("_show_purchase_confirmation", "purchase:confirm:", "delivery_estimate_label"),
    )
    require_tokens(
        "app/services/orders.py",
        ("acknowledge_delivery", "confirm_activation", "user_orders_page"),
    )
    require_tokens(
        "app/services/support.py",
        ("user_tickets_page", "ticket_messages_page"),
    )
    require_tokens(
        "app/services/disputes.py",
        ("user_disputes_page",),
    )

    for name in (
        "PHASE4_IMPLEMENTATION_REPORT_AR.md",
        "PHASE4_ACCEPTANCE_AR.md",
        "CHANGELOG_V6_8_PHASE4_AR.md",
        "PROJECT_STATE_AR.md",
        "ROADMAP_AR.md",
        "RUNBOOK_AR.md",
    ):
        if not (ROOT / name).is_file():
            raise SystemExit(f"missing phase4 project memory file: {name}")

    if order_status_label("payment_review") != "قيد مراجعة الدفع":
        raise SystemExit("Arabic order presentation is broken")
    if "دقائق" not in delivery_estimate_label("inventory_code"):
        raise SystemExit("delivery estimate presentation is broken")

    print(
        f"Phase 4 verification passed: {parsed} Python files, "
        f"{len(tables)} tables, migration={PHASE4}, release={__version__}"
    )


if __name__ == "__main__":
    main()
