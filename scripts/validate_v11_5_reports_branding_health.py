from __future__ import annotations
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core.release import is_release_at_least

def require(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        raise SystemExit(f"missing: {path}")
    return target.read_text(encoding="utf-8", errors="ignore")

def main() -> None:
    if not is_release_at_least(require("VERSION.txt").strip(), "11.5.0"):
        raise SystemExit("invalid V11.5+ version")
    init = require("app/__init__.py")
    checks = {
        "branding assets": (ROOT / "app/reports/assets/campuspass-iq-horizontal-v11.png").exists() and (ROOT / "app/reports/assets/campuspass-iq-square-v11.png").exists(),
        "report tiers": "def free_message" in require("app/services/reports.py") and 'format="pdf"' in require("app/bot/handlers/provider.py"),
        "plus no csv": "CSV export was retired" in require("app/api/server.py"),
        "official pdf": "WeasyPrint" in require("app/services/report_artifacts.py"),
        "menu revision": "snapshot_revision" in require("app/services/menus.py"),
        "health metrics": "RuntimeMetricsService" in require("app/services/health.py"),
        "migration": "1150_reports_branding_health" in require("alembic/versions/1150_reports_branding_health.py"),
        "render": "campuspass-v11-" in require("render.production.yaml"),
        "version init": any(value in init for value in ("11.5.0-reports-branding-health", "11.6.0-render-e2e-hardening", "11.7.0-lts-turbo-update-safe", "11.7.1-all-features-ready")),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise SystemExit("V11.5 validation failed: " + ", ".join(failed))
    print(f"V11.5 validation passed: {len(checks)}/{len(checks)}")

if __name__ == "__main__":
    main()
