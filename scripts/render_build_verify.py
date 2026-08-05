from __future__ import annotations

"""Render build-time verification for the current CampusPass release.

This verifier intentionally avoids network, Redis and database connections. It
checks the package that was copied into the Docker image and imports the actual
runtime graph after all dependencies are installed. Historical phase validators
remain in the repository for audit purposes, but they are not used as production
build gates because some of them pin old release identifiers literally.
"""

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fail(message: str) -> None:
    raise SystemExit(f"RENDER BUILD VERIFY FAILED: {message}")


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read(path: str) -> str:
    target = ROOT / path
    check(target.is_file(), f"required file is missing: {path}")
    return target.read_text(encoding="utf-8")


def verify_python_tree() -> int:
    count = 0
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if any(part in {".git", ".venv", "venv", "__pycache__"} for part in rel.parts):
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
        except SyntaxError as exc:
            fail(f"syntax error in {rel}:{exc.lineno}: {exc.msg}")
        count += 1
    check(count > 100, f"unexpectedly small Python tree ({count} files)")
    return count


def verify_state_references() -> tuple[int, int]:
    states_path = ROOT / "app/bot/states.py"
    tree = ast.parse(states_path.read_text(encoding="utf-8"), filename=str(states_path))
    groups: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        attributes: set[str] = set()
        for item in node.body:
            targets = []
            if isinstance(item, ast.Assign):
                targets = item.targets
            elif isinstance(item, ast.AnnAssign):
                targets = [item.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    attributes.add(target.id)
        groups[node.name] = attributes

    missing: list[str] = []
    references = 0
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel.parts and rel.parts[0] == "tests_legacy":
            continue
        try:
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
        except SyntaxError:
            continue
        for node in ast.walk(module):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in groups
            ):
                references += 1
                if node.attr not in groups[node.value.id]:
                    missing.append(f"{rel}:{node.lineno} -> {node.value.id}.{node.attr}")
    if missing:
        fail("undefined FSM state references: " + "; ".join(missing[:20]))
    check(
        "proof_guide" in groups.get("ProviderPaymentMethodStates", set()),
        "ProviderPaymentMethodStates.proof_guide is missing",
    )
    return len(groups), references


def module_file(module: str) -> Path | None:
    candidate = ROOT.joinpath(*module.split("."))
    if candidate.with_suffix(".py").is_file():
        return candidate.with_suffix(".py")
    init = candidate / "__init__.py"
    return init if init.is_file() else None


def verify_local_import_paths() -> int:
    missing: list[str] = []
    checked = 0
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel.parts and rel.parts[0] == "tests_legacy":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                if not name.startswith("app"):
                    continue
                checked += 1
                if module_file(name) is None:
                    missing.append(f"{rel}:{getattr(node, 'lineno', 0)} -> {name}")
    if missing:
        fail("missing local Python modules: " + "; ".join(missing[:20]))
    return checked


def verify_render_blueprint() -> dict[str, object]:
    text = read("render.production.yaml")
    required = (
        "type: web",
        "type: worker",
        "dockerfilePath: ./Dockerfile",
        "preDeployCommand: python ops/render_predeploy.py",
        "healthCheckPath: /health/ready",
        "value: bot",
        "value: worker",
    )
    for marker in required:
        check(marker in text, f"render.production.yaml is missing {marker!r}")

    # The user explicitly does not use an automated Mastercard gateway.
    check(
        text.count("- key: FEATURE_MASTERCARD") == 2,
        "FEATURE_MASTERCARD must be declared for Web and Worker",
    )
    check(
        text.count('value: "false"') >= 4,
        "expected disabled optional financial feature values are missing",
    )
    check(
        text.count("autoDeployTrigger: commit") == 2,
        "both services must deploy automatically on commits",
    )
    return {
        "web": "campuspass-v11-7-web" in text,
        "worker": "campuspass-v11-7-worker" in text,
        "mastercard_gateway": "disabled",
    }


