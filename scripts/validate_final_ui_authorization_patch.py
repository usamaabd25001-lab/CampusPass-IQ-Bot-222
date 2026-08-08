from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDLERS = ROOT / "app" / "bot" / "handlers"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def validate_callbacks() -> int:
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
    if count < 300 or failures:
        raise SystemExit(f"Callback acknowledgement validation failed count={count} failures={failures}")
    return count


def main() -> None:
    start = read("app/bot/handlers/start.py")
    navigation = read("app/bot/handlers/navigation.py")
    ui = read("app/bot/ui.py")
    inline = read("app/bot/keyboards/inline.py")
    access = read("app/services/platform_access.py")
    middleware = read("app/bot/middleware.py")
    main_source = read("app/main.py")

    assert "async def start_handler" in start and "await state.clear()" in start
    assert "async def send_inline_menu(" in ui
    assert "ReplyKeyboardRemove()" in ui
    assert "async def send_reply_menu" in ui
    assert "There is no deleted keyboard carrier" in ui
    assert 'F.data.in_({"back_to_main", "nav:home"})' in navigation
    assert 'F.data.in_({"back_to_platform", "provider:home"})' in navigation
    assert "telegram_id=callback.from_user.id" in navigation
    assert 'callback_data="back_to_main"' in inline
    assert "AUTHORIZED_PLATFORMS: set[str]" in access
    assert "return str(int(raw))" in access
    assert "async def resolve_provider_access" in access
    assert "ProviderAccessContext" in access
    assert "await refresh_authorized_platforms(session)" in main_source
    assert "campuspass_platform_auth_dirty" in middleware
    assert "invalidate_provider_access_cache" in middleware

    callback_count = validate_callbacks()
    print(f"Final UI/authorization patch validation passed callbacks={callback_count}")


if __name__ == "__main__":
    main()
