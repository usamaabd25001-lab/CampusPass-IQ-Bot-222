from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.utils import public_id
from app.db.models import (
    DistributedJob,
    Offer,
    OfferStatus,
    Order,
    StudentSubscription,
    SupportFAQ,
    SupportTicket,
    TicketMessage,
    TicketStatus,
    User,
)
from app.integrations.ai.gemini import GeminiClient
from app.services.data_protection import DataProtectionService
from app.services.enterprise_scale import EnterpriseScaleService


class SupportService:
    AI_QUEUE = "ai_support"
    AI_JOB_TYPE = "support_answer"

    def __init__(
        self,
        settings: Settings,
        gemini: GeminiClient,
        data_protection: DataProtectionService,
        enterprise_scale: EnterpriseScaleService,
    ) -> None:
        self.settings = settings
        self.gemini = gemini
        self.data_protection = data_protection
        self.enterprise_scale = enterprise_scale

    async def enqueue_ai_request(
        self,
        session: AsyncSession,
        *,
        user: User,
        chat_id: int,
        source_message_id: int,
        question: str,
        order_id: int = 0,
    ) -> DistributedJob:
        clean_question = self.data_protection.redact_for_ai(question).strip()
        if len(clean_question) < 5:
            raise ValueError("اكتب تفاصيل أكثر حتى يستطيع المساعد فهم المشكلة.")
        if len(clean_question) > self.settings.gemini_max_question_chars:
            raise ValueError(
                f"اختصر السؤال إلى أقل من {self.settings.gemini_max_question_chars} حرف."
            )
        since = datetime.now(UTC) - timedelta(days=1)
        recent_jobs = list(
            (
                await session.execute(
                    select(DistributedJob.payload_json, DistributedJob.status)
                    .where(
                        DistributedJob.queue_name == self.AI_QUEUE,
                        DistributedJob.created_at >= since,
                    )
                    .order_by(DistributedJob.id.desc())
                    .limit(5000)
                )
            ).all()
        )
        own_jobs = [
            (payload, status)
            for payload, status in recent_jobs
            if isinstance(payload, dict)
            and int(payload.get("user_id", 0) or 0) == user.id
        ]
        used = len(own_jobs)
        active_statuses = {"pending", "retry", "leased"}
        pending = sum(1 for _payload, status in own_jobs if status in active_statuses)
        if pending >= self.settings.gemini_max_pending_per_user:
            raise ValueError(
                "لديك استفسارات قيد المعالجة. انتظر وصول الرد قبل إرسال سؤال جديد."
            )
        if used >= self.settings.gemini_daily_user_limit:
            raise ValueError(
                "وصلت إلى الحد اليومي للمساعد الذكي. افتح تذكرة دعم وسيتم خدمتك بشرياً."
            )
        return await self.enterprise_scale.enqueue_job(
            session,
            queue_name=self.AI_QUEUE,
            job_type=self.AI_JOB_TYPE,
            payload={
                "job_schema_version": 1,
                "user_id": user.id,
                "telegram_id": int(user.telegram_id),
                "chat_id": int(chat_id),
                "source_message_id": int(source_message_id),
                "placeholder_message_id": 0,
                "order_id": int(order_id or 0),
                "question": clean_question,
            },
            idempotency_key=f"ai-support:{user.telegram_id}:{source_message_id}",
            priority=50,
            max_attempts=self.settings.gemini_job_max_attempts,
        )

    async def build_ai_context(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        order_id: int,
        question: str,
    ) -> dict:
        user = await session.scalar(
            select(User)
            .options(selectinload(User.profile))
            .where(User.id == int(user_id))
        )
        if user is None or user.is_banned or not user.is_active:
            raise PermissionError("User is not eligible for AI support")
        if user.ai_data_consent_at is None:
            raise PermissionError("AI data consent is missing")

        raw_name = (user.profile.full_name if user.profile else user.telegram_name) or "طالب"
        first_name = raw_name.strip().split()[0][:40] if raw_name.strip() else "طالب"
        context: dict = {
            "platform": {
                "name": "CampusPass IQ",
                "scope": "اشتراكات وخدمات طلابية رقمية في العراق",
                "terms_summary": self.settings.terms_text[:800],
                "privacy_summary": self.settings.privacy_text[:800],
            },
            "user": {
                "display_name": first_name,
                "role": user.role,
                "has_platform_access": bool(user.has_platform_access),
            },
            "order": None,
            "active_subscriptions": [],
            "recent_orders": [],
            "matching_offers": [],
            "faq": [],
        }

        subscriptions = list(
            (
                await session.scalars(
                    select(StudentSubscription)
                    .where(
                        StudentSubscription.user_id == user.id,
                        StudentSubscription.status.in_(
                            [
                                "pending",
                                "waiting_activation",
                                "active",
                                "expiring",
                                "paused",
                                "needs_support",
                            ]
                        ),
                    )
                    .order_by(StudentSubscription.id.desc())
                    .limit(5)
                )
            ).all()
        )
        context["active_subscriptions"] = [
            {
                "service": item.service_name_snapshot,
                "provider": item.provider_name_snapshot,
                "status": item.status,
                "starts_at": item.starts_at.isoformat() if item.starts_at else None,
                "ends_at": item.ends_at.isoformat() if item.ends_at else None,
                "warranty_ends_at": (
                    item.warranty_ends_at.isoformat() if item.warranty_ends_at else None
                ),
            }
            for item in subscriptions
        ]

        recent_orders = list(
            (
                await session.scalars(
                    select(Order)
                    .options(
                        selectinload(Order.offer).selectinload(Offer.provider),
                        selectinload(Order.provider),
                    )
                    .where(Order.user_id == user.id)
                    .order_by(Order.id.desc())
                    .limit(3)
                )
            ).all()
        )
        context["recent_orders"] = [
            {
                "reference": item.public_id,
                "status": item.status,
                "service": item.offer.title if item.offer else "",
                "provider": (
                    (item.provider.name_ar or item.provider.name_en)
                    if item.provider
                    else (
                        (item.offer.provider.name_ar or item.offer.provider.name_en)
                        if item.offer and item.offer.provider
                        else ""
                    )
                ),
                "price_iqd": int(item.total_iqd),
            }
            for item in recent_orders
        ]

        if order_id:
            order = await session.scalar(
                select(Order)
                .options(
                    selectinload(Order.offer).selectinload(Offer.provider),
                    selectinload(Order.provider),
                )
                .where(Order.id == int(order_id), Order.user_id == user.id)
            )
            if order is None:
                raise PermissionError("Order does not belong to user")
            subscription = await session.scalar(
                select(StudentSubscription).where(StudentSubscription.order_id == order.id)
            )
            context["order"] = {
                "reference": order.public_id,
                "status": order.status,
                "service": order.offer.title if order.offer else "",
                "provider": (
                    (order.offer.provider.name_ar or order.offer.provider.name_en)
                    if order.offer and order.offer.provider
                    else (
                        (order.provider.name_ar or order.provider.name_en)
                        if order.provider
                        else ""
                    )
                ),
                "price_iqd": int(order.total_iqd),
                "delivery_type": order.offer.delivery_type if order.offer else "",
                "duration_days": order.offer.duration_days if order.offer else None,
                "offer_terms": (order.offer.terms[:800] if order.offer else ""),
                "refund_policy": (order.offer.refund_policy[:800] if order.offer else ""),
                "subscription_status": subscription.status if subscription else None,
                "warranty_ends_at": (
                    subscription.warranty_ends_at.isoformat()
                    if subscription and subscription.warranty_ends_at
                    else None
                ),
            }

        words = []
        for word in question.replace("؟", " ").replace("،", " ").split():
            token = word.strip(".,:;!?()[]{}\"'ـ-")
            if len(token) >= 3 and token not in words:
                words.append(token)
            if len(words) >= 5:
                break
        if words:
            offer_filters = [Offer.title.ilike(f"%{word}%") for word in words]
            offers = list(
                (
                    await session.scalars(
                        select(Offer)
                        .options(selectinload(Offer.provider))
                        .where(
                            Offer.is_active.is_(True),
                            Offer.status == OfferStatus.ACTIVE.value,
                            or_(*offer_filters),
                        )
                        .order_by(Offer.id.desc())
                        .limit(6)
                    )
                ).all()
            )
            context["matching_offers"] = [
                {
                    "title": offer.title,
                    "provider": (offer.provider.name_ar or offer.provider.name_en) if offer.provider else "",
                    "price_iqd": int(offer.price_iqd),
                    "duration_days": offer.duration_days,
                    "delivery_type": offer.delivery_type,
                    "terms": offer.terms[:400],
                }
                for offer in offers
            ]

        faqs = list(
            (
                await session.scalars(
                    select(SupportFAQ)
                    .where(SupportFAQ.is_active.is_(True))
                    .order_by(SupportFAQ.sort_order, SupportFAQ.id)
                    .limit(10)
                )
            ).all()
        )
        context["faq"] = [
            {"question": item.question[:250], "answer": item.answer[:600]}
            for item in faqs
        ]
        return context

    async def generate_ai_answer(self, question: str, context: dict) -> str:
        safe_question = self.data_protection.redact_for_ai(question)
        safe_context = self.data_protection.redact_for_ai(
            json.dumps(context, ensure_ascii=False, sort_keys=True)
        )
        return await self.gemini.answer(safe_question, safe_context)

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
