from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
HANDLERS = APP / "bot" / "handlers"
EXPECTED_VERSION = "10.7.0-emergency-stabilization"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def callback_handlers() -> list[tuple[Path, ast.AsyncFunctionDef, str]]:
    result: list[tuple[Path, ast.AsyncFunctionDef, str]] = []
    for path in HANDLERS.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if "callback" not in {arg.arg for arg in node.args.args}:
                continue
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "callback_query"
                ):
                    route = "|".join(ast.unparse(arg) for arg in decorator.args) or "<catch-all>"
                    result.append((path, node, route))
    return result


def callback_answer_is_first_and_unique(node: ast.AsyncFunctionDef) -> bool:
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body.pop(0)
    if not body or ast.unparse(body[0]) != "await callback.answer()":
        return False
    answers = [
        item
        for item in ast.walk(node)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and isinstance(item.func.value, ast.Name)
        and item.func.value.id == "callback"
        and item.func.attr == "answer"
    ]
    return len(answers) == 1


def main() -> None:
    assert read("VERSION.txt").strip() == EXPECTED_VERSION
    assert f'__version__ = "{EXPECTED_VERSION}"' in read("app/__init__.py")

    handlers = callback_handlers()
    assert len(handlers) >= 300
    bad_ack = [
        f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}"
        for path, node, _route in handlers
        if not callback_answer_is_first_and_unique(node)
    ]
    assert not bad_ack, f"callback acknowledgement failures: {bad_ack}"

    # Exact duplicate filter expressions are dispatcher-order bugs. Legacy aliases
    # must live on one canonical handler rather than two competing routers.
    owners: dict[str, list[str]] = {}
    for path, node, route in handlers:
        owners.setdefault(route, []).append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}")
    duplicate_routes = {
        route: values
        for route, values in owners.items()
        if route != "<catch-all>" and len(values) > 1
    }
    assert not duplicate_routes, f"duplicate callback routes: {duplicate_routes}"

    ui = read("app/bot/ui.py")
    start = read("app/bot/handlers/start.py")
    navigation = read("app/bot/handlers/navigation.py")
    assert "async def transition_lock" in ui
    assert "async def send_reply_menu" in ui
    assert "final visible Home/submenu message with its ReplyKeyboard attached" in ui
    assert "There is no deleted keyboard carrier" in ui
    assert "await send_reply_menu(" in start
    assert 'F.data.in_({"back_to_main", "nav:home"})' in navigation
    assert 'F.data.in_({"back_to_platform", "provider:home"})' in navigation
    assert "callback.from_user.id" in navigation
    assert "BACK_MAP" in navigation
    assert "rendered is not None" in navigation

    access = read("app/services/platform_access.py")
    assert "class ProviderAccessContext" in access
    assert "class ProviderActorRole" in access
    assert "ProviderActorRole.SUPER_ADMIN" in access
    assert "ProviderActorRole.OWNER" in access
    assert "frozenset(PERMISSION_NAMES)" in access
    assert "ProviderAccessFailure.STALE_CONTEXT" in access
    assert "ProviderAccessFailure.STAFF_PAUSED" in access
    assert "selectable_memberships" in access
    assert "invalidate_provider_access_cache" in access
    assert "set_active_provider_selection" in access

    menus = read("app/services/menus.py")
    provider = read("app/bot/handlers/provider.py")
    permissions = read("app/bot/permissions.py")
    authorization = read("app/services/authorization.py")
    for source in (menus, provider, permissions, authorization):
        assert "resolve_provider_access" in source
    assert 'item.action != "provider_dashboard"' in menus
    assert 'item.action != "admin_dashboard"' in menus

    catalog = read("app/bot/handlers/provider_catalog.py")
    assert "➕ إضافة عرض جديد" in catalog
    assert "📋 عروضي" in catalog
    assert "🗂 تنظيم المتجر" in catalog
    assert "provider:offer_new_section" in catalog
    assert "provider:offer_service_new:" in catalog
    assert "provider:branding" not in catalog[catalog.index("async def _catalog_overview"):catalog.index("async def _offer_status_counts")]

    branding = read("app/services/branding.py")
    moderation = read("app/services/image_moderation.py")
    config = read("app/core/config.py")
    assert "provider.logo_file_id = candidate.file_id" in branding
    assert "SUPPORTED_FORMATS" in branding
    assert "MAX_LOGO_BYTES" in branding
    assert "validate_photo" in branding and "save_candidate" in branding
    assert "httpx" not in branding
    assert "google_vision" not in branding.lower()
    assert "vision.googleapis.com" not in branding.lower()
    assert "network call is ever required" in moderation
    assert 'default="disabled", alias="IMAGE_MODERATION_PROVIDER"' in config
    assert 'default=False, alias="IMAGE_MODERATION_FAIL_CLOSED"' in config

    templates = read("app/services/templates.py")
    admin_customization = read("app/bot/handlers/admin/customization.py")
    assert '"start.welcome"' in templates
    assert "_welcome_cache" in templates
    assert "validate_telegram_html" in templates
    assert 'parsed.scheme.lower() not in {"http", "https", "tg", "mailto"}' in templates
    assert "admin:start_message" in admin_customization
    assert "reset_welcome" in admin_customization

    migration = read("alembic/versions/1070_emergency_stabilization.py").lower()
    upgrade_source = migration.split("def downgrade", 1)[0]
    for forbidden in ("drop_table", "truncate", "delete from cp_", "create_table(\"cp_provider_staff\""):
        assert forbidden not in upgrade_source
    assert "add_column" in upgrade_source
    assert "def downgrade" in migration
    assert "backfill" in migration

    literal_pattern = re.compile(r"callback_data\s*=\s*([\"'])(.*?)\1")
    payloads: list[str] = []
    for path in APP.rglob("*.py"):
        payloads.extend(match.group(2) for match in literal_pattern.finditer(path.read_text(encoding="utf-8")))
    oversized = [value for value in payloads if len(value.encode("utf-8")) > 64]
    assert not oversized, oversized

    railway = json.loads(read("railway.json"))
    assert railway["deploy"]["healthcheckPath"] == "/health/live"
    assert railway["deploy"]["overlapSeconds"] == 0
    assert "validate_v10_7_emergency_stabilization.py" in read("Dockerfile")
    print(
        "V10.7 emergency stabilization validation passed "
        f"callbacks={len(handlers)} routes={len(owners)} literal_payloads={len(payloads)}"
    )


if __name__ == "__main__":
    main()
