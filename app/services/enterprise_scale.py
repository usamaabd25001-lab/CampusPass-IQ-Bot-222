from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import socket
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import SecretBox
from app.db.models import (
    ApiUsageEvent, ApiUsageMonthlyAggregate, BusinessInvoiceStatus, BusinessPlan,
    BusinessSubscription, BusinessSubscriptionStatus, DistributedJob,
    DistributedJobStatus, ProviderWebhookDelivery, ProviderWebhookEndpoint,
    SubscriptionLifecycleEvent, WebhookDeliveryAttempt, WebhookDeliveryStatus,
    WorkerHeartbeat,
)


class EnterpriseScaleService:
    """Durable, idempotent scale layer safe for multiple concurrent workers."""

    def __init__(self, settings, secret_box: SecretBox) -> None:
        self.settings = settings
        self.secret_box = secret_box

    @staticmethod
    def period_key(at: datetime | None = None) -> str:
        return (at or datetime.now(UTC)).strftime("%Y-%m")

    async def usage_limit(self, session: AsyncSession, provider_id: int) -> int:
        row = await session.execute(
            select(BusinessSubscription, BusinessPlan)
            .join(BusinessPlan, BusinessPlan.id == BusinessSubscription.plan_id)
            .where(BusinessSubscription.provider_id == provider_id)
        )
        item = row.first()
        if not item:
            return 0
        subscription, plan = item
        return int(subscription.api_requests_override or plan.included_api_requests or 0)

    async def record_usage(self, session: AsyncSession, *, provider_id: int, api_key_id: int | None,
                           route: str, idempotency_key: str, units: int = 1,
                           status_code: int = 200) -> dict:
        if units <= 0:
            raise ValueError("usage units must be positive")
        existing = await session.scalar(select(ApiUsageEvent).where(ApiUsageEvent.idempotency_key == idempotency_key))
        period = self.period_key()
        aggregate = await session.scalar(select(ApiUsageMonthlyAggregate).where(
            ApiUsageMonthlyAggregate.provider_id == provider_id,
            ApiUsageMonthlyAggregate.period_key == period,
        ))
        if existing:
            used = aggregate.request_units if aggregate else 0
            limit = await self.usage_limit(session, provider_id)
            return {"accepted": existing.status_code < 429, "used": used, "limit": limit, "duplicate": True}
        limit = await self.usage_limit(session, provider_id)
        used = int(aggregate.request_units if aggregate else 0)
        accepted = limit <= 0 or used + units <= limit
        effective_status = status_code if accepted else 429
        session.add(ApiUsageEvent(provider_id=provider_id, api_key_id=api_key_id, route=route,
            units=units, status_code=effective_status, idempotency_key=idempotency_key))
        if not aggregate:
            aggregate = ApiUsageMonthlyAggregate(provider_id=provider_id, period_key=period)
            session.add(aggregate)
        if accepted:
            aggregate.request_units += units
        else:
            aggregate.rejected_units += units
        aggregate.last_event_at = datetime.now(UTC)
        await session.flush()
        return {"accepted": accepted, "used": aggregate.request_units, "limit": limit, "duplicate": False}

    async def enqueue_job(self, session: AsyncSession, *, queue_name: str, job_type: str,
                          payload: dict, idempotency_key: str, priority: int = 100,
                          available_at: datetime | None = None, max_attempts: int = 8) -> DistributedJob:
        existing = await session.scalar(select(DistributedJob).where(
            DistributedJob.queue_name == queue_name, DistributedJob.idempotency_key == idempotency_key))
        if existing:
            return existing
        row = DistributedJob(public_id=f"job_{uuid4().hex[:20]}", queue_name=queue_name,
            job_type=job_type, payload_json=payload, idempotency_key=idempotency_key,
            priority=priority, available_at=available_at or datetime.now(UTC), max_attempts=max_attempts)
        session.add(row); await session.flush(); return row

    async def claim_jobs(self, session: AsyncSession, *, queue_name: str, worker_id: str,
                         limit: int = 10, lease_seconds: int | None = None) -> list[DistributedJob]:
        now = datetime.now(UTC); lease = lease_seconds or self.settings.enterprise_job_lease_seconds
        stmt = (select(DistributedJob).where(
            DistributedJob.queue_name == queue_name,
            DistributedJob.available_at <= now,
            or_(DistributedJob.status.in_([DistributedJobStatus.PENDING.value, DistributedJobStatus.RETRY.value]),
                (DistributedJob.status == DistributedJobStatus.LEASED.value) & (DistributedJob.lease_expires_at < now)),
        ).order_by(DistributedJob.priority, DistributedJob.id).limit(limit).with_for_update(skip_locked=True))
        rows = list((await session.scalars(stmt)).all())
        for row in rows:
            row.status = DistributedJobStatus.LEASED.value
            row.lease_owner = worker_id
            row.lease_expires_at = now + timedelta(seconds=lease)
            row.attempts += 1
        await session.flush(); return rows

    async def finish_job(self, session: AsyncSession, job: DistributedJob, *, success: bool,
                         result: dict | None = None, error: str = "") -> None:
        if success:
            job.status = DistributedJobStatus.SUCCEEDED.value
            job.result_json = result or {}
            job.last_error = ""
        elif job.attempts >= job.max_attempts:
            job.status = DistributedJobStatus.DEAD.value
            job.last_error = error[:4000]
        else:
            job.status = DistributedJobStatus.RETRY.value
            delay = min(self.settings.enterprise_job_max_backoff_seconds,
                        self.settings.enterprise_job_base_backoff_seconds * (2 ** max(0, job.attempts - 1)))
            job.available_at = datetime.now(UTC) + timedelta(seconds=delay)
            job.last_error = error[:4000]
        job.lease_owner = None; job.lease_expires_at = None

    async def heartbeat(self, session: AsyncSession, worker_id: str, queues: list[str]) -> WorkerHeartbeat:
        row = await session.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == worker_id))
        now = datetime.now(UTC)
        if not row:
            row = WorkerHeartbeat(worker_id=worker_id, runtime_mode=self.settings.runtime_mode,
                release_id=self.settings.release_id, queues_json=queues, hostname=socket.gethostname(),
                process_id=os.getpid(), last_seen_at=now)
            session.add(row)
        else:
            row.last_seen_at = now; row.release_id = self.settings.release_id; row.queues_json = queues
        await session.flush(); return row

    def webhook_signature(self, secret: str, timestamp: str, body: bytes) -> str:
        return hmac.new(secret.encode(), timestamp.encode()+b"."+body, hashlib.sha256).hexdigest()

    async def deliver_webhook(self, session: AsyncSession, delivery: ProviderWebhookDelivery) -> bool:
        endpoint = await session.get(ProviderWebhookEndpoint, delivery.endpoint_id)
        if not endpoint or not endpoint.is_active:
            delivery.status = WebhookDeliveryStatus.DEAD.value
            delivery.last_error = "endpoint inactive or missing"
            return False
        body = json.dumps(delivery.payload_json or {}, separators=(",", ":"), sort_keys=True).encode()
        timestamp = str(int(time.time()))
        secret = self.secret_box.decrypt(endpoint.secret_encrypted)
        signature = self.webhook_signature(secret, timestamp, body)
        request_id = f"wha_{uuid4().hex}"
        started = time.perf_counter()
        attempt = WebhookDeliveryAttempt(delivery_id=delivery.id, attempt_number=delivery.attempts + 1,
            request_id=request_id, signature=signature)
        session.add(attempt)
        try:
            async with httpx.AsyncClient(timeout=self.settings.enterprise_webhook_timeout_seconds,
                                         follow_redirects=False) as client:
                response = await client.post(endpoint.url, content=body, headers={
                    "Content-Type":"application/json", "User-Agent":"CampusPass-IQ-Webhooks/8.0B",
                    "X-CampusPass-Event":delivery.event_type, "X-CampusPass-Delivery":delivery.event_id,
                    "X-CampusPass-Timestamp":timestamp, "X-CampusPass-Signature":"sha256="+signature,
                })
            attempt.response_status = response.status_code
            delivery.response_code = response.status_code
            if 200 <= response.status_code < 300:
                delivery.status = WebhookDeliveryStatus.DELIVERED.value
                delivery.delivered_at = datetime.now(UTC); delivery.last_error = ""
                endpoint.failure_count = 0; endpoint.last_success_at = datetime.now(UTC)
                ok = True
            else:
                raise RuntimeError(f"HTTP {response.status_code}")
        except Exception as exc:
            attempt.error = f"{type(exc).__name__}: {exc}"[:2000]
            endpoint.failure_count += 1; endpoint.last_failure_at = datetime.now(UTC)
            delivery.attempts += 1; delivery.last_error = attempt.error
            if delivery.attempts >= self.settings.enterprise_webhook_max_attempts:
                delivery.status = WebhookDeliveryStatus.DEAD.value
            else:
                delivery.status = WebhookDeliveryStatus.RETRY.value
                delay = min(self.settings.enterprise_webhook_max_backoff_seconds,
                            self.settings.enterprise_webhook_base_backoff_seconds * (2 ** max(0, delivery.attempts-1)))
                delivery.next_attempt_at = datetime.now(UTC)+timedelta(seconds=delay)
            ok = False
        attempt.duration_ms = int((time.perf_counter()-started)*1000)
        await session.flush(); return ok

    async def lifecycle(self, session: AsyncSession, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC); changed = {"grace":0,"suspended":0,"cancelled":0,"renewal_invoices":0}
        subscriptions = list((await session.scalars(select(BusinessSubscription).where(
            BusinessSubscription.status.in_([BusinessSubscriptionStatus.ACTIVE.value,
                BusinessSubscriptionStatus.PAST_DUE.value, BusinessSubscriptionStatus.GRACE.value]),
            BusinessSubscription.current_period_end <= now))).all())
        for sub in subscriptions:
            old = sub.status
            if sub.cancel_at_period_end:
                new = BusinessSubscriptionStatus.CANCELLED.value; changed["cancelled"] += 1
            elif old == BusinessSubscriptionStatus.ACTIVE.value:
                new = BusinessSubscriptionStatus.GRACE.value; changed["grace"] += 1
                sub.grace_ends_at = now + timedelta(days=self.settings.enterprise_grace_days)
            elif sub.grace_ends_at and sub.grace_ends_at <= now:
                new = BusinessSubscriptionStatus.SUSPENDED.value; changed["suspended"] += 1
            else:
                continue
            idem = f"lifecycle:{sub.id}:{old}:{new}:{sub.current_period_end.date()}"
            if not await session.scalar(select(SubscriptionLifecycleEvent.id).where(SubscriptionLifecycleEvent.idempotency_key==idem)):
                session.add(SubscriptionLifecycleEvent(provider_id=sub.provider_id, subscription_id=sub.id,
                    event_type="status_changed", from_status=old, to_status=new, idempotency_key=idem))
            sub.status = new
        await session.flush(); return changed

    async def dashboard(self, session: AsyncSession) -> dict:
        period=self.period_key(); now=datetime.now(UTC)
        return {
            "period": period,
            "usage_units": int(await session.scalar(select(func.coalesce(func.sum(ApiUsageMonthlyAggregate.request_units),0)).where(ApiUsageMonthlyAggregate.period_key==period)) or 0),
            "rejected_units": int(await session.scalar(select(func.coalesce(func.sum(ApiUsageMonthlyAggregate.rejected_units),0)).where(ApiUsageMonthlyAggregate.period_key==period)) or 0),
            "queued_jobs": int(await session.scalar(select(func.count()).select_from(DistributedJob).where(DistributedJob.status.in_(["pending","retry","leased"]))) or 0),
            "dead_jobs": int(await session.scalar(select(func.count()).select_from(DistributedJob).where(DistributedJob.status=="dead")) or 0),
            "active_workers": int(await session.scalar(select(func.count()).select_from(WorkerHeartbeat).where(WorkerHeartbeat.last_seen_at >= now-timedelta(seconds=self.settings.enterprise_worker_stale_seconds))) or 0),
            "dead_webhooks": int(await session.scalar(select(func.count()).select_from(ProviderWebhookDelivery).where(ProviderWebhookDelivery.status==WebhookDeliveryStatus.DEAD.value)) or 0),
            "overdue_invoices": int(await session.scalar(select(func.count()).select_from(__import__('app.db.models',fromlist=['BusinessInvoice']).BusinessInvoice).where(__import__('app.db.models',fromlist=['BusinessInvoice']).BusinessInvoice.status==BusinessInvoiceStatus.OVERDUE.value)) or 0),
        }
