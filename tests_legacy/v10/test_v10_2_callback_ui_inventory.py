from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
HANDLERS = APP / "bot" / "handlers"


def _callback_handlers() -> list[tuple[Path, ast.AsyncFunctionDef]]:
    handlers: list[tuple[Path, ast.AsyncFunctionDef]] = []
    for path in HANDLERS.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if "callback" not in {arg.arg for arg in node.args.args}:
                continue
            is_handler = any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "callback_query"
                for decorator in node.decorator_list
            )
            if is_handler:
                handlers.append((path, node))
    return handlers


def _first_executable_statement(node: ast.AsyncFunctionDef) -> ast.stmt | None:
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body.pop(0)  # function docstring is not an executable Telegram operation
    return body[0] if body else None


def _is_callback_answer(statement: ast.stmt | None) -> bool:
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Await):
        return False
    call = statement.value.value
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "callback"
        and call.func.attr == "answer"
        and not call.args
        and not call.keywords
    )


def _conservative_callback_size(value: ast.expr) -> int | None:
    """Estimate the maximum payload using 64-bit decimal IDs and short enum tokens."""

    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return len(value.value.encode("utf-8"))
    if not isinstance(value, ast.JoinedStr):
        return None

    total = 0
    for part in value.values:
        if isinstance(part, ast.Constant):
            total += len(str(part.value).encode("utf-8"))
            continue
        if not isinstance(part, ast.FormattedValue):
            return None
        expression = ast.unparse(part.value)
        if "token(" in expression or "TOKENS[" in expression:
            total += 3
        elif (
            expression.endswith(".id")
            or expression.endswith("_id")
            or expression in {"page", "page - 1", "page + 1", "rating"}
        ):
            total += 19
        else:
            # Controlled action/filter/mode values are deliberately bounded below 24 bytes.
            total += 24
    return total


def test_every_callback_acknowledges_before_other_executable_work() -> None:
    handlers = _callback_handlers()
    assert len(handlers) >= 290
    failures = [
        f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}"
        for path, node in handlers
        if not _is_callback_answer(_first_executable_statement(node))
    ]
    assert failures == []


def test_callback_payloads_fit_telegram_64_byte_limit() -> None:
    failures: list[str] = []
    checked = 0
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.keyword) or node.arg != "callback_data":
                continue
            size = _conservative_callback_size(node.value)
            if size is None:
                continue
            checked += 1
            if size > 64:
                failures.append(
                    f"{path.relative_to(ROOT)}:{node.lineno} estimates {size} bytes: "
                    f"{ast.unparse(node.value)}"
                )
    assert checked >= 250
    assert failures == []


def test_callback_query_is_answered_only_once_per_handler() -> None:
    failures: list[str] = []
    for path, node in _callback_handlers():
        answer_calls = [
            child
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and isinstance(child.func.value, ast.Name)
            and child.func.value.id == "callback"
            and child.func.attr == "answer"
        ]
        if len(answer_calls) != 1:
            failures.append(
                f"{path.relative_to(ROOT)}:{node.lineno}:{node.name} has {len(answer_calls)} answers"
            )
    assert failures == []


def test_callback_menus_do_not_send_duplicate_messages_directly() -> None:
    failures = []
    for path in HANDLERS.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "callback.message.answer(" in source:
            failures.append(str(path.relative_to(ROOT)))
    assert failures == []


def test_runtime_polling_lease_is_modelled_migrated_and_used() -> None:
    model = (APP / "db" / "models.py").read_text(encoding="utf-8")
    runtime = (APP / "core" / "runtime_lock.py").read_text(encoding="utf-8")
    main = (APP / "main.py").read_text(encoding="utf-8")
    migration = (ROOT / "alembic" / "versions" / "1020_callback_ui_inventory.py").read_text(
        encoding="utf-8"
    )
    assert 'class RuntimeLease' in model
    assert 'cp_runtime_leases' in model
    assert 'class RuntimeLeaseGuard' in runtime
    assert 'with_for_update()' in runtime
    assert 'RuntimeLeaseGuard(' in main
    assert 'await polling_lease.acquire' in main
    assert 'await polling_lease.release' in main
    assert 'cp_runtime_leases' in migration


def test_in_place_rendering_has_race_lock_and_single_fallback() -> None:
    source = (APP / "bot" / "ui.py").read_text(encoding="utf-8")
    assert "_RENDER_LOCKS" in source
    assert "async with _render_lock(message)" in source
    assert "message.edit_text" in source
    assert "message.edit_caption" in source
    assert "message.edit_reply_markup" in source
    assert "async def callback_notice(" in source
    assert "replacement = await message.answer" in source
    assert "await message.delete()" in source


def test_compact_grid_and_integrated_store_tree_are_present() -> None:
    keyboards = (APP / "bot" / "keyboards" / "inline.py").read_text(encoding="utf-8")
    provider_catalog = (HANDLERS / "provider_catalog.py").read_text(encoding="utf-8")
    assert "def admin_dashboard_keyboard" in keyboards
    assert "two actions per row" in keyboards
    assert "🛍 متجري والعروض" in keyboards
    assert "➕ إضافة عرض جديد" in provider_catalog
    assert "📋 عروضي" in provider_catalog
    assert "🗂 تنظيم المتجر" in provider_catalog
    assert 'callback_data="p:oe"' in provider_catalog
    assert 'callback_data=f"p:cred:{offer.id}"' in provider_catalog
    assert 'callback_data=f"p:stop:{offer.id}"' in provider_catalog
    assert "reactivate_after_inventory" in provider_catalog
    assert "استبدلت ببيانات اعتماد مجددة" in provider_catalog


