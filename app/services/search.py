from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Offer, Provider

class SearchService:
    async def offers(self, session: AsyncSession, query: str, limit: int = 20):
        term = f"%{query.strip()}%"
        return list((await session.scalars(select(Offer).join(Provider).where(
            Offer.is_active.is_(True), Provider.is_active.is_(True),
            or_(Offer.title.ilike(term), Offer.description.ilike(term),
                Provider.name_ar.ilike(term), Provider.name_en.ilike(term))
        ).order_by(Offer.updated_at.desc()).limit(min(max(limit, 1), 50)))).all())
