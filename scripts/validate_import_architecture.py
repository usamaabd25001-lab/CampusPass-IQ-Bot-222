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


def _module_path(module: str) -> Path | None:
    candidate = ROOT.joinpath(*module.split("."))
    py_file = candidate.with_suffix(".py")
    if py_file.is_file():
        return py_file
    init_file = candidate / "__init__.py"
    return init_file if init_file.is_file() else None


def _top_level_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
    return names


def check_internal_imported_symbols() -> int:
    """Catch ``from app.x import MissingName`` without importing third parties."""
    cache: dict[Path, set[str]] = {}
    missing: list[str] = []
    checked = 0
    for source_path in APP.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
                and node.module.startswith("app")
            ):
                continue
            target = _module_path(node.module)
            if target is None:
                continue  # render_build_verify has the module-path gate.
            symbols = cache.setdefault(target, _top_level_symbols(target))
            for alias in node.names:
                if alias.name == "*":
                    continue
                checked += 1
                if alias.name not in symbols:
                    missing.append(
                        f"{source_path.relative_to(ROOT)}:{node.lineno} -> "
                        f"{node.module}.{alias.name}"
                    )
    if missing:
        fail("missing internal imported symbols: " + "; ".join(missing[:30]))
    return checked


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
    imported_symbols = check_internal_imported_symbols()
    keyboard_files = check_keyboard_layering()
    check_button_style_independence()
    print(
        "Import architecture validation passed "
        f"({collision_files} modules checked, {imported_symbols} imported symbols checked, "
        f"{keyboard_files} keyboard modules checked)"
    )


if __name__ == "__main__":
    main()
