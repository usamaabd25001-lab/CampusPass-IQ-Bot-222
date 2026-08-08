from __future__ import annotations

import compileall
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def require(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        errors.append(f"missing: {path}")
        return ""
    return target.read_text(encoding="utf-8", errors="replace")


version = require("VERSION.txt").strip()
if version not in {"11.7.0-lts-turbo-update-safe", "11.7.1-all-features-ready"}:
    errors.append(f"wrong V11.7 version: {version}")

for path in (
    "app/domain/update_safety.py",
    "app/domain/callback_compat.py",
    "app/services/cache_coherence.py",
    "app/services/update_safety.py",
    "alembic/versions/1170_lts_turbo_update_safe.py",
    "tests/test_v11_7_lts_turbo.py",
):
    require(path)

models = require("app/db/models.py")
for table in ("cp_runtime_config_generations", "cp_release_compatibility"):
    if table not in models:
        errors.append(f"missing model table: {table}")

runtime = require("app/services/telegram_updates.py")
for token in (
    "claim_batch",
    "telegram_update_claim_batch_size",
    "context.update_wakeup",
    "telegram_update_graceful_shutdown_seconds",
    "with_for_update(skip_locked=True)",
):
    if token not in runtime:
        errors.append(f"turbo update runtime missing: {token}")

api = require("app/api/server.py")
for token in (
    "orjson.loads",
    "ORJSONResponse",
    "Deployment draining",
    "/admin/update/status",
    "update_inflight",
):
    if token not in api:
        errors.append(f"fast/update API missing: {token}")

main = require("app/main.py")
for token in (
    'http="httptools"',
    "CallbackCompatibilityOuterMiddleware",
    "update_safety.assert_compatible",
    "cache_coherence.ensure_defaults",
):
    if token not in main:
        errors.append(f"runtime integration missing: {token}")

requirements = require("requirements.txt")
for pin in ("orjson==3.11.9", "uvloop==0.22.1", "httptools==0.8.0"):
    if pin not in requirements:
        errors.append(f"performance dependency missing: {pin}")

migration = require("alembic/versions/1170_lts_turbo_update_safe.py")
for token in (
    'revision = "1170_lts_turbo_update_safe"',
    'down_revision = "1160_render_e2e_hardening"',
    "cp_runtime_config_generations",
    "cp_release_compatibility",
):
    if token not in migration:
        errors.append(f"migration guard missing: {token}")

registry = json.loads(require("REQUIREMENTS_REGISTER.json") or "{}")
ids = {item.get("id") for item in registry.get("requirements", [])}
for requirement_id in (
    "OPS-007",
    "OPS-008",
    "PERF-003",
    "PERF-004",
    "CFG-001",
    "CBK-001",
):
    if requirement_id not in ids:
        errors.append(f"requirement lost: {requirement_id}")

for directory in ROOT.rglob("*"):
    if directory.is_dir() and ".git" not in directory.parts:
        count = sum(1 for child in directory.iterdir() if child.is_file())
        if count > 100:
            errors.append(
                f"folder exceeds GitHub web limit: {directory.relative_to(ROOT)}={count}"
            )

for directory in ("app", "ops", "scripts", "alembic"):
    if not compileall.compile_dir(ROOT / directory, quiet=1):
        errors.append(f"{directory} compileall failed")

if errors:
    print("V11.7 validation FAILED")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)
print("V11.7 LTS turbo/update-safe validation PASSED")
