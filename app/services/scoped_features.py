from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import FeatureFlag, ScopedFeatureOverride

class ScopedFeatureService:
    async def enabled(self, session: AsyncSession, key: str, *, provider_id: int | None = None,
                      user_id: int | None = None, default: bool = False) -> bool:
        scopes = []
        if user_id is not None: scopes.append(("user", user_id))
        if provider_id is not None: scopes.append(("provider", provider_id))
        scopes.extend([("students", 0), ("global", 0)])
        for scope_type, scope_id in scopes:
            row = await session.scalar(select(ScopedFeatureOverride).where(
                ScopedFeatureOverride.feature_key == key,
                ScopedFeatureOverride.scope_type == scope_type,
                ScopedFeatureOverride.scope_id == scope_id))
            if row is not None:
                return bool(row.is_enabled)
        global_flag = await session.scalar(select(FeatureFlag).where(FeatureFlag.key == key))
        return bool(global_flag.is_enabled) if global_flag else default
