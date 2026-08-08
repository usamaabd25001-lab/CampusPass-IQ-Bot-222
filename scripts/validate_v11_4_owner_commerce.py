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
if not is_release_at_least(version, "11.4.0"):
    errors.append(f"wrong V11.4 version: {version}")

app_init = require("app/__init__.py")
for token in (
    'TELEGRAM_BOT_API_TARGET = "10.2"',
    'AIOGRAM_TARGET = "3.30.0"',
):
    if token not in app_init:
        errors.append(f"compatibility marker missing: {token}")

models = require("app/db/models.py")
for table in (
    "cp_financial_proof_registry",
    "cp_provider_billing_policies",
    "cp_business_invoice_proofs",
    "cp_owner_inbox_items",
    "cp_ad_campaigns",
    "cp_ad_campaign_recipients",
    "cp_coupon_campaigns",
    "cp_coupon_assignments",
    "cp_hybrid_bundles",
    "cp_hybrid_bundle_components",
    "cp_hybrid_bundle_purchases",
    "cp_hybrid_inventory_holds",
    "cp_hybrid_purchase_proofs",
    "cp_hybrid_revenue_allocations",
    "cp_reward_task_campaigns",
    "cp_reward_task_completions",
):
    if table not in models:
        errors.append(f"model table missing: {table}")

service = require("app/services/owner_commerce.py")
for token in (
    "issue_due_invoices",
    "enforce_overdue_billing",
    "sync_central_inbox",
    "create_ad_campaign",
    "dispatch_ad_campaign",
    "create_coupon_campaign",
    "create_hybrid_bundle",
    "create_hybrid_purchase",
    "HybridInventoryHold(",
    "expire_hybrid_purchases",
    "post_balanced_transaction",
    "create_reward_campaign",
    "reward_verified_student",
    "with_for_update(skip_locked=True)",
):
    if token not in service:
        errors.append(f"owner commerce engine missing: {token}")

handlers = require("app/bot/handlers/owner_commerce.py")
for token in (
    "provider:billing",
    "provider:ad_request",
    "provider:coupon_campaign",
    "provider:reward_new",
    "reward:tasks",
    "hybrid:list",
    "allow_paused: bool = False",
    "get_chat_member",
):
    if token not in handlers:
        errors.append(f"public commerce handler missing: {token}")

admin = require("app/bot/handlers/admin/owner_commerce.py")
for token in (
    "admin:owner_commerce",
    "admin:owner_billing",
    "admin:owner_inbox",
    "admin:owner_ads",
    "admin:hybrid_bundles",
    "admin:reward_campaigns",
):
    if token not in admin:
        errors.append(f"owner handler missing: {token}")

scheduler = require("app/tasks/scheduler.py")
for token in (
    "owner_commerce.expire_hybrid_purchases",
    "owner_commerce.process_ad_campaigns",
    "owner_commerce.sync_central_inbox",
    "owner_commerce.issue_due_invoices",
    "owner_commerce.enforce_overdue_billing",
):
    if token not in scheduler:
        errors.append(f"scheduler job missing: {token}")

migration = require("alembic/versions/1140_owner_commerce.py")
for token in (
    'revision = "1140_owner_commerce"',
    'down_revision = "1130_friends_warranty"',
    "uq_cp_business_invoice_proof_fingerprint",
    "uq_cp_owner_inbox_source",
    "uq_cp_ad_campaign_key",
    "uq_cp_coupon_assignment_user",
    "uq_cp_financial_proof_fingerprint",
    "uq_cp_hybrid_allocation_order",
    "uq_cp_reward_completion_user",
):
    if token not in migration:
        errors.append(f"migration guard missing: {token}")

requirements = json.loads(require("REQUIREMENTS_REGISTER.json") or "{}")
req_ids = {item.get("id") for item in requirements.get("requirements", [])}
for req_id in (
    "OWN-001", "OWN-002", "OWN-003", "OWN-007", "OWN-008", "OWN-009", "OWN-010",
    "PAY-004", "SEC-001", "SEC-002", "SEC-003", "SEC-004", "PERF-001", "PERF-002",
):
    if req_id not in req_ids:
        errors.append(f"requirement lost: {req_id}")

requirements_text = require("requirements.txt")
for pin in (
    "aiogram==3.30.0",
    "SQLAlchemy==2.0.51",
    "redis==8.1.0",
    "alembic==1.18.5",
):
    if pin not in requirements_text:
        errors.append(f"required pin missing: {pin}")

main = require("app/main.py")
for token in ("protocol=2", "ExponentialBackoff", "Retry("):
    if token not in main:
        errors.append(f"Redis guard missing: {token}")

render = require("render.production.yaml")
for token in (
    "campuspass-v11-",
    "type: web",
    "type: worker",
    "REQUIRE_REDIS_IN_PRODUCTION",
    'value: "true"',
):
    if token not in render:
        errors.append(f"Render production guard missing: {token}")

for directory in ROOT.rglob("*"):
    if directory.is_dir() and ".git" not in directory.parts:
        count = sum(1 for child in directory.iterdir() if child.is_file())
        if count > 100:
            errors.append(f"folder exceeds GitHub web limit: {directory.relative_to(ROOT)}={count}")

if not compileall.compile_dir(ROOT / "app", quiet=1):
    errors.append("app compileall failed")
if not compileall.compile_dir(ROOT / "alembic", quiet=1):
    errors.append("alembic compileall failed")

if errors:
    print("V11.4 validation FAILED")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)
print("V11.4 owner commerce validation PASSED")
