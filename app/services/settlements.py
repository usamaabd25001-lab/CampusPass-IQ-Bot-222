from __future__ import annotations

from datetime import UTC, datetime, timedelta
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import public_id
from app.db.models import (Order, OrderStatus, ProviderSettlement, SettlementStatus,
                           WalletEntryType, WalletOwnerType)
from app.services.wallets import WalletService


class SettlementService:
    def __init__(self, wallets: WalletService) -> None:
        self.wallets = wallets

    async def build(self, session: AsyncSession, provider_id: int,
                    period_start: datetime, period_end: datetime,
                    due_hours: int = 24) -> ProviderSettlement:
        existing = await session.scalar(select(ProviderSettlement).where(
            ProviderSettlement.provider_id == provider_id,
            ProviderSettlement.period_start == period_start,
            ProviderSettlement.period_end == period_end))
        if existing:
            return existing
        row = (await session.execute(select(
            func.count(Order.id), func.coalesce(func.sum(Order.total_iqd), 0),
            func.coalesce(func.sum(Order.owner_net_iqd), 0)
        ).where(Order.provider_id == provider_id,
                Order.completed_at >= period_start, Order.completed_at <= period_end,
                Order.status == OrderStatus.COMPLETED.value))).one()
        due = int(row[2] or 0)
        settlement = ProviderSettlement(public_id=public_id("ST"), provider_id=provider_id,
            period_start=period_start, period_end=period_end, orders_count=int(row[0] or 0),
            gross_sales_iqd=int(row[1] or 0), owner_due_iqd=due, remaining_due_iqd=due,
            due_at=datetime.now(UTC) + timedelta(hours=due_hours))
        session.add(settlement)
        await session.flush()
        return settlement


    async def create_manual_due(
        self,
        session: AsyncSession,
        provider_id: int,
        amount_iqd: int,
        *,
        due_hours: int = 24,
    ) -> ProviderSettlement:
        """Create an owner-requested collection of CampusPass fees from a provider.

        This does not move provider sales money. It only records the amount the
        bot owner asks the provider to remit for CampusPass service/commission.
        """
        amount = max(0, int(amount_iqd))
        if amount <= 0:
            raise ValueError("المبلغ المطلوب يجب أن يكون أكبر من صفر")
        now = datetime.now(UTC)
        settlement = ProviderSettlement(
            public_id=public_id("ST"),
            provider_id=provider_id,
            period_start=now,
            period_end=now,
            orders_count=0,
            gross_sales_iqd=0,
            owner_due_iqd=amount,
            remaining_due_iqd=amount,
            due_at=now + timedelta(hours=due_hours),
            status=SettlementStatus.NOTIFIED.value,
            first_notified_at=now,
        )
        session.add(settlement)
        await session.flush()
        return settlement

    async def apply_provider_wallet(self, session: AsyncSession, settlement: ProviderSettlement) -> int:
        balance = await self.wallets.balance(session, WalletOwnerType.PROVIDER.value, settlement.provider_id)
        used = min(balance, settlement.remaining_due_iqd)
        if used:
            await self.wallets.post(session, owner_type=WalletOwnerType.PROVIDER.value,
                owner_id=settlement.provider_id, amount_iqd=used, direction="debit",
                entry_type=WalletEntryType.SETTLEMENT.value,
                idempotency_key=f"settlement:{settlement.id}:wallet",
                provider_id=settlement.provider_id, description=f"تسديد {settlement.public_id}")
            settlement.wallet_applied_iqd += used
            settlement.remaining_due_iqd -= used
            if settlement.remaining_due_iqd == 0:
                settlement.status = SettlementStatus.CONFIRMED.value
        await session.flush()
        return used

    async def submit_proof(self, session: AsyncSession, settlement: ProviderSettlement,
                           user_id: int, file_id: str, proof_kind: str) -> None:
        if settlement.status == SettlementStatus.CONFIRMED.value:
            return
        settlement.proof_file_id = file_id
        settlement.proof_kind = proof_kind
        settlement.submitted_by_user_id = user_id
        settlement.submitted_at = datetime.now(UTC)
        settlement.status = SettlementStatus.PROOF_RECEIVED.value
        await session.flush()

    async def review(self, session: AsyncSession, settlement: ProviderSettlement,
                     admin_user_id: int, approved: bool, reason: str = "") -> None:
        settlement.reviewed_by_user_id = admin_user_id
        settlement.reviewed_at = datetime.now(UTC)
        if approved:
            settlement.status = SettlementStatus.CONFIRMED.value
            settlement.remaining_due_iqd = 0
        else:
            settlement.status = SettlementStatus.REJECTED.value
            settlement.rejection_reason = reason
        await session.flush()
