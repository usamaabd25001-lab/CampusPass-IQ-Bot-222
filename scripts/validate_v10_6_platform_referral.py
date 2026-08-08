from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.release import require_release_at_least

APP = ROOT / "app"
HANDLERS = APP / "bot" / "handlers"
BASELINE_VERSION = "10.6.0-platform-access-referral"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _callback_handlers() -> list[tuple[Path, ast.AsyncFunctionDef]]:
    result: list[tuple[Path, ast.AsyncFunctionDef]] = []
    for path in HANDLERS.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if "callback" not in {arg.arg for arg in node.args.args}:
                continue
            if any(
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "callback_query"
                for dec in node.decorator_list
            ):
                result.append((path, node))
    return result


def _body_without_docstring(node: ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body.pop(0)
    return body


def _is_callback_answer(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Await)
        and isinstance(statement.value.value, ast.Call)
        and isinstance(statement.value.value.func, ast.Attribute)
        and isinstance(statement.value.value.func.value, ast.Name)
        and statement.value.value.func.value.id == "callback"
        and statement.value.value.func.attr == "answer"
        and not statement.value.value.args
        and not statement.value.value.keywords
    )


def _callback_answer_count(node: ast.AsyncFunctionDef) -> int:
    count = 0
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        func = item.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "callback"
            and func.attr == "answer"
        ):
            count += 1
    return count


def main() -> None:
    version = read("VERSION.txt").strip()
    require_release_at_least(
        version, BASELINE_VERSION, context="V10.6 platform/referral validation"
    )
    assert f'__version__ = "{version}"' in read("app/__init__.py")

    handlers = _callback_handlers()
    assert len(handlers) >= 300
    bad_first: list[str] = []
    bad_count: list[str] = []
    for path, node in handlers:
        body = _body_without_docstring(node)
        label = f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}"
        if not body or not _is_callback_answer(body[0]):
            bad_first.append(label)
        if _callback_answer_count(node) != 1:
            bad_count.append(label)
    assert not bad_first, f"Callback handlers without immediate callback.answer(): {bad_first}"
    assert not bad_count, f"Callback handlers with zero/multiple callback.answer(): {bad_count}"

    handlers_init = read("app/bot/handlers/__init__.py")
    main_source = read("app/main.py")
    seed = read("app/db/seed.py")
    menus = read("app/services/menus.py")
    menu_handler = read("app/bot/handlers/menu.py")
    assert "privacy," not in handlers_init
    assert 'Command("privacy")' not in main_source
    assert 'Command("my_data")' not in main_source
    assert 'key="privacy"' not in seed
    assert 'item.action != "privacy"' in menus
    assert 'item.action == "privacy"' in menus

    ui = read("app/bot/ui.py")
    start = read("app/bot/handlers/start.py")
    assert "ReplyKeyboardRemove()" in ui
    assert "async def remove_reply_keyboard_temporarily" in ui
    assert "async def install_reply_keyboard_temporarily" in ui
    assert "async def send_reply_menu" in ui
    assert "reply_markup=reply_markup" in ui
    assert "await send_reply_menu(" in start
    assert "deleted carrier" in ui

    access = read("app/services/platform_access.py")
    provider = read("app/bot/handlers/provider.py")
    inline = read("app/bot/keyboards/inline.py")
    models = read("app/db/models.py")
    assert "def normalize_telegram_user_id" in access
    assert "async def is_platform_authorized" in access
    assert ".join(ProviderStaff" in access and ".join(Provider" in access
    assert "has_platform_access: Mapped[bool]" in models
    assert 'F.data == "provider:terms:accept"' in provider
    assert 'F.data == "provider:terms:reject"' in provider
    assert "user.has_platform_access = True" in provider
    assert 'callback_data="provider:terms:accept"' in inline
    assert 'callback_data="provider:terms:reject"' in inline
    assert "resolve_provider_access(" in menus
    assert "self.settings.is_admin(user.telegram_id)" in menus
    assert 'item.action != "provider_dashboard"' in menus
    assert 'item.action != "admin_dashboard"' in menus

    finance = read("app/services/finance.py")
    config = read("app/core/config.py")
    points_view = menu_handler
    assert "referral:success:" in finance
    assert "referral:coupon:" not in finance
    assert "OrderCouponType.FEE_WAIVER.value" not in finance
    assert "referral_reward_points" in finance
    assert "self.wallets.post" not in finance
    assert "WalletEntryType.REFERRAL" not in finance
    assert 'default=10, alias="REFERRAL_REWARD_POINTS"' in config
    assert 'default=0, alias="REFERRAL_WALLET_REWARD_IQD"' in config
    assert "نظام الحالة والمكافآت" in points_view
    assert "من دون بطاقات إعفاء متراكمة" in points_view

    branding = read("app/services/branding.py")
    provider_catalog = read("app/bot/handlers/provider_catalog.py")
    admin_catalog = read("app/bot/handlers/admin/catalog.py")
    assert "provider.logo_file_id = candidate.file_id" in branding
    assert "ImageModerationService" in branding
    assert "httpx" not in branding
    assert "await self.moderation.ensure_safe(raw)" in branding
    assert "message.photo[-1]" in provider_catalog
    assert "message.photo[-1]" in admin_catalog
    assert "save_url(" not in provider_catalog
    assert "save_url(" not in admin_catalog

    middleware = read("app/bot/middleware.py")
    assert "CallbackNavigationStateMiddleware" in middleware
    assert "Leave state transitions to the destination handlers" in middleware
    assert "FSMInputValidationMiddleware" in middleware

    migration = read("alembic/versions/1060_platform_access_referral_cleanup.py")
    assert 'down_revision = "1050_final_hardening"' in migration
    assert '"has_platform_access"' in migration
    assert "ix_cp_users_has_platform_access" in migration
    assert "referrals.invites_per_coupon" in migration
    assert "referrals.wallet_reward_iqd" in migration

    # Validate every literal callback payload. Dynamic payloads are protected by
    # validate_callback_markup at runtime and by compact numeric IDs.
    literal_payloads: list[tuple[str, str]] = []
    pattern = re.compile(r"callback_data\s*=\s*([\"'])(.*?)\1")
    for path in APP.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for match in pattern.finditer(source):
            literal_payloads.append((str(path.relative_to(ROOT)), match.group(2)))
    oversized = [
        f"{path}:{value!r} ({len(value.encode('utf-8'))} bytes)"
        for path, value in literal_payloads
        if len(value.encode("utf-8")) > 64
    ]
    assert not oversized, f"Oversized literal callback_data values: {oversized}"
    assert "MAX_CALLBACK_BYTES" in inline
    assert "MAX_CALLBACK_BYTES = 64" in read("app/bot/callbacks.py")
    assert "validate_callback_markup" in inline

    print(
        "V10.6 platform access/referral validation passed "
        f"({len(handlers)} callback handlers, {len(literal_payloads)} literal payloads)"
    )


if __name__ == "__main__":
    main()
