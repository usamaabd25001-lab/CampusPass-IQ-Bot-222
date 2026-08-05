from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BotIssueReport, User


class BotIssueService:
    async def create(
        self,
        session: AsyncSession,
        *,
        user: User,
        category: str,
        description: str,
        file_id: str | None = None,
        file_type: str | None = None,
        last_action: str | None = None,
        conversation_state: str | None = None,
    ) -> BotIssueReport:
        text = (description or "").strip()
        if len(text) < 5:
            raise ValueError("اكتب وصفًا أوضح للمشكلة")
        public_id = f"BUG-{secrets.token_hex(4).upper()}"
        while await session.scalar(
            select(BotIssueReport.id).where(BotIssueReport.public_id == public_id)
        ):
            public_id = f"BUG-{secrets.token_hex(4).upper()}"
        row = BotIssueReport(
            public_id=public_id,
            user_id=user.id,
            category=(category or "other")[:80],
            description=text[:6000],
            file_id=file_id,
            file_type=file_type,
            last_action=(last_action or "")[:120] or None,
            conversation_state=(conversation_state or "")[:180] or None,
        )
        session.add(row)
        await session.flush()
        return row

    async def list_open(self, session: AsyncSession, limit: int = 50) -> list[BotIssueReport]:
        return list(
            (
                await session.scalars(
                    select(BotIssueReport)
                    .where(BotIssueReport.status.in_(["open", "in_progress"]))
                    .order_by(BotIssueReport.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )
