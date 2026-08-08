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
if version not in {"11.2.0-provider-operations", "11.3.0-friends-warranty", "11.4.0-owner-commerce", "11.5.0-reports-branding-health", "11.6.0-render-e2e-hardening", "11.7.0-lts-turbo-update-safe", "11.7.1-all-features-ready"}:
    errors.append(f"wrong inherited version: {version}")

models = require("app/db/models.py")
for table in (
    "cp_provider_terms_acceptances",
    "cp_provider_offer_fulfillment_profiles",
    "cp_provider_payment_method_configs",
    "cp_provider_inbox_items",
    "cp_provider_inbox_events",
    "cp_student_activation_requests",
    "cp_student_code_relays",
    "cp_otp_account_leases",
    "cp_temporary_logout_proofs",
    "cp_student_operational_restrictions",
):
    if table not in models:
        errors.append(f"model table missing: {table}")

migration = require("alembic/versions/1120_provider_operations.py")
if 'revision = "1120_provider_operations"' not in migration:
    errors.append("alembic revision missing")

router = require("app/bot/handlers/__init__.py")
for token in ("provider_operations.router", "student_fulfillment.router"):
    if token not in router:
        errors.append(f"router not registered: {token}")

main = require("app/main.py")
if "OperationalRestrictionMiddleware" not in main:
    errors.append("operational restriction middleware not registered")

payments = require("app/bot/handlers/payments.py")
if "ProviderInboxKind.PAYMENT_PROOF" not in payments:
    errors.append("payment proof is not linked to provider inbox")

email_codes = require("app/services/email_codes.py")
for token in ("acquire_otp_lease", "otp_account_lease_seconds", "يرجى الانتظار لثوانٍ معدودة"):
    if token not in email_codes:
        errors.append(f"OTP integration missing: {token}")

scheduler = require("app/tasks/scheduler.py")
for token in ("temporary_access_tick", "temporary_logout_grace_minutes"):
    if token not in scheduler:
        errors.append(f"temporary account scheduler missing: {token}")

requirements_path = ROOT / "REQUIREMENTS_REGISTER.json"
if requirements_path.exists():
    data = json.loads(requirements_path.read_text(encoding="utf-8"))
    if len(data.get("requirements", [])) < 85:
        errors.append("requirements register lost entries")

for directory in ROOT.rglob("*"):
    if directory.is_dir() and ".git" not in directory.parts:
        count = sum(1 for child in directory.iterdir() if child.is_file())
        if count > 100:
            errors.append(f"folder exceeds 100 files: {directory.relative_to(ROOT)}={count}")

if not compileall.compile_dir(ROOT / "app", quiet=1):
    errors.append("app compileall failed")
if not compileall.compile_dir(ROOT / "alembic", quiet=1):
    errors.append("alembic compileall failed")

if errors:
    print("V11.2 validation FAILED")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)
print("V11.2 provider operations validation PASSED")
