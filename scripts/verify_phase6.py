from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import __version__
from app.core.release import require_release_at_least

required = [
    ROOT / "app/services/pilot.py",
    ROOT / "ops/pilot_validate.py",
    ROOT / "tests/test_v7_0_phase6_pilot_quality.py",
]
missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
if missing:
    raise SystemExit(f"Missing Phase 6 files: {missing}")
require_release_at_least(
    __version__, "7.0.0-pilot-quality-phase6", context="phase6 verification"
)
models = (ROOT / "app/db/models.py").read_text(encoding="utf-8")
for marker in ("cp_pilot_validation_runs", "cp_recovery_drills"):
    if marker not in models:
        raise SystemExit(f"Missing model marker: {marker}")
print(f"Phase 6 verification passed: release={__version__}")
