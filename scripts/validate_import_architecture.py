from __future__ import annotations

"""Static import-architecture gate for high-risk Telegram UI modules.

This gate catches two classes of defects that ordinary ``compileall`` cannot:

1. a ``name.py`` module shadowed by a sibling ``name/__init__.py`` package;
2. keyboard builders importing the UI runtime/handlers, which can create
   ``inline -> ui -> inline`` circular imports during package initialization.

It requires no third-party packages and therefore runs very early in Docker.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def fail(message: str) -> None:
    raise SystemExit(f"IMPORT ARCHITECTURE VALIDATION FAILED: {message}")


def check_module_package_collisions() -> int:
    collisions: list[str] = []
    checked = 0
    for py_file in APP.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        checked += 1
        package_dir = py_file.with_suffix("")
        if (package_dir / "__init__.py").is_file():
            collisions.append(str(py_file.relative_to(ROOT)))
    if collisions:
        fail(
            "module/package shadow collisions: "
            + ", ".join(collisions[:20])
        )
    return checked


def imports_for(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.lineno, node.module))
    return found


def check_keyboard_layering() -> int:
    violations: list[str] = []
    checked = 0
    keyboard_root = APP / "bot" / "keyboards"
    for path in keyboard_root.rglob("*.py"):
        checked += 1
        for lineno, module in imports_for(path):
            if module == "app.bot.ui" or module.startswith("app.bot.ui."):
                violations.append(
                    f"{path.relative_to(ROOT)}:{lineno} imports {module}"
                )
            if module == "app.bot.handlers" or module.startswith("app.bot.handlers."):
                violations.append(
                    f"{path.relative_to(ROOT)}:{lineno} imports {module}"
                )
    if violations:
        fail("keyboard dependency inversion: " + "; ".join(violations[:20]))
    return checked


def check_button_style_independence() -> None:
    path = APP / "bot" / "button_styles.py"
    if not path.is_file():
        fail("app/bot/button_styles.py is missing")
    forbidden = []
    for lineno, module in imports_for(path):
        if module.startswith("app.bot.ui") or module.startswith("app.bot.keyboards.inline"):
            forbidden.append(f"line {lineno}: {module}")
    if forbidden:
        fail("button style policy depends on UI/inline: " + "; ".join(forbidden))


def check_expected_shape() -> None:
    ui_module = APP / "bot" / "ui.py"
    ui_package = APP / "bot" / "ui" / "__init__.py"
    if not ui_module.is_file():
        fail("stable app/bot/ui.py facade is missing")
    if ui_package.exists():
        fail("app.bot.ui must not simultaneously exist as a package")

    inline = (APP / "bot" / "keyboards" / "inline.py").read_text(encoding="utf-8")
    if "from app.bot.button_styles import apply_button_style_policy" not in inline:
        fail("inline keyboard module is not using independent button style policy")


def main() -> None:
    check_expected_shape()
    collision_files = check_module_package_collisions()
    keyboard_files = check_keyboard_layering()
    check_button_style_independence()
    print(
        "Import architecture validation passed "
        f"({collision_files} modules checked, {keyboard_files} keyboard modules checked)"
    )


if __name__ == "__main__":
    main()