def test_branding_is_mandatory_before_offer_creation_and_report_ready() -> None:
    provider_catalog = (HANDLERS / "provider_catalog.py").read_text(encoding="utf-8")
    admin_catalog = (HANDLERS / "admin" / "catalog.py").read_text(encoding="utf-8")
    branding = (APP / "services" / "branding.py").read_text(encoding="utf-8")
    reports = (APP / "services" / "reports.py").read_text(encoding="utf-8")
    assert "if not services.branding.has_logo(staff.provider)" in provider_catalog
    assert "رفع شعار المنصة خطوة إلزامية" in provider_catalog
    assert "provider:branding" in provider_catalog
    assert "AdminProviderLogoStates.logo" in admin_catalog
    assert "لا يمكن تفعيل المنصة قبل رفع شعارها" in admin_catalog
    assert "provider.logo_file_id = candidate.file_id" in branding
    assert "ImageModerationService" not in branding
    assert "provider_logo" in reports or "logo_file_id" in reports


def test_ui_sync_helpers_cover_core_state_toggles() -> None:
    plan_source = (HANDLERS / "admin" / "plans.py").read_text(encoding="utf-8")
    subscription_source = (HANDLERS / "admin" / "subscriptions.py").read_text(
        encoding="utf-8"
    )
    provider_source = (HANDLERS / "provider_catalog.py").read_text(encoding="utf-8")
    admin_catalog = (HANDLERS / "admin" / "catalog.py").read_text(encoding="utf-8")
    assert "await _render_plan_details(callback.message, plan)" in plan_source
    assert "await _render_plan_features(callback.message, session, plan.id)" in plan_source
    assert "await _render_subscription_details(callback.message, provider, subscription, percent)" in subscription_source
    assert "await _render_feature_overrides(callback.message, session, services, provider.id)" in subscription_source
    assert "await _render_expired_offers(callback.message, session, staff)" in provider_source
    assert "await _render_admin_provider(callback.message" in admin_catalog


def test_railway_verifier_targets_v10_3_release() -> None:
    verifier = (ROOT / "scripts" / "verify_v10_railway_turbo.py").read_text(encoding="utf-8")
    assert 'EXPECTED_VERSION = "10.7.0-emergency-stabilization"' in verifier
    assert '"RuntimeLeaseGuard("' in verifier
    assert '"await polling_lease.acquire"' in verifier
    assert '"app/bot/ui.py"' in verifier
    assert '"app/services/branding.py"' in verifier


def test_v10_3_offer_lifecycle_and_promotion_catalog_are_wired() -> None:
    lifecycle = (APP / "services" / "offer_lifecycle.py").read_text(encoding="utf-8")
    scheduler = (APP / "tasks" / "scheduler.py").read_text(encoding="utf-8")
    catalog = (APP / "services" / "catalog.py").read_text(encoding="utf-8")
    provider_catalog = (HANDLERS / "provider_catalog.py").read_text(encoding="utf-8")
    templates = (APP / "services" / "templates.py").read_text(encoding="utf-8")
    assert "async def run_cycle" in lifecycle
    assert "offer.price_iqd = int(offer.original_price_iqd" in lifecycle
    assert "OfferStatus.OUT_OF_STOCK.value" in lifecycle
    assert '"offer_lifecycle"' in scheduler
    assert "async def promotion_categories" in catalog
    assert "if featured_only" in catalog
    assert "ProviderOfferStates.promotion_end" in provider_catalog
    assert '"offer.launched"' in templates


def test_v10_6_logo_upload_bypasses_external_verification() -> None:
    branding = (APP / "services" / "branding.py").read_text(encoding="utf-8")
    provider_catalog = (HANDLERS / "provider_catalog.py").read_text(encoding="utf-8")
    admin_catalog = (HANDLERS / "admin" / "catalog.py").read_text(encoding="utf-8")
    assert "provider.logo_file_id = candidate.file_id" in branding
    assert "ImageModerationService" not in branding
    assert "ensure_safe" not in branding
    assert "httpx" not in branding
    assert "message.photo[-1]" in provider_catalog
    assert "message.photo[-1]" in admin_catalog


def test_v10_3_direct_credential_update_preserves_offer_and_sales_history() -> None:
    provider_catalog = (HANDLERS / "provider_catalog.py").read_text(encoding="utf-8")
    states = (APP / "bot" / "states.py").read_text(encoding="utf-8")
    assert "class ProviderCredentialUpdateStates" in states
    assert 'callback_data=f"p:ciu:{item.id}"' in provider_catalog
    assert "credential_update_finish" in provider_catalog
    assert "item.encrypted_payload =" in provider_catalog
    assert "fingerprint_row.fingerprint" in provider_catalog
    assert "session.delete(offer)" not in provider_catalog[provider_catalog.index("credential_update_finish"):provider_catalog.index("@router.callback_query(F.data == \"provider:branding\")")]


def test_v10_3_fsm_navigation_has_single_callback_owner() -> None:
    middleware = (APP / "bot" / "middleware.py").read_text(encoding="utf-8")
    navigation = (HANDLERS / "navigation.py").read_text(encoding="utf-8")
    provider = (HANDLERS / "provider.py").read_text(encoding="utf-8")
    provider_catalog = (HANDLERS / "provider_catalog.py").read_text(encoding="utf-8")
    assert "class CallbackNavigationStateMiddleware" in middleware
    assert "active_state_callback_interrupt" not in navigation
    assert "async def _staff_for_provider" in provider
    assert "_staff_for_provider(" in provider_catalog
