from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Wallet, WalletEntry, WalletEntryType, WalletOwnerType


class WalletService:
    """Atomic, idempotent wallet ledger for students and providers."""

    async def get_or_create(self, session: AsyncSession, owner_type: str, owner_id: int) -> Wallet:
        wallet = await session.scalar(
            select(Wallet).where(Wallet.owner_type == owner_type, Wallet.owner_id == owner_id).with_for_update()
        )
        if wallet is None:
            wallet = Wallet(owner_type=owner_type, owner_id=owner_id)
            session.add(wallet)
            await session.flush()
        return wallet

    async def balance(self, session: AsyncSession, owner_type: str, owner_id: int) -> int:
        wallet = await self.get_or_create(session, owner_type, owner_id)
        return wallet.balance_iqd

    async def post(self, session: AsyncSession, *, owner_type: str, owner_id: int,
                   amount_iqd: int, direction: str, entry_type: str,
                   idempotency_key: str, description: str = "", order_id: int | None = None,
                   provider_id: int | None = None, actor_user_id: int | None = None,
                   metadata: dict | None = None) -> WalletEntry:
        if amount_iqd < 0 or direction not in {"credit", "debit"}:
            raise ValueError("حركة المحفظة غير صالحة")
        existing = await session.scalar(select(WalletEntry).where(WalletEntry.idempotency_key == idempotency_key))
        if existing:
            return existing
        wallet = await self.get_or_create(session, owner_type, owner_id)
        if wallet.is_frozen:
            raise ValueError("المحفظة مجمدة")
        new_balance = wallet.balance_iqd + amount_iqd if direction == "credit" else wallet.balance_iqd - amount_iqd
        if new_balance < 0:
            raise ValueError("الرصيد غير كافٍ")
        wallet.balance_iqd = new_balance
        wallet.version += 1
        entry = WalletEntry(wallet_id=wallet.id, entry_type=entry_type, direction=direction,
                            amount_iqd=amount_iqd, balance_after_iqd=new_balance,
                            idempotency_key=idempotency_key, description=description,
                            order_id=order_id, provider_id=provider_id,
                            actor_user_id=actor_user_id, metadata_json=metadata or {})
        session.add(entry)
        await session.flush()
        return entry

    async def credit_overpayment(self, session: AsyncSession, user_id: int, order_id: int,
                                 paid_iqd: int, required_iqd: int) -> int:
        excess = max(0, paid_iqd - required_iqd)
        if excess:
            await self.post(session, owner_type=WalletOwnerType.USER.value, owner_id=user_id,
                            amount_iqd=excess, direction="credit",
                            entry_type=WalletEntryType.OVERPAYMENT.value,
                            idempotency_key=f"order:{order_id}:overpayment",
                            order_id=order_id, description="فرق دفع محفوظ للطلبات اللاحقة")
        return excess

    async def apply_service_fee_only(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        order_id: int,
        service_fee_iqd: int,
    ) -> int:
        """Debit the complete bot fee only when the wallet can cover it.

        Partial wallet deductions are forbidden and the service price is never
        reduced by this method. The idempotency key makes repeated callbacks safe.
        """
        fee = max(0, int(service_fee_iqd))
        if fee == 0:
            return 0
        key = f"order:{order_id}:bot-fee"
        existing = await session.scalar(
            select(WalletEntry).where(WalletEntry.idempotency_key == key)
        )
        if existing:
            return int(existing.amount_iqd)
        wallet = await self.get_or_create(session, WalletOwnerType.USER.value, user_id)
        if int(wallet.balance_iqd) < fee:
            return 0
        await self.post(
            session,
            owner_type=WalletOwnerType.USER.value,
            owner_id=user_id,
            amount_iqd=fee,
            direction="debit",
            entry_type=WalletEntryType.BOT_FEE.value,
            idempotency_key=key,
            order_id=order_id,
            description="تغطية رسوم البوت تلقائياً من المحفظة",
            metadata={"scope": "bot_service_fee_only"},
        )
        return fee

    async def refund_service_fee(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        order_id: int,
        amount_iqd: int,
        reason: str,
    ) -> int:
        amount = max(0, int(amount_iqd))
        if amount == 0:
            return 0
        await self.post(
            session,
            owner_type=WalletOwnerType.USER.value,
            owner_id=user_id,
            amount_iqd=amount,
            direction="credit",
            entry_type=WalletEntryType.BOT_FEE_REFUND.value,
            idempotency_key=f"order:{order_id}:bot-fee-refund",
            order_id=order_id,
            description=reason[:500],
            metadata={"scope": "bot_service_fee_refund"},
        )
        return amount

    async def apply_to_purchase(self, session: AsyncSession, user_id: int, order_id: int,
                                amount_iqd: int) -> int:
        wallet = await self.get_or_create(session, WalletOwnerType.USER.value, user_id)
        used = min(max(0, amount_iqd), wallet.balance_iqd)
        if used:
            await self.post(session, owner_type=WalletOwnerType.USER.value, owner_id=user_id,
                            amount_iqd=used, direction="debit", entry_type=WalletEntryType.PURCHASE.value,
                            idempotency_key=f"order:{order_id}:wallet-use", order_id=order_id,
                            description="استخدام رصيد المحفظة في الطلب")
        return used
