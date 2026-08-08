from __future__ import annotations

import ast
import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSIONS = {"11.1.0-student-commerce", "11.2.0-provider-operations", "11.3.0-friends-warranty", "11.4.0-owner-commerce", "11.5.0-reports-branding-health", "11.6.0-render-e2e-hardening", "11.7.0-lts-turbo-update-safe", "11.7.1-all-features-ready"}
EXPECTED_REQUIREMENTS = {
    "aiogram": "3.30.0",
    "SQLAlchemy": "2.0.51",
    "asyncpg": "0.31.0",
    "fastapi": "0.128.2",
    "redis": "8.1.0",
}
REQUIRED_FILES = {
    "app/core/telegram_webapp.py",
    "app/services/webapp_profile.py",
    "app/domain/student_commerce.py",
    "app/services/student_commerce.py",
    "app/api/templates/student_profile.html",
    "alembic/versions/1110_student_commerce.py",
    "tests/test_v11_1_student_commerce.py",
}


def fail(message: str) -> None:
    raise SystemExit(f"V11.1 student-commerce validation failed: {message}")


def parse_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        pins[name.split("[")[0]] = version.strip()
    return pins


def module_exists(module: str) -> bool:
    relative = Path(*module.split("."))
    return (ROOT / f"{relative}.py").is_file() or (ROOT / relative / "__init__.py").is_file()


def main() -> None:
    version = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    if version not in EXPECTED_VERSIONS:
        fail(f"VERSION.txt is {version!r}")

    app_init = (ROOT / "app/__init__.py").read_text(encoding="utf-8")
    for expected in (
        f'__version__ = "{version}"',
        'TELEGRAM_BOT_API_TARGET = "10.2"',
        'AIOGRAM_TARGET = "3.30.0"',
    ):
        if expected not in app_init:
            fail(f"missing compatibility marker: {expected}")

    missing = sorted(path for path in REQUIRED_FILES if not (ROOT / path).is_file())
    if missing:
        fail(f"missing files: {missing}")

    registry = json.loads((ROOT / "REQUIREMENTS_REGISTER.json").read_text(encoding="utf-8"))
    requirements = registry.get("requirements", [])
    ids = [item.get("id") for item in requirements]
    if len(requirements) < 85 or len(ids) != len(set(ids)):
        fail("requirements register must retain at least 85 unique requirement IDs")

    pins = parse_pins()
    for package, expected in EXPECTED_REQUIREMENTS.items():
        if pins.get(package) != expected:
            fail(f"{package} pin is {pins.get(package)!r}; expected {expected}")

    domain = (ROOT / "app/domain/student_commerce.py").read_text(encoding="utf-8")
    for token in (
        "def calculate_invoice(",
        "def net_wallet_fee_deduction(",
        "wallet_balance >= bot_fee",
        "def profile_completion(",
    ):
        if token not in domain:
            fail(f"student commerce domain token missing: {token}")

    commerce_service = (ROOT / "app/services/student_commerce.py").read_text(encoding="utf-8")
    if "merged_metadata.update(metadata)" not in commerce_service:
        fail("checkout metadata must be merged instead of replaced")
    if "net_wallet_fee_deduction(" not in commerce_service:
        fail("checkout snapshot does not use the net wallet debit")

    payment_service = (ROOT / "app/services/payments.py").read_text(encoding="utf-8")
    if "current_bot_fee_iqd=int(order.service_fee_iqd or 0)" not in payment_service:
        fail("payment confirmation can misreport a refunded wallet fee")
    if "صورة الوصل مستخدمة في طلب آخر" not in payment_service:
        fail("receipt duplicate protection is missing")

    catalog_handler = (ROOT / "app/bot/handlers/catalog.py").read_text(encoding="utf-8")
    if "profile_complete, _missing" not in catalog_handler or "profile_webapp_keyboard(" not in catalog_handler:
        fail("direct store access is not protected by the complete-profile gate")
    if "message.from_user.id if message.from_user else message.chat.id" in catalog_handler:
        fail("purchase identity may fall back to chat_id")

    payment_handler = (ROOT / "app/bot/handlers/payments.py").read_text(encoding="utf-8")
    if payment_handler.count("services.payments.can_review(") < 2:
        fail("payment confirm/reject prompts are not both authorization-gated")

    seed = (ROOT / "app/db/seed.py").read_text(encoding="utf-8")
    if '("favorites", "❤️ مفضلاتي",' not in seed:
        fail("final favorites label was not seeded")

    webapp = (ROOT / "app/api/templates/student_profile.html").read_text(encoding="utf-8")
    for field in ("full_name", "phone", "governorate", "university", "college", "department", "stage"):
        if f'id="{field}"' not in webapp:
            fail(f"profile Web App field missing: {field}")
    if "X-Telegram-Init-Data" not in webapp:
        fail("Web App does not send signed Telegram initData")

    alembic = (ROOT / "alembic/versions/1110_student_commerce.py").read_text(encoding="utf-8")
    for table in (
        "cp_student_favorites",
        "cp_provider_working_hours",
        "cp_checkout_snapshots",
        "cp_payment_amount_confirmations",
        "cp_student_reward_statuses",
    ):
        if table not in alembic:
            fail(f"Alembic migration missing table: {table}")

    missing_modules: set[str] = set()
    for path in (ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app"):
                if not module_exists(node.module):
                    missing_modules.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app") and not module_exists(alias.name):
                        missing_modules.add(alias.name)
    if missing_modules:
        fail(f"missing internal modules: {sorted(missing_modules)}")

    for path in list((ROOT / "app").rglob("*.py")) + list((ROOT / "alembic").rglob("*.py")):
        py_compile.compile(str(path), doraise=True)

    oversized: list[tuple[str, int]] = []
    for directory in (path for path in ROOT.rglob("*") if path.is_dir()):
        count = sum(1 for child in directory.iterdir() if child.is_file())
        if count > 100:
            oversized.append((str(directory.relative_to(ROOT)), count))
    if oversized:
        fail(f"folders exceed GitHub web limit: {oversized}")

    print(
        "V11.1 student commerce OK: "
        f"{len(requirements)} requirements, Telegram Bot API 10.2, aiogram 3.30.0"
    )


if __name__ == "__main__":
    main()
