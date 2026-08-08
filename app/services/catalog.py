from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.emoji import smart_emoji
from app.db.models import (
    CatalogSection,
    CatalogServiceItem,
    Category,
    DeliveryType,
    Favorite,
    InventoryItem,
    InventoryStatus,
    Offer,
    OfferCatalogPlacement,
    OfferStatus,
    OfferValidityPolicy,
    Provider,
    ProviderStatus,
    User,
    ValidityType,
)


class CatalogService:
    def __init__(self, backfill_cache_ttl_seconds: float = 300.0) -> None:
        # Legacy catalog repair must never run as an N+1 query on every student click.
        # The cache is only a short-lived guard; missing placements are still repaired
        # on demand and all explicit catalog mutations continue to write immediately.
        self._backfill_cache_ttl_seconds = max(5.0, float(backfill_cache_ttl_seconds))
        self._backfilled_until: dict[int, float] = {}

    def invalidate_provider(self, provider_id: int) -> None:
        self._backfilled_until.pop(int(provider_id), None)


    @staticmethod
    def _sellable_stock_condition(now: datetime):
        """Require live stock only for offers delivered from inventory."""
        inventory_types = (
            DeliveryType.INVENTORY_ACCOUNT.value,
            DeliveryType.INVENTORY_CODE.value,
        )
        available_item = exists().where(
            InventoryItem.offer_id == Offer.id,
            InventoryItem.status == InventoryStatus.AVAILABLE.value,
            or_(InventoryItem.expires_at.is_(None), InventoryItem.expires_at > now),
        )
        return or_(~Offer.delivery_type.in_(inventory_types), available_item)

    async def categories(self, session: AsyncSession) -> list[Category]:
        return list(
            (
                await session.scalars(
                    select(Category)
                    .where(Category.is_active.is_(True))
                    .order_by(Category.sort_order, Category.id)
                )
            ).all()
        )

    async def promotion_categories(self, session: AsyncSession) -> list[Category]:
        """Categories that currently contain a live, explicitly discounted offer."""
        now = datetime.now(UTC)
        stmt = (
            select(Category)
            .join(Offer, Offer.category_id == Category.id)
            .join(Provider, Provider.id == Offer.provider_id)
            .where(
                Category.is_active.is_(True),
                Offer.status == OfferStatus.ACTIVE.value,
                Offer.is_active.is_(True),
                Offer.original_price_iqd.is_not(None),
                Offer.original_price_iqd > Offer.price_iqd,
                or_(Offer.start_at.is_(None), Offer.start_at <= now),
                Offer.end_at.is_not(None),
                Offer.end_at > now,
                Provider.status == ProviderStatus.ACTIVE.value,
                Provider.is_active.is_(True),
                self._sellable_stock_condition(now),
            )
            .distinct()
            .order_by(Category.sort_order, Category.id)
        )
        return list((await session.scalars(stmt)).all())

    async def promotion_providers(
        self, session: AsyncSession, limit: int = 50
    ) -> list[Provider]:
        """Active platforms that own at least one live student promotion."""
        now = datetime.now(UTC)
        stmt = (
            select(Provider)
            .join(Offer, Offer.provider_id == Provider.id)
            .where(
                Provider.status == ProviderStatus.ACTIVE.value,
                Provider.is_active.is_(True),
                Offer.status == OfferStatus.ACTIVE.value,
                Offer.is_active.is_(True),
                Offer.original_price_iqd.is_not(None),
                Offer.original_price_iqd > Offer.price_iqd,
                or_(Offer.start_at.is_(None), Offer.start_at <= now),
                Offer.end_at.is_not(None),
                Offer.end_at > now,
                self._sellable_stock_condition(now),
            )
            .distinct()
            .order_by(Provider.name_ar, Provider.id)
            .limit(limit)
        )
        return list((await session.scalars(stmt)).all())

    async def promotion_offers(
        self, session: AsyncSession, provider_id: int, limit: int = 30
    ) -> list[Offer]:
        """Live discounted offers for one platform, excluding depleted stock."""
        now = datetime.now(UTC)
        stmt = (
            select(Offer)
            .join(Provider, Provider.id == Offer.provider_id)
            .options(selectinload(Offer.provider), selectinload(Offer.category))
            .where(
                Offer.provider_id == int(provider_id),
                Offer.status == OfferStatus.ACTIVE.value,
                Offer.is_active.is_(True),
                Offer.original_price_iqd.is_not(None),
                Offer.original_price_iqd > Offer.price_iqd,
                or_(Offer.start_at.is_(None), Offer.start_at <= now),
                Offer.end_at.is_not(None),
                Offer.end_at > now,
                Provider.status == ProviderStatus.ACTIVE.value,
                Provider.is_active.is_(True),
                self._sellable_stock_condition(now),
            )
            .order_by(Offer.end_at, Offer.price_iqd, Offer.id)
            .limit(limit)
        )
        return list((await session.scalars(stmt)).all())

    async def providers(self, session: AsyncSession, limit: int = 50) -> list[Provider]:
        now = datetime.now(UTC)
        stmt = (
            select(Provider)
            .join(Offer, Offer.provider_id == Provider.id)
            .where(
                Provider.status == ProviderStatus.ACTIVE.value,
                Provider.is_active.is_(True),
                Offer.status == OfferStatus.ACTIVE.value,
                Offer.is_active.is_(True),
                or_(Offer.start_at.is_(None), Offer.start_at <= now),
                or_(Offer.end_at.is_(None), Offer.end_at >= now),
            )
            .distinct()
            .order_by(Provider.name_ar)
            .limit(limit)
        )
        return list((await session.scalars(stmt)).all())

    async def get_provider(self, session: AsyncSession, provider_id: int) -> Provider | None:
        return await session.scalar(
            select(Provider).where(
                Provider.id == provider_id,
                Provider.status == ProviderStatus.ACTIVE.value,
                Provider.is_active.is_(True),
            )
        )

    async def create_default_provider_catalog(
        self, session: AsyncSession, provider: Provider
    ) -> list[CatalogSection]:
        existing = list(
            (
                await session.scalars(
                    select(CatalogSection)
                    .where(CatalogSection.provider_id == provider.id)
                    .order_by(CatalogSection.sort_order, CatalogSection.id)
                )
            ).all()
        )
        if existing:
            return existing
        defaults = await self.categories(session)
        sections: list[CatalogSection] = []
        for index, category in enumerate(defaults):
            section = CatalogSection(
                provider_id=provider.id,
                name=category.name,
                emoji=category.emoji,
                description=category.description,
                sort_order=index,
            )
            session.add(section)
            sections.append(section)
        await session.flush()
        return sections

    async def ensure_offer_placement(self, session: AsyncSession, offer: Offer) -> None:
        existing = await session.scalar(
            select(OfferCatalogPlacement.id).where(OfferCatalogPlacement.offer_id == offer.id)
        )
        if existing:
            return
        provider = offer.provider or await session.get(Provider, offer.provider_id)
        category = offer.category or await session.get(Category, offer.category_id)
        if not provider:
            return
        sections = await self.create_default_provider_catalog(session, provider)
        section = None
        if category:
            section = await session.scalar(
                select(CatalogSection).where(
                    CatalogSection.provider_id == provider.id,
                    CatalogSection.name == category.name,
                )
            )
        if not section:
            section = (
                sections[0]
                if sections
                else CatalogSection(
                    provider_id=provider.id,
                    name="عروض أخرى",
                    emoji="🛍",
                    sort_order=999,
                )
            )
            if not sections:
                session.add(section)
                await session.flush()
        service = await session.scalar(
            select(CatalogServiceItem).where(
                CatalogServiceItem.section_id == section.id,
                CatalogServiceItem.name == offer.title,
            )
        )
        if not service:
            service = CatalogServiceItem(
                provider_id=provider.id,
                section_id=section.id,
                name=offer.title,
                emoji=smart_emoji(offer.title),
                description=offer.description,
            )
            session.add(service)
            await session.flush()
        session.add(
            OfferCatalogPlacement(
                offer_id=offer.id,
                provider_id=provider.id,
                section_id=section.id,
                service_id=service.id,
            )
        )
        if not await session.scalar(
            select(OfferValidityPolicy.id).where(OfferValidityPolicy.offer_id == offer.id)
        ):
            session.add(
                OfferValidityPolicy(
                    offer_id=offer.id,
                    validity_type=ValidityType.DAYS_FROM_ACTIVATION.value,
                    duration_value=offer.duration_days or 30,
                )
            )
        await session.flush()

    async def backfill_provider_catalog(self, session: AsyncSession, provider_id: int) -> None:
        provider_id = int(provider_id)
        now_monotonic = time.monotonic()
        if self._backfilled_until.get(provider_id, 0.0) > now_monotonic:
            return

        missing_placement = ~exists().where(
            OfferCatalogPlacement.offer_id == Offer.id
        )
        offers = list(
            (
                await session.scalars(
                    select(Offer)
                    .options(selectinload(Offer.provider), selectinload(Offer.category))
                    .where(
                        Offer.provider_id == provider_id,
                        missing_placement,
                    )
                    .order_by(Offer.id)
                )
            ).all()
        )
        for offer in offers:
            await self.ensure_offer_placement(session, offer)
        self._backfilled_until[provider_id] = (
            now_monotonic + self._backfill_cache_ttl_seconds
        )
        if len(self._backfilled_until) > 10_000:
            self._backfilled_until = {
                key: expires
                for key, expires in self._backfilled_until.items()
                if expires > now_monotonic
            }

    async def sections(self, session: AsyncSession, provider_id: int) -> list[CatalogSection]:
        await self.backfill_provider_catalog(session, provider_id)
        now = datetime.now(UTC)
        stmt = (
            select(CatalogSection)
            .join(OfferCatalogPlacement, OfferCatalogPlacement.section_id == CatalogSection.id)
            .join(Offer, Offer.id == OfferCatalogPlacement.offer_id)
            .where(
                CatalogSection.provider_id == provider_id,
                CatalogSection.is_active.is_(True),
                OfferCatalogPlacement.is_active.is_(True),
                Offer.status == OfferStatus.ACTIVE.value,
                Offer.is_active.is_(True),
                or_(Offer.start_at.is_(None), Offer.start_at <= now),
                or_(Offer.end_at.is_(None), Offer.end_at >= now),
            )
            .distinct()
            .order_by(CatalogSection.sort_order, CatalogSection.id)
        )
        return list((await session.scalars(stmt)).all())

    async def section(self, session: AsyncSession, section_id: int) -> CatalogSection | None:
        return await session.get(CatalogSection, section_id)

    async def services(
        self, session: AsyncSession, provider_id: int, section_id: int
    ) -> list[CatalogServiceItem]:
        now = datetime.now(UTC)
        stmt = (
            select(CatalogServiceItem)
            .join(OfferCatalogPlacement, OfferCatalogPlacement.service_id == CatalogServiceItem.id)
            .join(Offer, Offer.id == OfferCatalogPlacement.offer_id)
            .where(
                CatalogServiceItem.provider_id == provider_id,
                CatalogServiceItem.section_id == section_id,
                CatalogServiceItem.is_active.is_(True),
                OfferCatalogPlacement.is_active.is_(True),
                Offer.status == OfferStatus.ACTIVE.value,
                Offer.is_active.is_(True),
                or_(Offer.start_at.is_(None), Offer.start_at <= now),
                or_(Offer.end_at.is_(None), Offer.end_at >= now),
            )
            .distinct()
            .order_by(CatalogServiceItem.sort_order, CatalogServiceItem.id)
        )
        return list((await session.scalars(stmt)).all())

    async def service(self, session: AsyncSession, service_id: int) -> CatalogServiceItem | None:
        return await session.get(CatalogServiceItem, service_id)

    async def offers_for_service(
        self, session: AsyncSession, provider_id: int, service_id: int, limit: int = 30
    ) -> list[Offer]:
        now = datetime.now(UTC)
        stmt = (
            select(Offer)
            .join(OfferCatalogPlacement, OfferCatalogPlacement.offer_id == Offer.id)
            .join(Provider, Provider.id == Offer.provider_id)
            .options(selectinload(Offer.provider), selectinload(Offer.category))
            .where(
                Offer.provider_id == provider_id,
                OfferCatalogPlacement.service_id == service_id,
                OfferCatalogPlacement.is_active.is_(True),
                Offer.status == OfferStatus.ACTIVE.value,
                Offer.is_active.is_(True),
                Provider.status == ProviderStatus.ACTIVE.value,
                Provider.is_active.is_(True),
                or_(Offer.start_at.is_(None), Offer.start_at <= now),
                or_(Offer.end_at.is_(None), Offer.end_at >= now),
            )
            .order_by(OfferCatalogPlacement.sort_order, Offer.price_iqd, Offer.id)
            .limit(limit)
        )
        return list((await session.scalars(stmt)).all())

    async def offers(
        self,
        session: AsyncSession,
        category_id: int | None = None,
        featured_only: bool = False,
        limit: int = 30,
    ) -> list[Offer]:
        now = datetime.now(UTC)
        conditions = [
            Offer.status == OfferStatus.ACTIVE.value,
            Offer.is_active.is_(True),
            Provider.status == ProviderStatus.ACTIVE.value,
            Provider.is_active.is_(True),
            or_(Offer.start_at.is_(None), Offer.start_at <= now),
            or_(Offer.end_at.is_(None), Offer.end_at >= now),
        ]
        if category_id:
            conditions.append(Offer.category_id == category_id)
        if featured_only:
            conditions.extend(
                [
                    Offer.original_price_iqd.is_not(None),
                    Offer.original_price_iqd > Offer.price_iqd,
                    Offer.end_at.is_not(None),
                    Offer.end_at > now,
                    self._sellable_stock_condition(now),
                ]
            )
        stmt = (
            select(Offer)
            .join(Provider, Provider.id == Offer.provider_id)
            .options(selectinload(Offer.provider), selectinload(Offer.category))
            .where(and_(*conditions))
            .order_by(Offer.created_at.desc())
            .limit(limit)
        )
        return list((await session.scalars(stmt)).all())

    async def get_offer(self, session: AsyncSession, offer_id: int) -> Offer | None:
        # Read paths must stay read-only. Legacy placement repair belongs to the
        # provider catalog backfill path, not every offer-details button.
        return await session.scalar(
            select(Offer)
            .options(selectinload(Offer.provider), selectinload(Offer.category))
            .where(Offer.id == offer_id)
        )

    async def toggle_favorite(self, session: AsyncSession, user: User, offer_id: int) -> bool:
        favorite = await session.scalar(
            select(Favorite).where(Favorite.user_id == user.id, Favorite.offer_id == offer_id)
        )
        if favorite:
            await session.delete(favorite)
            return False
        session.add(Favorite(user_id=user.id, offer_id=offer_id))
        return True

    async def favorites(self, session: AsyncSession, user: User) -> list[Offer]:
        return list(
            (
                await session.scalars(
                    select(Offer)
                    .join(Favorite, Favorite.offer_id == Offer.id)
                    .options(selectinload(Offer.provider))
                    .join(Provider, Provider.id == Offer.provider_id)
                    .where(
                        Favorite.user_id == user.id,
                        Offer.status == OfferStatus.ACTIVE.value,
                        Offer.is_active.is_(True),
                        Provider.status == ProviderStatus.ACTIVE.value,
                        Provider.is_active.is_(True),
                        or_(Offer.start_at.is_(None), Offer.start_at <= datetime.now(UTC)),
                        or_(Offer.end_at.is_(None), Offer.end_at > datetime.now(UTC)),
                    )
                    .order_by(Favorite.created_at.desc())
                )
            ).all()
        )

    async def counts(self, session: AsyncSession) -> dict[str, int]:
        return {
            "providers": int(await session.scalar(select(func.count()).select_from(Provider)) or 0),
            "offers": int(await session.scalar(select(func.count()).select_from(Offer)) or 0),
            "categories": int(
                await session.scalar(select(func.count()).select_from(Category)) or 0
            ),
        }
