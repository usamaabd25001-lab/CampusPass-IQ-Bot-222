from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import SecretBox
from app.db.models import (
    BusinessInvoice, BusinessInvoiceStatus, BusinessPlan, BusinessSubscription,
    BusinessSubscriptionStatus, LedgerDirection, AccountingEntry, LedgerTransaction,
    ProviderApiKey, ProviderTeamMember, ProviderWebhookDelivery,
    ProviderWebhookEndpoint, WebhookDeliveryStatus,
)


class EnterpriseCoreService:
    """Commercial control plane with idempotent billing and balanced ledger posts."""

    def __init__(self, secret_box: SecretBox) -> None:
        self.secret_box = secret_box

    async def seed_default_plans(self, session: AsyncSession) -> None:
        plans = (
            ("basic", "Basic", 15000, 2, 1000, 1000, {"reports": True}),
            ("pro", "Pro", 35000, 5, 10000, 700, {"reports": True, "api": True, "webhooks": True}),
            ("enterprise", "Enterprise", 75000, 20, 100000, 400, {"reports": True, "api": True, "webhooks": True, "teams": True}),
        )
        for order, (code, name, price, seats, requests, commission, features) in enumerate(plans):
            if not await session.scalar(select(BusinessPlan.id).where(BusinessPlan.code == code)):
                session.add(BusinessPlan(code=code, name=name, monthly_price_iqd=price,
                    included_team_members=seats, included_api_requests=requests,
                    commission_bps=commission, features_json=features, sort_order=order))
        await session.flush()

    async def subscribe(self, session: AsyncSession, *, provider_id: int, plan_code: str,
                        idempotency_key: str, period_days: int = 30) -> BusinessSubscription:
        plan = await session.scalar(select(BusinessPlan).where(BusinessPlan.code == plan_code, BusinessPlan.is_active.is_(True)))
        if not plan:
            raise ValueError("business plan not found")
        current = await session.scalar(select(BusinessSubscription).where(BusinessSubscription.provider_id == provider_id))
        now = datetime.now(UTC)
        if current:
            current.plan_id = plan.id
            current.status = BusinessSubscriptionStatus.ACTIVE.value
            current.current_period_start = now
            current.current_period_end = now + timedelta(days=period_days)
            current.metadata_json = {**(current.metadata_json or {}), "last_idempotency_key": idempotency_key}
            return current
        row = BusinessSubscription(public_id=f"bs_{uuid4().hex[:20]}", provider_id=provider_id,
            plan_id=plan.id, status=BusinessSubscriptionStatus.ACTIVE.value,
            current_period_start=now, current_period_end=now + timedelta(days=period_days),
            metadata_json={"created_idempotency_key": idempotency_key})
        session.add(row); await session.flush(); return row

    async def issue_invoice(self, session: AsyncSession, *, provider_id: int, subscription_id: int | None,
                            amount_iqd: int, idempotency_key: str, due_days: int = 7,
                            description: str = "Enterprise subscription") -> BusinessInvoice:
        if amount_iqd <= 0:
            raise ValueError("invoice amount must be positive")
        existing = await session.scalar(select(BusinessInvoice).where(BusinessInvoice.idempotency_key == idempotency_key))
        if existing:
            return existing
        now = datetime.now(UTC)
        invoice = BusinessInvoice(invoice_number=f"CPI-{now:%Y%m%d}-{uuid4().hex[:8].upper()}",
            provider_id=provider_id, subscription_id=subscription_id,
            status=BusinessInvoiceStatus.ISSUED.value, subtotal_iqd=amount_iqd,
            total_iqd=amount_iqd, due_at=now+timedelta(days=due_days), issued_at=now,
            idempotency_key=idempotency_key, line_items_json=[{"description": description, "amount_iqd": amount_iqd}])
        session.add(invoice); await session.flush(); return invoice

    async def post_balanced_transaction(self, session: AsyncSession, *, idempotency_key: str,
            reference_type: str, reference_id: str, description: str,
            entries: list[dict], currency: str = "IQD") -> LedgerTransaction:
        existing = await session.scalar(select(LedgerTransaction).where(LedgerTransaction.idempotency_key == idempotency_key))
        if existing:
            return existing
        debit = sum(int(e["amount_iqd"]) for e in entries if e["direction"] == LedgerDirection.DEBIT.value)
        credit = sum(int(e["amount_iqd"]) for e in entries if e["direction"] == LedgerDirection.CREDIT.value)
        if debit <= 0 or debit != credit:
            raise ValueError("ledger transaction must be positive and balanced")
        tx = LedgerTransaction(public_id=f"lt_{uuid4().hex[:20]}", idempotency_key=idempotency_key,
            reference_type=reference_type, reference_id=reference_id, description=description,
            currency=currency, total_iqd=debit)
        session.add(tx); await session.flush()
        for item in entries:
            session.add(AccountingEntry(transaction_id=tx.id, account_code=item["account_code"],
                direction=item["direction"], amount_iqd=int(item["amount_iqd"]),
                provider_id=item.get("provider_id")))
        await session.flush(); return tx

    async def mark_invoice_paid(self, session: AsyncSession, *, invoice_id: int,
                                payment_idempotency_key: str) -> BusinessInvoice:
        invoice = await session.get(BusinessInvoice, invoice_id)
        if not invoice:
            raise ValueError("invoice not found")
        if invoice.status == BusinessInvoiceStatus.PAID.value:
            return invoice
        await self.post_balanced_transaction(session, idempotency_key=payment_idempotency_key,
            reference_type="business_invoice", reference_id=str(invoice.id),
            description=f"Payment for {invoice.invoice_number}", entries=[
                {"account_code": "cash", "direction": "debit", "amount_iqd": invoice.total_iqd, "provider_id": invoice.provider_id},
                {"account_code": "subscription_revenue", "direction": "credit", "amount_iqd": invoice.total_iqd, "provider_id": invoice.provider_id},
            ])
        invoice.paid_iqd = invoice.total_iqd
        invoice.status = BusinessInvoiceStatus.PAID.value
        invoice.paid_at = datetime.now(UTC)
        return invoice

    async def create_api_key(self, session: AsyncSession, *, provider_id: int, name: str,
                             scopes: list[str], created_by_user_id: int | None = None) -> tuple[ProviderApiKey, str]:
        raw = "cp_live_" + secrets.token_urlsafe(32)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        row = ProviderApiKey(provider_id=provider_id, name=name, key_prefix=raw[:16], key_hash=digest,
            scopes_json=sorted(set(scopes)), created_by_user_id=created_by_user_id)
        session.add(row); await session.flush(); return row, raw

    async def authenticate_api_key(self, session: AsyncSession, raw_key: str, required_scope: str | None = None) -> ProviderApiKey | None:
        digest = hashlib.sha256(raw_key.encode()).hexdigest()
        row = await session.scalar(select(ProviderApiKey).where(ProviderApiKey.key_hash == digest, ProviderApiKey.is_active.is_(True)))
        if not row or (row.expires_at and row.expires_at <= datetime.now(UTC)):
            return None
        if required_scope and required_scope not in (row.scopes_json or []):
            return None
        row.last_used_at = datetime.now(UTC); return row

    async def add_team_member(self, session: AsyncSession, *, provider_id: int, user_id: int,
                              role_code: str, permissions: list[str], invited_by_user_id: int | None = None) -> ProviderTeamMember:
        row = await session.scalar(select(ProviderTeamMember).where(ProviderTeamMember.provider_id == provider_id, ProviderTeamMember.user_id == user_id))
        if row:
            row.role_code=role_code; row.permissions_json=sorted(set(permissions)); row.is_active=True; return row
        row=ProviderTeamMember(provider_id=provider_id, user_id=user_id, role_code=role_code,
            permissions_json=sorted(set(permissions)), invited_by_user_id=invited_by_user_id)
        session.add(row); await session.flush(); return row

    async def register_webhook(self, session: AsyncSession, *, provider_id: int, url: str,
                               secret: str, events: list[str]) -> ProviderWebhookEndpoint:
        if not url.startswith("https://"):
            raise ValueError("webhook URL must use HTTPS")
        row=ProviderWebhookEndpoint(provider_id=provider_id, url=url,
            secret_encrypted=self.secret_box.encrypt(secret), events_json=sorted(set(events)))
        session.add(row); await session.flush(); return row

    async def enqueue_webhook_event(self, session: AsyncSession, *, provider_id: int,
                                    event_id: str, event_type: str, payload: dict) -> int:
        endpoints=list((await session.scalars(select(ProviderWebhookEndpoint).where(
            ProviderWebhookEndpoint.provider_id == provider_id,
            ProviderWebhookEndpoint.is_active.is_(True)))).all())
        count=0
        for endpoint in endpoints:
            if event_type not in (endpoint.events_json or []):
                continue
            exists=await session.scalar(select(ProviderWebhookDelivery.id).where(
                ProviderWebhookDelivery.endpoint_id == endpoint.id,
                ProviderWebhookDelivery.event_id == event_id))
            if exists: continue
            session.add(ProviderWebhookDelivery(endpoint_id=endpoint.id, event_id=event_id,
                event_type=event_type, status=WebhookDeliveryStatus.PENDING.value, payload_json=payload))
            count += 1
        await session.flush(); return count

    async def dashboard(self, session: AsyncSession) -> dict:
        plan_count = int(await session.scalar(select(func.count(BusinessPlan.id))) or 0)
        active_subs = int(await session.scalar(select(func.count(BusinessSubscription.id)).where(BusinessSubscription.status == "active")) or 0)
        outstanding = int(await session.scalar(select(func.coalesce(func.sum(BusinessInvoice.total_iqd-BusinessInvoice.paid_iqd),0)).where(BusinessInvoice.status.in_(["issued","partially_paid","overdue"]))) or 0)
        revenue = int(await session.scalar(select(func.coalesce(func.sum(AccountingEntry.amount_iqd),0)).where(AccountingEntry.account_code == "subscription_revenue", AccountingEntry.direction == "credit")) or 0)
        return {"plans": plan_count, "active_subscriptions": active_subs,
            "outstanding_iqd": outstanding, "recognized_subscription_revenue_iqd": revenue}
