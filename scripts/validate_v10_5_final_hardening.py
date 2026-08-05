from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
HANDLERS = APP / "bot" / "handlers"


def _first_statement(node: ast.AsyncFunctionDef) -> ast.stmt | None:
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            body.pop(0)
    return body[0] if body else None


def _is_immediate_answer(statement: ast.stmt | None) -> bool:
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


def callback_handlers() -> list[tuple[Path, ast.AsyncFunctionDef]]:
    result: list[tuple[Path, ast.AsyncFunctionDef]] = []
    for path in HANDLERS.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if "callback" not in {item.arg for item in node.args.args}:
                continue
            if any(
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "callback_query"
                for dec in node.decorator_list
            ):
                result.append((path, node))
    return result


def main() -> None:
    version = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    assert version in {"10.5.0-final-hardening", "10.6.0-platform-access-referral", "10.7.0-emergency-stabilization"}

    handlers = callback_handlers()
    assert len(handlers) >= 300
    bad = [
        f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}"
        for path, node in handlers
        if not _is_immediate_answer(_first_statement(node))
    ]
    assert not bad, f"callbacks without immediate answer: {bad}"

    ui = (APP / "bot" / "ui.py").read_text(encoding="utf-8")
    inline = (APP / "bot" / "keyboards" / "inline.py").read_text(encoding="utf-8")
    main_source = (APP / "main.py").read_text(encoding="utf-8")
    middleware = (APP / "bot" / "middleware.py").read_text(encoding="utf-8")
    lifecycle = (APP / "services" / "offer_lifecycle.py").read_text(encoding="utf-8")
    announcements = (APP / "services" / "announcements.py").read_text(encoding="utf-8")
    menu = (APP / "bot" / "handlers" / "menu.py").read_text(encoding="utf-8")
    verifier = (ROOT / "scripts" / "verify_v10_railway_turbo.py").read_text(encoding="utf-8")
    migration = (ROOT / "alembic" / "versions" / "1050_final_hardening.py").read_text(encoding="utf-8")

    assert "with_navigation(reply_markup" in ui
    assert "validate_callback_markup" in ui
    assert "MAX_CALLBACK_BYTES" in inline
    assert "callback_size(value) > MAX_CALLBACK_BYTES" in inline
    assert "def navigable_keyboard(" in inline
    assert inline.count("@navigable_keyboard") >= 40
    assert "dp.include_router(callback_fallback_router)" in main_source
    assert "class FSMInputValidationMiddleware" in middleware
    assert "_PHOTO_OR_DOCUMENT_STATES" in middleware
    assert "All remaining FSM states are text-input states" in middleware
    assert "asyncio.timeout(0.60)" in middleware
    assert "if isinstance(event, CallbackQuery):\n            return await handler(event, data)" in middleware
    assert "update(InventoryItem)" in lifecycle
    assert "InventoryItem.offer_id.in_(inventory_offer_ids)" in lifecycle
    assert "ix_cp_provider_active_status" in migration
    assert "ix_cp_offer_lifecycle" in migration
    assert "ix_cp_inventory_lifecycle" in migration
    assert 'callback_payload("announcement", "open", action)' in announcements
    assert "await send_inline_menu(" in menu
    assert "sys.path.insert(0, str(ROOT))" in verifier

    print(f"V10.5 final hardening validation passed ({len(handlers)} callback handlers)")


if __name__ == "__main__":
    main()
