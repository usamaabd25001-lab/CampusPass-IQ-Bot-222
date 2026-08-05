from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RuntimeConfigGeneration


@dataclass(slots=True)
class _GenerationSnapshot:
    value: int
    expires_at: float


class CacheCoherenceService:
    """Small database-backed cache-generation coordinator.

    Local in-process caches are extremely fast, but a Render deployment may have
    a web service and a worker alive at the same time. A monotonically increasing
    generation lets every process notice owner changes without relying on sticky
    sessions or a fragile pub/sub-only message. The database is the source of
    truth; each process checks it only once per short poll window.
    """

    DEFAULT_NAMESPACES = ("menus", "features", "templates", "branding")

    def __init__(self, poll_seconds: float = 2.0) -> None:
        self.poll_seconds = max(0.25, float(poll_seconds))
        self._local: dict[str, _GenerationSnapshot] = {}

    async def ensure_defaults(self, session: AsyncSession) -> None:
        for namespace in self.DEFAULT_NAMESPACES:
            await self._ensure_row(session, namespace)

    async def _ensure_row(
        self, session: AsyncSession, namespace: str
    ) -> RuntimeConfigGeneration:
        normalized = namespace.strip().lower()
        row = await session.scalar(
            select(RuntimeConfigGeneration).where(
                RuntimeConfigGeneration.namespace == normalized
            )
        )
        if row is not None:
            return row
        try:
            async with session.begin_nested():
                row = RuntimeConfigGeneration(namespace=normalized, generation=1)
                session.add(row)
                await session.flush()
                return row
        except IntegrityError:
            row = await session.scalar(
                select(RuntimeConfigGeneration).where(
                    RuntimeConfigGeneration.namespace == normalized
                )
            )
            if row is None:  # pragma: no cover - defensive database race
                raise
            return row

    async def generation(
        self, session: AsyncSession, namespace: str, *, force: bool = False
    ) -> int:
        normalized = namespace.strip().lower()
        now = time.monotonic()
        cached = self._local.get(normalized)
        if not force and cached is not None and cached.expires_at > now:
            return cached.value
        row = await self._ensure_row(session, normalized)
        value = int(row.generation)
        self._local[normalized] = _GenerationSnapshot(
            value=value, expires_at=now + self.poll_seconds
        )
        return value

    async def bump(
        self,
        session: AsyncSession,
        namespace: str,
        *, actor_user_id: int | None = None,
        reason: str = "",
    ) -> int:
        normalized = namespace.strip().lower()
        row = await session.scalar(
            select(RuntimeConfigGeneration)
            .where(RuntimeConfigGeneration.namespace == normalized)
            .with_for_update()
        )
        if row is None:
            row = await self._ensure_row(session, normalized)
        row.generation = int(row.generation) + 1
        row.updated_by_user_id = actor_user_id
        row.reason = reason[:255]
        await session.flush()
        value = int(row.generation)
        self._local[normalized] = _GenerationSnapshot(
            value=value, expires_at=time.monotonic() + self.poll_seconds
        )
        return value

    def invalidate_local(self, namespace: str | None = None) -> None:
        if namespace is None:
            self._local.clear()
        else:
            self._local.pop(namespace.strip().lower(), None)
