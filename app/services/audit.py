from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, User


class AuditService:
    async def log(
        self,
        session: AsyncSession,
        actor: User | None,
        action: str,
        entity_type: str = "",
        entity_id: str = "",
        data: dict | None = None,
    ) -> None:
        session.add(
            AuditLog(
                actor_user_id=actor.id if actor else None,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                data=data or {},
            )
        )
        await session.flush()
