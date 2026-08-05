from pathlib import Path

from app import __version__
from app.core.release import require_release_at_least
from app.db.migrations import MIGRATIONS
from app.db.models import Base


def test_release_and_migration_registered():
    require_release_at_least(__version__, "8.1.0", context="V8.1 regression test")
    versions = {migration.version for migration in MIGRATIONS}
    assert "8.1.0-ux-wallet-settlement" in versions


def test_wallet_coupon_and_settlement_schema_present():
    tables = set(Base.metadata.tables)
    assert "cp_wallets" in tables
    assert "cp_wallet_entries" in tables
    assert "cp_provider_settlements" in tables
    assert "cp_order_coupons" in tables
    assert "cp_order_coupon_redemptions" in tables


def test_surgical_features_are_wired():
    payment_source = Path("app/services/payments.py").read_text(encoding="utf-8")
    menu_source = Path("app/services/menus.py").read_text(encoding="utf-8")
    finance_source = Path("app/bot/handlers/admin/finance.py").read_text(encoding="utf-8")
    report_source = Path("app/services/reports.py").read_text(encoding="utf-8")
    nav_source = Path("app/bot/handlers/navigation.py").read_text(encoding="utf-8")

    assert "credit_overpayment" in payment_source
    assert "apply_to_purchase" in payment_source
    assert "move_button" in menu_source
    assert "provider.collection.created" in finance_source
    assert "provider.suspended.nonpayment" in finance_source
    assert "provider.logo_data_uri" in report_source
    assert "تم إلغاء الخطوة السابقة وفتح القسم الجديد" not in nav_source
