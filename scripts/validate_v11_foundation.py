from __future__ import annotations

import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MINIMUM_REQUIREMENTS = 85
REQUIRED_DOCS = {
    "MASTER_SPEC.md",
    "REQUIREMENTS_REGISTER.json",
    "DECISION_LOG.md",
    "IMPLEMENTATION_ROADMAP.md",
    "ENGINEERING_HANDOFF_CHECKLIST.md",
}
REMOVED_RUNTIME_FILES = {
    "app/bot/handlers/disputes.py",
    "app/bot/handlers/privacy.py",
    "app/services/disputes.py",
    "app/services/privacy.py",
}
PROHIBITED_RUNTIME_TOKENS = {
    "services.disputes",
    "services.privacy",
    "DisputeService",
    "PrivacyService",
    'Command("disputes")',
}


def fail(message: str) -> None:
    raise SystemExit(f"V11 foundation validation failed: {message}")


def main() -> None:
    version = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    if not version.startswith("11."):
        fail(f"VERSION.txt is {version!r}")
    app_init = (ROOT / "app/__init__.py").read_text(encoding="utf-8")
    if f'__version__ = "{version}"' not in app_init:
        fail("app/__init__.py version mismatch")

    missing = [name for name in REQUIRED_DOCS if not (ROOT / name).is_file()]
    if missing:
        fail(f"missing governance documents: {missing}")

    registry = json.loads((ROOT / "REQUIREMENTS_REGISTER.json").read_text(encoding="utf-8"))
    requirements = registry.get("requirements", [])
    ids = [item.get("id") for item in requirements]
    if len(requirements) < MINIMUM_REQUIREMENTS or len(ids) != len(set(ids)):
        fail(f"requirements register must contain at least {MINIMUM_REQUIREMENTS} unique requirement IDs")

    existing_removed = [name for name in REMOVED_RUNTIME_FILES if (ROOT / name).exists()]
    if existing_removed:
        fail(f"removed runtime files still exist: {existing_removed}")

    runtime_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "app").rglob("*.py")
    )
    found = [token for token in PROHIBITED_RUNTIME_TOKENS if token in runtime_text]
    if found:
        fail(f"prohibited legacy runtime references: {found}")

    pricing = (ROOT / "app/services/pricing.py").read_text(encoding="utf-8")
    if "1 <= value < 250" not in pricing:
        fail("smart IQD parser threshold is not < 250")

    wallet = (ROOT / "app/services/wallets.py").read_text(encoding="utf-8")
    if "apply_service_fee_only" not in wallet or "Partial wallet deductions are forbidden" not in wallet:
        fail("wallet bot-fee-only rule is missing")

    for path in (ROOT / "app").rglob("*.py"):
        py_compile.compile(str(path), doraise=True)

    oversized = []
    for directory in [path for path in ROOT.rglob("*") if path.is_dir()]:
        count = sum(1 for child in directory.iterdir() if child.is_file())
        if count > 100:
            oversized.append((str(directory.relative_to(ROOT)), count))
    if oversized:
        fail(f"folders exceed GitHub web limit: {oversized}")

    print(f"V11 foundation OK: {len(requirements)} requirements, version {version}")


if __name__ == "__main__":
    main()
