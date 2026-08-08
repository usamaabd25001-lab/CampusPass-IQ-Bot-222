from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FeatureFlag
from app.services.cache_coherence import CacheCoherenceService


class FeatureService:
    """Feature flags with generation-aware in-process caching.

    Each process keeps the hot path in memory. The shared generation row makes
    owner changes visible to every Render process within a short bounded window,
    instead of waiting for a long TTL or relying on best-effort pub/sub delivery.
    """

    def __init__(
        self,
        cache_coherence: CacheCoherenceService | None = None,
        ttl_seconds: float = 60.0,
    ) -> None:
        self._ttl = max(0.25, float(ttl_seconds))
        self._cache: dict[str, tuple[float, bool]] = {}
        self._coherence = cache_coherence or CacheCoherenceService()
        self._generation = 0

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)

    async def _refresh_generation(self, session: AsyncSession) -> None:
        generation = await self._coherence.generation(session, "features")
        if generation != self._generation:
            self._generation = generation
            self._cache.clear()

    async def enabled(self, session: AsyncSession, key: str, default: bool = False) -> bool:
        await self._refresh_generation(session)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
        flag = await session.scalar(select(FeatureFlag).where(FeatureFlag.key == key))
        value = flag.is_enabled if flag else default
        self._cache[key] = (now + self._ttl, bool(value))
        return bool(value)

    async def toggle(
        self, session: AsyncSession, key: str, actor_user_id: int | None = None
    ) -> FeatureFlag | None:
        flag = await session.scalar(
            select(FeatureFlag).where(FeatureFlag.key == key).with_for_update()
        )
        if not flag:
            return None
        flag.is_enabled = not flag.is_enabled
        flag.updated_by_user_id = actor_user_id
        await session.flush()
        self.invalidate(key)
        self._generation = await self._coherence.bump(
            session,
            "features",
            actor_user_id=actor_user_id,
            reason=f"toggle:{key}",
        )
        return flag
