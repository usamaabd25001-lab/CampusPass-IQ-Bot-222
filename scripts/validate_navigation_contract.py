from __future__ import annotations

"""Static navigation regression gate.

Back and Home are different contracts. Back must not be implemented as Home in
reusable keyboards, and Mini App wizards must keep a real one-step history.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"NAVIGATION CONTRACT VALIDATION FAILED: {message}")


def require(source: str, marker: str, where: str) -> None:
    if marker not in source:
        fail(f"{where} missing {marker!r}")


def check_inline_buttons() -> int:
    root = ROOT / "app" / "bot"
    violations: list[str] = []
    checked = 0
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            fail(f"syntax error in {path.relative_to(ROOT)}:{exc.lineno}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name != "InlineKeyboardButton":
                continue
            checked += 1
            values: dict[str, str] = {}
            for kw in node.keywords:
                if kw.arg in {"text", "callback_data"} and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    values[kw.arg] = kw.value.value
            label = values.get("text", "")
            callback = values.get("callback_data", "")
            if "رجوع" in label and callback in {"back_to_main", "nav:home"}:
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno} Back routes to Home")
    if violations:
        fail("; ".join(violations[:30]))
    return checked


def check_webapps() -> None:
    provider = (ROOT / "app/api/templates/admin_provider.html").read_text(encoding="utf-8")
    offer = (ROOT / "app/api/templates/provider_offer.html").read_text(encoding="utf-8")
    require(provider, "function goBack()", "provider Web App")
    require(provider, "tg.BackButton.onClick(goBack)", "provider Web App")
    require(provider, "localStorage", "provider Web App")
    require(offer, "function goBack()", "offer Web App")
    require(offer, "history.pop()", "offer branch history")
    require(offer, "history.push(current)", "offer branch history")
    require(offer, "tg.BackButton.onClick(goBack)", "offer Web App")
    if "tg.close()" in offer.split("function goBack()", 1)[1].split("function goNext()", 1)[0]:
        fail("offer Back closes the Web App instead of moving one step")


def main() -> None:
    count = check_inline_buttons()
    check_webapps()
    print(f"Navigation contract validation passed ({count} inline buttons checked)")


if __name__ == "__main__":
    main()
