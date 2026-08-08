from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import __version__
from app.core.release import require_release_at_least
from app.db.migrations import MIGRATIONS
from app.db.models import Base

BASELINE = "8.0.0-enterprise-scale-b"
required = {"cp_api_usage_events", "cp_api_usage_monthly", "cp_distributed_jobs", "cp_worker_heartbeats", "cp_webhook_delivery_attempts", "cp_subscription_lifecycle_events"}
require_release_at_least(__version__, BASELINE, context="phase7b verification")
if not required.issubset(set(Base.metadata.tables)):
    raise SystemExit(f"missing phase7b tables: {required - set(Base.metadata.tables)}")
if not any(m.version == BASELINE for m in MIGRATIONS):
    raise SystemExit("phase7b baseline migration is missing")
if not Path("app/services/enterprise_scale.py").exists():
    raise SystemExit("enterprise scale service is missing")
print(f"PHASE7B_OK release={__version__} tables={len(Base.metadata.tables)} migrations={len(MIGRATIONS)}")
