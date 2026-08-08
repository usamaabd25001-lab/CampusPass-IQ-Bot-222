from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"

CRITICAL_FILES = (
    "app/main.py",
    "app/bot/processing.py",
    "app/bot/handlers/provider_catalog.py",
    "app/bot/handlers/subscriptions.py",
    "app/services/email_codes.py",
    "app/services/student_subscriptions.py",
    "app/services/workflows.py",
    "app/services/health.py",
    "app/services/direct_support.py",
    "app/services/data_protection.py",
    "app/services/owner_commerce.py",
    "app/bot/handlers/owner_commerce.py",
    "app/bot/handlers/admin/owner_commerce.py",
    "app/db/migrations.py",
    "app/db/models.py",
)


def module_name(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def main() -> int:
    missing_files = [item for item in CRITICAL_FILES if not (ROOT / item).is_file()]
    if missing_files:
        print("ERROR: incomplete CampusPass repository. Missing required files:")
        for item in missing_files:
            print(f" - {item}")
        print("Upload the complete CampusPass V11.4 repository before deploying.")
        return 1

    python_files = sorted(APP.rglob("*.py"))
    modules = {module_name(path) for path in python_files}
    missing_imports: list[tuple[str, int, str]] = []
    syntax_errors: list[tuple[str, str]] = []

    for path in python_files:
        relative = str(path.relative_to(ROOT))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except SyntaxError as exc:
            syntax_errors.append((relative, str(exc)))
            continue

        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.append(node.module)

            for imported in names:
                if not imported.startswith("app."):
                    continue
                exists = imported in modules or any(
                    name.startswith(imported + ".") for name in modules
                )
                if not exists:
                    missing_imports.append((relative, node.lineno, imported))

    if syntax_errors:
        print("ERROR: Python syntax errors detected:")
        for file_name, error in syntax_errors:
            print(f" - {file_name}: {error}")
        return 1

    if missing_imports:
        print("ERROR: local Python imports point to missing repository files:")
        for file_name, line, imported in missing_imports:
            print(f" - {file_name}:{line} -> {imported}")
        return 1

    print(
        f"Runtime repository verification passed: {len(python_files)} Python files, "
        f"{len(modules)} local modules."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
