from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_navigation_footer_and_payload_guard_are_centralized() -> None:
    inline = read("app/bot/keyboards/inline.py")
    ui = read("app/bot/ui.py")
    assert "def with_navigation(" in inline
    assert "Existing back/home buttons are preserved and never duplicated" in inline
    assert 'text="↩️ رجوع"' in inline
    assert 'text="🏠 الرئيسية"' in inline
    assert "callback_size(value) > MAX_CALLBACK_BYTES" in inline
    assert "reply_markup = with_navigation(" in ui
    assert "reply_markup = validate_callback_markup(" in ui


def test_unknown_callback_fallback_is_last_and_preserves_fsm() -> None:
    source = read("app/main.py")
    assert source.index("await load_plugins(dp, context)") < source.index(
        "dp.include_router(callback_fallback_router)"
    )
    fallback = read("app/bot/handlers/fallback.py")
    tree = ast.parse(fallback)
    handler = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef))
    body = list(handler.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    assert ast.unparse(body[0]) == "await callback.answer()"
    assert "state.clear" not in fallback
    assert "edit_or_send" in fallback


def test_menu_actions_use_in_place_renderer_for_inline_navigation() -> None:
    source = read("app/bot/handlers/menu.py")
    start = source.index("async def execute_menu_action")
    body = source[start:]
    assert "async def render(" in body
    assert "await edit_or_send(" in body
    assert "show_profile(message, session, services, user, in_place=in_place)" in body
    assert "show_points(message, session, services, user, in_place=in_place)" in body


def test_fsm_validation_and_indexed_lifecycle_are_wired() -> None:
    middleware = read("app/bot/middleware.py")
    main = read("app/main.py")
    lifecycle = read("app/services/offer_lifecycle.py")
    models = read("app/db/models.py")
    assert "class FSMInputValidationMiddleware" in middleware
    assert "dp.message.middleware(FSMInputValidationMiddleware())" in main
    assert "update(InventoryItem)" in lifecycle
    assert "Offer.end_at <= now" in lifecycle
    assert "InventoryItem.offer_id.in_(inventory_offer_ids)" in lifecycle
    assert '"ix_cp_offer_lifecycle"' in models
    assert '"ix_cp_inventory_lifecycle"' in models


def test_release_and_build_verifier_target_final_hardening() -> None:
    assert read("VERSION.txt").strip() == "10.7.0-emergency-stabilization"
    verifier = read("scripts/verify_v10_railway_turbo.py")
    dockerfile = read("Dockerfile")
    assert 'EXPECTED_VERSION = "10.7.0-emergency-stabilization"' in verifier
    assert "validate_v10_5_final_hardening.py" in dockerfile
    migration = read("alembic/versions/1050_final_hardening.py")
    assert 'down_revision = "1040_commerce_referral_payments"' in migration


def test_callbacks_are_not_queued_before_acknowledgement() -> None:
    middleware = read("app/bot/middleware.py")
    assert "if isinstance(event, CallbackQuery):\n            return await handler(event, data)" in middleware
    assert "asyncio.timeout(0.60)" in middleware
    assert "Banned-user lookup failed" in middleware


def test_fsm_default_is_text_only_and_media_states_are_explicit() -> None:
    middleware = read("app/bot/middleware.py")
    for marker in (
        "_PHOTO_ONLY_STATES",
        "_PHOTO_OR_URL_STATES",
        "_PHOTO_OR_DOCUMENT_STATES",
        "_MEDIA_ONLY_STATES",
        "_MEDIA_OR_TEXT_STATES",
    ):
        assert marker in middleware
    assert "All remaining FSM states are text-input states" in middleware
    assert "هذه الخطوة تقبل نصًا فقط" in middleware


def test_docker_verifier_can_import_project_from_script_path() -> None:
    verifier = read("scripts/verify_v10_railway_turbo.py")
    assert "ROOT = Path(__file__).resolve().parents[1]" in verifier
    assert "sys.path.insert(0, str(ROOT))" in verifier


def test_announcements_and_custom_media_fail_closed() -> None:
    announcements = read("app/services/announcements.py")
    menu = read("app/bot/handlers/menu.py")
    assert 'callback_payload("announcement", "open", action)' in announcements
    assert "except CallbackPayloadError" in announcements
    assert "await send_inline_menu(" in menu


def test_reusable_keyboards_and_grid_builders_are_dead_end_safe() -> None:
    inline = read("app/bot/keyboards/inline.py")
    assert "def navigable_keyboard(" in inline
    assert inline.count("@navigable_keyboard") >= 40
    assert "return with_navigation(factory(*args, **kwargs))" in inline
    provider_catalog = read("app/bot/handlers/provider_catalog.py")
    admin_v5 = read("app/bot/handlers/admin/v5.py")
    assert "return with_navigation(InlineKeyboardMarkup(inline_keyboard=rows))" in provider_catalog
    assert "return with_navigation(InlineKeyboardMarkup(inline_keyboard=rows))" in admin_v5
