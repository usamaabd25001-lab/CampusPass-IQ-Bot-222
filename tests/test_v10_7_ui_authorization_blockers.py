from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDLERS = ROOT / "app" / "bot" / "handlers"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_start_clears_aiogram_fsm_before_any_other_work() -> None:
    tree = ast.parse(read("app/bot/handlers/start.py"))
    handler = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "start_handler"
    )
    body = list(handler.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body.pop(0)
    assert ast.unparse(body[0]) == "await state.clear()"


def test_inline_transition_helper_uses_final_visible_remove_message() -> None:
    source = read("app/bot/ui.py")
    assert "async def send_inline_menu(" in source
    assert "ReplyKeyboardRemove()" in source
    assert "There is no deleted keyboard carrier" in source
    assert "source_message_id" in source
    menu = read("app/bot/handlers/menu.py")
    assert menu.count("await send_inline_menu(") >= 5


def test_explicit_back_routes_use_actor_id_and_render_before_cleanup() -> None:
    source = read("app/bot/handlers/navigation.py")
    assert 'F.data.in_({"back_to_main", "nav:home"})' in source
    assert 'F.data.in_({"back_to_platform", "provider:home"})' in source
    assert "telegram_id=callback.from_user.id" in source
    assert "rendered is not None" in source
    assert source.index("rendered = await _home") < source.index("await state.clear()", source.index("rendered = await _home"))
    assert 'back_callback="back_to_main"' in source
    inline = read("app/bot/keyboards/inline.py")
    assert 'callback_data="back_to_main"' in inline
    assert 'callback_data="back_to_platform"' in read("app/bot/handlers/provider.py")


def test_platform_authorization_is_warmed_and_refreshed_after_commit() -> None:
    access = read("app/services/platform_access.py")
    main = read("app/main.py")
    middleware = read("app/bot/middleware.py")
    catalog = read("app/bot/handlers/admin/catalog.py")
    assert "AUTHORIZED_PLATFORMS: set[str]" in access
    assert "return str(int(raw))" in access
    assert "_CONTEXT_CACHE" in access
    assert "async def resolve_provider_access" in access
    assert "await refresh_authorized_platforms(session)" in main
    assert "campuspass_platform_auth_dirty" in middleware
    assert "await session.commit()" in middleware
    assert "invalidate_provider_access_cache" in middleware
    assert "mark_platform_authorization_dirty(session" in catalog


def test_all_callback_handlers_still_acknowledge_once_at_entry() -> None:
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
            answers = sum(
                1
                for child in ast.walk(node)
                if isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == "callback"
                and child.func.attr == "answer"
            )
            if first != "await callback.answer()" or answers != 1:
                failures.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}")
    assert count >= 300
    assert failures == []
