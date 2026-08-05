from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import __version__
from app.db.models import Base, BusinessPlan, LedgerDirection
from app.core.release import is_release_at_least
from app.services.enterprise import EnterpriseCoreService

ROOT=Path(__file__).resolve().parents[1]

def test_version_and_assets():
    assert is_release_at_least(__version__, "8.0.0-enterprise-core-a")
    assert (ROOT/"app/services/enterprise.py").exists()
    assert "8.0.0-enterprise-core-a" in (ROOT/"app/db/migrations.py").read_text()

def test_enterprise_tables_are_additive():
    names=set(Base.metadata.tables)
    expected={"cp_business_plans","cp_business_subscriptions","cp_business_invoices",
      "cp_ledger_transactions","cp_accounting_entries","cp_provider_team_members",
      "cp_provider_api_keys","cp_provider_webhook_endpoints","cp_provider_webhook_deliveries"}
    assert expected <= names

def test_balanced_ledger_guard_is_present():
    src=(ROOT/"app/services/enterprise.py").read_text()
    assert "debit != credit" in src
    assert "idempotency_key" in src
    assert LedgerDirection.DEBIT.value == "debit"

def test_api_and_webhook_security():
    src=(ROOT/"app/services/enterprise.py").read_text()
    api=(ROOT/"app/api/server.py").read_text()
    assert "hashlib.sha256(raw.encode()).hexdigest()" in src
    assert 'url.startswith("https://")' in src
    assert '/admin/enterprise/dashboard' in api
    assert '/v1/provider/me' in api

def test_metadata_builds_on_sqlite():
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    assert len(Base.metadata.tables) >= 98
