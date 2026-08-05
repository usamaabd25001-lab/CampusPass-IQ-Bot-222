from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import public_id
from app.db.models import (
    SupportFAQ,
    SupportTicket,
    TicketMessage,
    TicketStatus,
    User,
)
from app.integrations.ai.gemini import GeminiClient
from app.services.data_protection import DataProtectionService


class SupportService:
    def __init__(self, gemini: GeminiClient, data_protection: DataProtectionService) -> None:
        self.gemini = gemini
        self.data_protection = data_protection

    async def faqs(self, session: AsyncSession) -> list[SupportFAQ]:
        return list(
            (
                await session.scalars(
                    select(SupportFAQ)
                    .where(SupportFAQ.is_active.is_(True))
                    .order_by(SupportFAQ.sort_order, SupportFAQ.id)
                )
            ).all()
        )

    async def ask_ai(self, question: str, context: str = "") -> str | None:
        try:
            safe_question = self.data_protection.redact_for_ai(question)
            safe_context = self.data_protection.redact_for_ai(context)
            return await self.gemini.answer(safe_question, safe_context)
        except Exception as exc:
            # Keep user-facing support safe, while preserving a concise diagnostic
            # for the administrator through structured logs. Never log API keys.
            import logging
            logging.getLogger(__name__).warning("Gemini unavailable: %s", exc)
            return None

    async def create_ticket(
        self,
        session: AsyncSession,
        user: User,
        subject: str,
        message: str,
        category: str = "general",
        provider_id: int | None = None,
        order_id: int | None = None,
        ai_answer: str | None = None,
    ) -> SupportTicket:
        ticket = SupportTicket(
            public_id=public_id("TKT"),
            user_id=user.id,
            provider_id=provider_id,
            order_id=order_id,
            category=category,
            subject=subject[:255],
            ai_answer=ai_answer,
        )
        session.add(ticket)
        await session.flush()
        session.add(
            TicketMessage(
                ticket_id=ticket.id,
                sender_user_id=user.id,
                sender_role="user",
                text=message,
            )
        )
        await session.flush()
        return ticket

    async def add_message(
        self,
        session: AsyncSession,
        ticket: SupportTicket,
        sender: User | None,
        sender_role: str,
        text: str,
        file_id: str | None = None,
        file_type: str | None = None,
        evidence_asset_id: int | None = None,
    ) -> TicketMessage:
        if ticket.status == TicketStatus.CLOSED.value:
            raise ValueError("التذكرة مغلقة ولا يمكن إضافة رد جديد")
        msg = TicketMessage(
            ticket_id=ticket.id,
            sender_user_id=sender.id if sender else None,
            sender_role=sender_role,
            text=text,
            file_id=file_id,
            file_type=file_type,
            evidence_asset_id=evidence_asset_id,
        )
        session.add(msg)
        ticket.status = (
            TicketStatus.WAITING_USER.value
            if sender_role in {"provider", "admin", "staff"}
            else TicketStatus.WAITING_PROVIDER.value
        )
        await session.flush()
        return msg

    async def close_ticket(
        self,
        session: AsyncSession,
        ticket: SupportTicket,
        actor: User,
        reason: str = "",
    ) -> SupportTicket:
        locked = await session.scalar(
            select(SupportTicket)
            .where(SupportTicket.id == ticket.id)
            .with_for_update()
        )
        if not locked:
            raise ValueError("التذكرة غير موجودة")
        if locked.status == TicketStatus.CLOSED.value:
            return locked
        locked.status = TicketStatus.CLOSED.value
        locked.closed_at = datetime.now(UTC)
        locked.closed_by_user_id = actor.id
        locked.close_reason = reason[:500]
        await session.flush()
        return locked

    async def latest_messages(
        self, session: AsyncSession, ticket_id: int, limit: int = 15
    ) -> list[TicketMessage]:
        rows, _total = await self.ticket_messages_page(
            session, ticket_id, page=0, page_size=limit
        )
        return rows

    async def ticket_messages_page(
        self,
        session: AsyncSession,
        ticket_id: int,
        *,
        page: int = 0,
        page_size: int = 15,
    ) -> tuple[list[TicketMessage], int]:
        page = max(0, int(page))
        page_size = max(1, min(int(page_size), 30))
        total = int(
            await session.scalar(
                select(func.count(TicketMessage.id)).where(
                    TicketMessage.ticket_id == ticket_id
                )
            )
            or 0
        )
        rows = list(
            (
                await session.scalars(
                    select(TicketMessage)
                    .where(TicketMessage.ticket_id == ticket_id)
                    .order_by(TicketMessage.created_at.desc(), TicketMessage.id.desc())
                    .offset(page * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        rows.reverse()
        return rows, total

    async def get_ticket(self, session: AsyncSession, ticket_id: int) -> SupportTicket | None:
        return await session.get(SupportTicket, ticket_id)

    async def user_tickets(self, session: AsyncSession, user: User) -> list[SupportTicket]:
        items, _total = await self.user_tickets_page(session, user, page=0, page_size=20)
        return items

    async def user_tickets_page(
        self,
        session: AsyncSession,
        user: User,
        *,
        page: int = 0,
        page_size: int = 8,
    ) -> tuple[list[SupportTicket], int]:
        page = max(0, int(page))
        page_size = max(1, min(int(page_size), 20))
        total = int(
            await session.scalar(
                select(func.count(SupportTicket.id)).where(
                    SupportTicket.user_id == user.id
                )
            )
            or 0
        )
        rows = list(
            (
                await session.scalars(
                    select(SupportTicket)
                    .where(SupportTicket.user_id == user.id)
                    .order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc())
                    .offset(page * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return rows, total
