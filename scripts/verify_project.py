from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _literal_assignment(path: Path, name: str) -> Any:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.target if isinstance(node, ast.AnnAssign) else None
            targets = [target] if target is not None else list(node.targets)
            if any(isinstance(item, ast.Name) and item.id == name for item in targets):
                value = node.value
                if value is None:
                    break
                return ast.literal_eval(value)
    raise SystemExit(f"Could not find a literal assignment for {name} in {path}")


def _package_version() -> str:
    value = _literal_assignment(ROOT / "app" / "__init__.py", "__version__")
    if not isinstance(value, str):
        raise SystemExit("app.__version__ must be a literal string")
    return value


def main() -> None:
    version = _package_version()
    file_version = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    if file_version != version:
        raise SystemExit(f"Version mismatch: VERSION.txt={file_version}, app={version}")

    supported_actions = _literal_assignment(
        ROOT / "app" / "bot" / "handlers" / "menu.py", "SUPPORTED_MENU_ACTIONS"
    )
    default_menu = _literal_assignment(ROOT / "app" / "db" / "seed.py", "DEFAULT_MENU")
    if not isinstance(supported_actions, set) or not isinstance(default_menu, list):
        raise SystemExit("Menu verification constants must remain literal set/list values")

    keys = [row[0] for row in default_menu]
    texts = [row[1] for row in default_menu]
    actions = {row[2] for row in default_menu}
    if len(keys) != len(set(keys)):
        raise SystemExit("Duplicate default menu keys")
    if len(texts) != len(set(texts)):
        raise SystemExit("Duplicate default menu texts")
    missing = actions - supported_actions
    if missing:
        raise SystemExit(f"Menu actions without handlers: {sorted(missing)}")

    forbidden_legacy = [
        "app/config.py",
        "app/database.py",
        "app/models.py",
        "app/repositories.py",
        "app/keyboards.py",
        "app/middleware.py",
        "app/states.py",
        "app/handlers",
    ]
    present = [item for item in forbidden_legacy if (ROOT / item).exists()]
    if present:
        raise SystemExit(f"Legacy runtime files returned: {present}")

    print(f"CampusPass IQ {version}: project verification passed")


if __name__ == "__main__":
    main()
