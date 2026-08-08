from pathlib import Path
from app import __version__
from app.db.models import Base
root=Path(__file__).resolve().parent
assert __version__ == "8.0.0-enterprise-core-a"
required={"cp_business_plans","cp_business_subscriptions","cp_business_invoices","cp_ledger_transactions","cp_accounting_entries","cp_provider_team_members","cp_provider_api_keys","cp_provider_webhook_endpoints","cp_provider_webhook_deliveries"}
assert required <= set(Base.metadata.tables)
for path in [root/"app/services/enterprise.py", root/"PHASE7A_IMPLEMENTATION_REPORT_AR.md", root/"PHASE7A_ACCEPTANCE_AR.md"]: assert path.exists(), path
print(f"phase7a ok: {len(Base.metadata.tables)} tables")
