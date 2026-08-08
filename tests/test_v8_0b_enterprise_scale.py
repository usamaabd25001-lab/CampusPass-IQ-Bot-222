from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
aiosqlite = pytest.importorskip("aiosqlite")
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.security import SecretBox
from app.db.models import Base, DistributedJobStatus
from app.services.enterprise_scale import EnterpriseScaleService


def settings():
    return SimpleNamespace(enterprise_job_lease_seconds=60, enterprise_job_max_backoff_seconds=3600,
        enterprise_job_base_backoff_seconds=10, runtime_mode="worker", release_id="test",
        enterprise_webhook_timeout_seconds=1, enterprise_webhook_max_attempts=3,
        enterprise_webhook_base_backoff_seconds=10, enterprise_webhook_max_backoff_seconds=60,
        enterprise_grace_days=7, enterprise_worker_stale_seconds=120)

@pytest.mark.asyncio
async def test_distributed_jobs_are_idempotent_and_leased():
    engine=create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    maker=async_sessionmaker(engine, expire_on_commit=False)
    service=EnterpriseScaleService(settings(), SecretBox(SimpleNamespace(encryption_key="x"*32, encryption_keyring=(), bot_token="test", report_secret_key="", encryption_key_version=1)))
    async with maker() as session:
        a=await service.enqueue_job(session, queue_name="webhooks", job_type="deliver", payload={"x":1}, idempotency_key="same")
        b=await service.enqueue_job(session, queue_name="webhooks", job_type="deliver", payload={"x":2}, idempotency_key="same")
        assert a.id == b.id
        claimed=await service.claim_jobs(session, queue_name="webhooks", worker_id="w1")
        assert len(claimed)==1 and claimed[0].status==DistributedJobStatus.LEASED.value
        await service.finish_job(session, claimed[0], success=True, result={"ok":True})
        assert claimed[0].status==DistributedJobStatus.SUCCEEDED.value
    await engine.dispose()


def test_webhook_signature_is_deterministic_and_body_bound():
    service=EnterpriseScaleService(settings(), SecretBox(SimpleNamespace(encryption_key="x"*32, encryption_keyring=(), bot_token="test", report_secret_key="", encryption_key_version=1)))
    one=service.webhook_signature("secret","123",b'{"a":1}')
    two=service.webhook_signature("secret","123",b'{"a":1}')
    three=service.webhook_signature("secret","123",b'{"a":2}')
    assert one==two and one!=three and len(one)==64
