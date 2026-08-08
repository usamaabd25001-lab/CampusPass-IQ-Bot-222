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



if not is_release_at_least(require("VERSION.txt").strip(), "11.3.0"):  # additive compatibility
    errors.append("wrong inherited V11.3+ version")

models = require("app/db/models.py")
for table in (
    "cp_friend_package_configs",
    "cp_friend_groups",
    "cp_friend_group_members",
    "cp_friend_escrow_entries",
    "cp_warranty_policies",
    "cp_warranty_claims",
    "cp_warranty_claim_events",
    "cp_warranty_replacements",
):
    if table not in models:
        errors.append(f"missing model table: {table}")

friend_service = require("app/services/friend_packages.py")
for token in (
    "with_for_update(skip_locked=True)",
    "full_bot_fee_per_member = True",
    "FriendEscrowEntryType.DEPOSIT",
    "FriendEscrowEntryType.REFUND",
    "join_window_hours != 24",
    "friend_group_delivery",
):
    if token not in friend_service:
        errors.append(f"friend engine missing: {token}")
if ") + 1\n        group.paid_members" in friend_service:
    errors.append("friend paid-member double count regression")

warranty = require("app/services/warranties.py")
for token in (
    "provider_text_response",
    "WAITING_STUDENT_CONFIRMATION",
    "subscription.inventory_item_id = replacement.new_inventory_item_id",
    "ProviderInboxItemStatus.RESOLVED",
):
    if token not in warranty:
        errors.append(f"warranty engine missing: {token}")

handlers = require("app/bot/handlers/friends_warranty.py")
for token in (
    "friend:create:",
    "friend:join:",
    "p:frcustom:",
    "warranty:start:",
    "p:warotp:",
    "p:warrep:",
    "p:wartext:",
):
    if token not in handlers:
        errors.append(f"handler missing: {token}")

subscriptions = require("app/bot/handlers/subscriptions.py")
claim_block = subscriptions.split("subscription_code_from_warranty", 1)[-1]
if 'split(":")[3]' not in claim_block:
    errors.append("warranty OTP callback does not parse claim id safely")

scheduler = require("app/tasks/scheduler.py")
if "friend_packages.expire_groups" not in scheduler:
    errors.append("friend expiry job not registered")
elif scheduler.index("friend_packages.expire_groups") > scheduler.index("orders.expire_reservations"):
    errors.append("generic reservation expiry runs before friend escrow refund")

migration = require("alembic/versions/1130_friends_warranty.py")
for token in (
    'revision = "1130_friends_warranty"',
    'down_revision = "1120_provider_operations"',
    "uq_cp_warranty_active_subscription",
    "ck_cp_friend_group_paid",
):
    if token not in migration:
        errors.append(f"migration guard missing: {token}")

requirements = json.loads(require("REQUIREMENTS_REGISTER.json") or "{}")
items = {item.get("id"): item for item in requirements.get("requirements", [])}
for req_id in ("FRD-001", "FRD-002", "FRD-003", "FRD-004", "FRD-005", "WAR-001", "WAR-002", "WAR-003", "WAR-004", "WAR-005", "WAR-006"):
    if req_id not in items:
        errors.append(f"requirement lost: {req_id}")

requirements_text = require("requirements.txt")
if "alembic==1.18.5" not in requirements_text:
    errors.append("verified Alembic version is not pinned")
if "redis==8.1.0" not in requirements_text:
    errors.append("verified redis-py version is not pinned")
main_source = require("app/main.py")
for token in ("protocol=2", "ExponentialBackoff", "Retry("):
    if token not in main_source:
        errors.append(f"Redis compatibility/retry guard missing: {token}")

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
    print("V11.3 validation FAILED")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)
print("V11.3 friends + warranty validation PASSED")
