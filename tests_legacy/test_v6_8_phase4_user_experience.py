from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

from app import __version__
from app.core.release import is_release_at_least
from app.core.presentation import (
    delivery_estimate_label,
    dispute_status_label,
    order_status_label,
    provider_status_label,
    refund_status_label,
    sender_role_label,
    subscription_status_label,
    ticket_status_label,
)
from app.db.migrations import MIGRATIONS
from app.db.models import Base, Order

ROOT = Path(__file__).resolve().parents[1]


def test_phase4_version_and_migration_are_consistent() -> None:
    assert is_release_at_least(__version__, "6.8.0-user-experience-phase4")
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == __version__
    versions = [migration.version for migration in MIGRATIONS]
    assert "6.8.0-user-experience-phase4" in versions
    assert versions.index("6.8.0-user-experience-phase4") > versions.index(
        "6.7.0-privacy-evidence-phase3"
    )


def test_phase4_schema_keeps_previous_tables_and_adds_ack_timestamps() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert len(tables) >= 82
    assert hasattr(Order, "delivery_acknowledged_at")
    assert hasattr(Order, "activation_confirmed_at")
    columns = {column["name"] for column in inspect(engine).get_columns("cp_orders")}
    assert {"delivery_acknowledged_at", "activation_confirmed_at"} <= columns


def test_progressive_onboarding_allows_browsing_before_profile() -> None:
    start = (ROOT / "app/bot/handlers/start.py").read_text(encoding="utf-8")
    catalog = (ROOT / "app/bot/handlers/catalog.py").read_text(encoding="utf-8")
    assert "تقدر تتصفح جميع المنصات والعروض بدون تسجيل طويل" in start
    assert "quick_registration=True" in catalog
    assert "pending_purchase_offer_id" in catalog
    assert "يُستكمل لاحقاً" in start
    assert "profile:complete" in start


def test_purchase_requires_explicit_confirmation_before_order_creation() -> None:
    catalog = (ROOT / "app/bot/handlers/catalog.py").read_text(encoding="utf-8")
    keyboards = (ROOT / "app/bot/keyboards/inline.py").read_text(encoding="utf-8")
    show_pos = catalog.index("async def _show_purchase_confirmation")
    confirm_pos = catalog.index("async def confirm_purchase")
    create_pos = catalog.index("await services.orders.create", confirm_pos)
    assert show_pos < confirm_pos < create_pos
    assert "purchase:confirm:" in catalog
    assert "purchase:cancel" in catalog
    assert "أوافق وأنشئ الطلب" in keyboards
    assert "لم يُحجز أي مورد أو مبلغ" in catalog


def test_delivery_and_activation_are_separate_user_actions() -> None:
    orders = (ROOT / "app/bot/handlers/orders.py").read_text(encoding="utf-8")
    service = (ROOT / "app/services/orders.py").read_text(encoding="utf-8")
    keyboards = (ROOT / "app/bot/keyboards/inline.py").read_text(encoding="utf-8")
    assert "order:ack_delivery:" in orders
    assert "acknowledge_delivery" in service
    assert "confirm_activation" in service
    assert "أكد استلام البيانات أولاً" in service
    assert "استلمت بيانات الخدمة" in keyboards
    assert "جرّبت ونجح التفعيل" in keyboards


def test_orders_subscriptions_and_tickets_are_paginated() -> None:
    orders_service = (ROOT / "app/services/orders.py").read_text(encoding="utf-8")
    subscriptions_service = (
        ROOT / "app/services/student_subscriptions.py"
    ).read_text(encoding="utf-8")
    support_service = (ROOT / "app/services/support.py").read_text(encoding="utf-8")
    disputes_service = (ROOT / "app/services/disputes.py").read_text(encoding="utf-8")
    orders_handler = (ROOT / "app/bot/handlers/orders.py").read_text(encoding="utf-8")
    support_handler = (ROOT / "app/bot/handlers/support.py").read_text(encoding="utf-8")
    disputes_handler = (ROOT / "app/bot/handlers/disputes.py").read_text(encoding="utf-8")
    for token, source in (
        ("user_orders_page", orders_service),
        ("user_subscriptions_page", subscriptions_service),
        ("user_tickets_page", support_service),
        ("ticket_messages_page", support_service),
        ("user_disputes_page", disputes_service),
        ('Command("order")', orders_handler),
        ('Command("ticket")', support_handler),
        ('Command("dispute")', disputes_handler),
    ):
        assert token in source
    assert ".offset(page * page_size)" in orders_service
    assert ".offset(page * page_size)" in subscriptions_service
    assert support_service.count(".offset(page * page_size)") >= 2
    assert ".offset(safe_page * safe_size)" in disputes_service


def test_user_facing_statuses_have_central_arabic_labels() -> None:
    assert order_status_label("payment_review") == "قيد مراجعة الدفع"
    assert subscription_status_label("waiting_activation") == "بانتظار التفعيل"
    assert ticket_status_label("waiting_provider") == "بانتظار رد المنصة"
    assert provider_status_label("active") == "فعالة"
    assert dispute_status_label("under_review") == "قيد المراجعة"
    assert refund_status_label("transfer_reported") == "تم تسجيل التحويل"
    assert sender_role_label("admin") == "إدارة البوت"
    assert order_status_label("unexpected") == "غير معروف"
    assert "دقائق" in delivery_estimate_label("inventory_code")
    assert "24 ساعة" in delivery_estimate_label("manual")


def test_profile_completion_does_not_consume_edit_quota() -> None:
    start = (ROOT / "app/bot/handlers/start.py").read_text(encoding="utf-8")
    users = (ROOT / "app/services/users.py").read_text(encoding="utf-8")
    assert "count_edit=edit_mode" in start
    assert "if count_edit:" in users
    assert "profile.edit_count += 1" in users
    assert "user.profile.edit_count += 1" not in start


def test_phase4_navigation_and_project_memory_are_present() -> None:
    navigation = (ROOT / "app/bot/handlers/navigation.py").read_text(encoding="utf-8")
    assert '"subscriptions:categories"' in navigation
    assert '"tickets:mine"' in navigation
    assert '"disputes:mine"' in navigation
    for name in (
        "PHASE4_IMPLEMENTATION_REPORT_AR.md",
        "PHASE4_ACCEPTANCE_AR.md",
        "CHANGELOG_V6_8_PHASE4_AR.md",
        "PROJECT_STATE_AR.md",
        "ROADMAP_AR.md",
        "RUNBOOK_AR.md",
    ):
        assert (ROOT / name).is_file()
