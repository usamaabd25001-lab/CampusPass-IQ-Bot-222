from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
HANDLERS = APP / "bot" / "handlers"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_privacy_buttons_commands_and_router_are_disabled() -> None:
    seed = read("app/db/seed.py")
    menu = read("app/bot/handlers/menu.py")
    menus = read("app/services/menus.py")
    handlers = read("app/bot/handlers/__init__.py")
    main = read("app/main.py")
    assert 'key="privacy"' not in seed
    assert '"privacy"' not in menu.split("SUPPORTED_MENU_ACTIONS", 1)[1].split("}", 1)[0]
    assert "privacy," not in handlers
    assert 'Command("privacy")' not in main
    assert 'Command("my_data")' not in main
    assert 'item.action != "privacy"' in menus
    assert 'item.action == "privacy"' in menus


def test_reply_inline_transition_uses_deleting_temporary_message() -> None:
    ui = read("app/bot/ui.py")
    start = read("app/bot/handlers/start.py")
    assert "async def delete_safely" in ui
    assert "async def remove_reply_keyboard_temporarily" in ui
    assert "ReplyKeyboardRemove()" in ui
    assert "async def install_reply_keyboard_temporarily" in ui
    assert "There is no deleted keyboard carrier" in ui
    assert "async def send_reply_menu" in ui
    assert "await send_reply_menu(" in start


def test_referral_cash_is_replaced_by_coupon_every_three_successes() -> None:
    finance = read("app/services/finance.py")
    config = read("app/core/config.py")
    menu = read("app/bot/handlers/menu.py")
    assert "completed_count == 1" in finance
    assert "referral:success:" in finance
    assert "referral:coupon:" in finance
    assert "OrderCouponType.FEE_WAIVER.value" in finance
    assert "referral_invites_per_coupon" in finance
    assert "self.wallets.post" not in finance
    assert "WalletEntryType.REFERRAL" not in finance
    assert 'default=0, alias="REFERRAL_WALLET_REWARD_IQD"' in config
    assert 'default=3, alias="REFERRAL_INVITES_PER_COUPON"' in config
    assert "لا يُضاف رصيد مالي للمحفظة" in menu


def test_platform_tos_gate_is_persistent_and_one_time() -> None:
    models = read("app/db/models.py")
    provider = read("app/bot/handlers/provider.py")
    inline = read("app/bot/keyboards/inline.py")
    assert "has_platform_access: Mapped[bool]" in models
    assert "ProviderAccessFailure.TERMS_REQUIRED" in provider
    assert "user.has_platform_access = True" in provider
    assert 'F.data == "provider:terms:accept"' in provider
    assert 'F.data == "provider:terms:reject"' in provider
    assert 'callback_data="provider:terms:accept"' in inline
    assert 'callback_data="provider:terms:reject"' in inline


def test_main_menu_permissions_are_strict() -> None:
    menus = read("app/services/menus.py")
    assert 'item.action != "provider_dashboard"' in menus
    assert "platform_allowed" in menus
    assert 'item.action != "admin_dashboard"' in menus
    assert "self.settings.is_admin(user.telegram_id)" in menus
    assert "resolve_provider_access(" in menus


def test_aiogram_fsm_navigation_interceptor_replaces_telebot_step_clear() -> None:
    middleware = read("app/bot/middleware.py")
    main = read("app/main.py")
    assert "class CallbackNavigationStateMiddleware" in middleware
    assert "Leave state transitions to the destination handlers" in middleware
    navigation = read("app/bot/handlers/navigation.py")
    assert "BACK_MAP" in navigation and "await state.clear()" in navigation
    assert "dp.callback_query.middleware(CallbackNavigationStateMiddleware())" in main
    assert "FSMInputValidationMiddleware" in middleware


def test_platform_authorization_normalizes_id_and_uses_one_query() -> None:
    source = read("app/services/platform_access.py")
    tree = ast.parse(source)
    function_names = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "normalize_telegram_user_id" in function_names
    assert "is_platform_authorized" in function_names
    assert "return str(int(raw))" in source
    assert "AUTHORIZED_PLATFORMS: set[str]" in source
    assert "refresh_authorized_platforms" in source
    assert "normalized in AUTHORIZED_PLATFORMS" in source
    assert ".join(ProviderStaff" in source
    assert ".join(Provider" in source


def test_platform_logo_is_saved_from_largest_telegram_photo_only() -> None:
    branding = read("app/services/branding.py")
    provider = read("app/bot/handlers/provider_catalog.py")
    admin = read("app/bot/handlers/admin/catalog.py")
    middleware = read("app/bot/middleware.py")
    assert "provider.logo_file_id = candidate.file_id" in branding
    assert "ImageModerationService" not in branding
    assert "ensure_safe" not in branding
    assert "httpx" not in branding
    assert "message.photo[-1]" in provider
    assert "message.photo[-1]" in admin
    assert "ProviderBrandingStates.logo.state" in middleware
    assert "AdminProviderLogoStates.logo.state" in middleware


def test_v10_6_migrations_and_build_guards_are_wired() -> None:
    migration = read("alembic/versions/1060_platform_access_referral_cleanup.py")
    custom = read("app/db/migrations.py")
    docker = read("Dockerfile")
    assert read("VERSION.txt").strip() == "10.7.0-emergency-stabilization"
    assert 'down_revision = "1050_final_hardening"' in migration
    assert "ix_cp_users_has_platform_access" in migration
    assert "referrals.invites_per_coupon" in migration
    assert 'version="10.6.0-platform-access-referral-cleanup"' in custom
    assert "validate_v10_6_platform_referral.py" in docker
    assert "validate_v10_7_emergency_stabilization.py" in docker


def test_all_callbacks_still_acknowledge_exactly_once() -> None:
    failures: list[str] = []
    count = 0
    for path in HANDLERS.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if "callback" not in {arg.arg for arg in node.args.args}:
                continue
            if not any(
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "callback_query"
                for dec in node.decorator_list
            ):
                continue
            count += 1
            body = list(node.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body.pop(0)
            first = ast.unparse(body[0]) if body else ""
            answer_count = sum(
                1
                for child in ast.walk(node)
                if isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == "callback"
                and child.func.attr == "answer"
            )
            if first != "await callback.answer()" or answer_count != 1:
                failures.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}")
    assert count >= 300
    assert failures == []
