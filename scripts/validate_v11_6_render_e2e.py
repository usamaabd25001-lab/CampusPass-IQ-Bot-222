from __future__ import annotations

import compileall
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core.release import is_release_at_least
errors: list[str] = []


def require(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        errors.append(f"missing: {path}")
        return ""
    return target.read_text(encoding="utf-8", errors="replace")


version = require("VERSION.txt").strip()
if not is_release_at_least(version, "11.6.0"):
    errors.append(f"wrong V11.6 version: {version}")

models = require("app/db/models.py")
for table in ("cp_telegram_update_inbox", "cp_deployment_gate_runs"):
    if table not in models:
        errors.append(f"missing model table: {table}")

service = require("app/services/telegram_updates.py")
for token in (
    "with_for_update(skip_locked=True)",
    "payload_sha256",
    "TelegramUpdateRuntime",
    "dispatcher.feed_update",
    "max_attempts",
):
    if token not in service:
        errors.append(f"durable Telegram intake missing: {token}")

api = require("app/api/server.py")
for token in (
    "X-Telegram-Bot-Api-Secret-Token",
    "telegram_updates.enqueue",
    "telegram_webhook_body_limit_bytes",
    "secrets.compare_digest",
    "/health/deep",
    "/admin/deployment/gates/latest",
):
    if token not in api:
        errors.append(f"API hardening missing: {token}")

main = require("app/main.py")
for token in (
    "bot.set_webhook",
    "TelegramUpdateRuntime",
    "deployment_gate_wait_seconds",
    "telegram_delivery_mode == \"webhook\"",
):
    if token not in main:
        errors.append(f"runtime integration missing: {token}")

migration = require("alembic/versions/1160_render_e2e_hardening.py")
for token in (
    'revision = "1160_render_e2e_hardening"',
    'down_revision = "1150_reports_branding_health"',
    "uq_cp_telegram_update_id",
    "ix_cp_deployment_gate_status_started",
):
    if token not in migration:
        errors.append(f"migration guard missing: {token}")

for path in ("render.yaml", "render.production.yaml"):
    render = require(path)
    for token in (
        "preDeployCommand: python ops/render_predeploy.py",
        "healthCheckPath: /health/ready",
        "autoDeployTrigger: checksPass",
        "TELEGRAM_DELIVERY_MODE",
        "DEPLOYMENT_GATE_STRICT",
    ):
        if token not in render:
            errors.append(f"{path} missing: {token}")

for path in ("ops/render_predeploy.py", "ops/render_smoke.py"):
    require(path)

requirements = json.loads(require("REQUIREMENTS_REGISTER.json") or "{}")
req_ids = {item.get("id") for item in requirements.get("requirements", [])}
for req_id in ("OPS-001", "OPS-002", "OPS-003", "OPS-004", "OPS-005", "OPS-006"):
    if req_id not in req_ids:
        errors.append(f"requirement lost: {req_id}")

for directory in ROOT.rglob("*"):
    if directory.is_dir() and ".git" not in directory.parts:
        count = sum(1 for child in directory.iterdir() if child.is_file())
        if count > 100:
            errors.append(f"folder exceeds GitHub web limit: {directory.relative_to(ROOT)}={count}")

if not compileall.compile_dir(ROOT / "app", quiet=1):
    errors.append("app compileall failed")
if not compileall.compile_dir(ROOT / "ops", quiet=1):
    errors.append("ops compileall failed")
if not compileall.compile_dir(ROOT / "alembic", quiet=1):
    errors.append("alembic compileall failed")

if errors:
    print("V11.6 validation FAILED")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)
print("V11.6 Render + E2E hardening validation PASSED")