def verify_runtime_imports() -> dict[str, object]:
    try:
        from app import __version__
        from app.core.release import release_tuple
    except Exception as exc:  # pragma: no cover - exercised in Docker
        fail(f"core release import failed: {type(exc).__name__}: {exc}")

    version_file = read("VERSION.txt").strip()
    check(version_file == __version__, f"VERSION.txt={version_file!r}, app={__version__!r}")
    try:
        release_tuple(__version__)
    except ValueError as exc:
        fail(str(exc))

    try:
        from app.db.migrations import MIGRATIONS
    except Exception as exc:
        fail(f"migration import failed: {type(exc).__name__}: {exc}")
    versions = [item.version for item in MIGRATIONS]
    check(bool(versions), "custom migration registry is empty")
    check(len(versions) == len(set(versions)), "duplicate custom migration versions")
    check(versions[-1] == __version__, f"migration head {versions[-1]!r} != app {__version__!r}")

    try:
        from app.core.config import Settings

        settings = Settings(
            _env_file=None,
            BOT_TOKEN="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
            ADMIN_IDS="1",
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            ENVIRONMENT="test",
            RUNTIME_MODE="bot",
            TELEGRAM_DELIVERY_MODE="polling",
            REQUIRE_EXTERNAL_DATABASE=False,
            REQUIRE_REDIS_IN_PRODUCTION=False,
            ENCRYPTION_KEY="render-build-verifier-encryption-key-0123456789abcdef",
            FEATURE_MASTERCARD=False,
            FEATURE_PROVIDER_WITHDRAWALS=False,
            BACKUP_ENABLED=False,
            EVIDENCE_EXTERNAL_STORAGE_ENABLED=False,
        )
    except Exception as exc:
        fail(f"Settings validation failed: {type(exc).__name__}: {exc}")
    check(not settings.mastercard_ready, "Mastercard must not be ready in the default package")
    check(
        not settings.provider_withdrawals_ready,
        "provider withdrawals must not be ready without a payment gateway",
    )

    try:
        from app.bot.handlers import build_router

        router = build_router()
    except Exception as exc:
        fail(f"handler/router import failed: {type(exc).__name__}: {exc}")
    subrouters = len(getattr(router, "sub_routers", []))
    check(subrouters >= 10, f"root router has too few subrouters ({subrouters})")

    # Import the real process entry points. No external calls happen at import time.
    try:
        import app.main  # noqa: F401
        import ops.render_predeploy  # noqa: F401
    except Exception as exc:
        fail(f"runtime entry-point import failed: {type(exc).__name__}: {exc}")

    try:
        from jinja2 import Environment, FileSystemLoader

        env = Environment(loader=FileSystemLoader(str(ROOT / "app/reports/templates")))
        for template in ("provider_daily.html", "provider_v5.html"):
            env.get_template(template)
    except Exception as exc:
        fail(f"report template validation failed: {type(exc).__name__}: {exc}")

    return {
        "version": __version__,
        "migration_count": len(versions),
        "router_subrouters": subrouters,
    }


def main() -> None:
    static_only = "--static-only" in sys.argv
    python_files = verify_python_tree()
    state_groups, state_references = verify_state_references()
    local_imports = verify_local_import_paths()
    blueprint = verify_render_blueprint()
    runtime = {"skipped": True} if static_only else verify_runtime_imports()

    dockerfile = read("Dockerfile")
    check(
        "python scripts/render_build_verify.py" in dockerfile,
        "Dockerfile is not using the current Render build verifier",
    )
    check(
        "python scripts/verify_v10_railway_turbo.py" not in dockerfile,
        "Dockerfile still executes the obsolete exact-version V10 build gate",
    )

    print(
        json.dumps(
            {
                "ok": True,
                "python_files": python_files,
                "state_groups": state_groups,
                "state_references": state_references,
                "local_app_imports_checked": local_imports,
                "blueprint": blueprint,
                "runtime": runtime,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
