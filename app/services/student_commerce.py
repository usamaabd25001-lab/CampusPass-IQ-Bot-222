from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.student_commerce import (
    FavoriteTarget,
    InvoiceBreakdown,
    calculate_invoice,
    format_offer_button,
    net_wallet_fee_deduction,
    profile_completion,
)
from app.db.models import (
    CatalogSection,
    CatalogServiceItem,
    CheckoutSnapshot,
    FavoriteTargetType,
    Offer,
    OfferCatalogPlacement,
    OfferStatus,
    Provider,
    ProviderBrandProfile,
    ProviderStatus,
    ProviderWorkingHour,
    Review,
    StudentSubscription,
    StudentSubscriptionStatus,
    StudentFavorite,
    StudentProfile,
    User,
)


class StudentCommerceService:
    """Student-facing marketplace and checkout orchestration for V11.1."""

    async def profile_status(self, profile: StudentProfile | None) -> tuple[bool, tuple[str, ...]]:
        if profile is None:
            return False, profile_completion(None).missing_fields
        result = profile_completion(
            {
                "full_name": profile.full_name,
                "phone": profile.phone,
                "governorate": profile.governorate,
                "university": profile.university,
                "college": profile.college,
                "department": profile.department,
                "stage": profile.stage,
            }
        )
        return result.complete, result.missing_fields

    async def provider_cards(self, session: AsyncSession, *, limit: int = 50) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        providers = list(
            (
                await session.scalars(
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
                    .order_by(Provider.name_ar, Provider.id)
                    .limit(max(1, min(int(limit), 100)))
                )
            ).all()
        )
        if not providers:
            return []
        provider_ids = [item.id for item in providers]
        rating_rows = (
            await session.execute(
                select(
                    Review.provider_id,
                    func.coalesce(func.avg(Review.rating), 0),
                    func.count(Review.id),
                )
                .where(Review.provider_id.in_(provider_ids))
                .group_by(Review.provider_id)
            )
        ).all()
        rating_map = {
            int(provider_id): (float(average or 0), int(count or 0))
            for provider_id, average, count in rating_rows
        }
        subscriber_rows = (
            await session.execute(
                select(StudentSubscription.provider_id, func.count(StudentSubscription.id))
                .where(
                    StudentSubscription.provider_id.in_(provider_ids),
                    StudentSubscription.status.in_((
                        StudentSubscriptionStatus.ACTIVE.value,
                        StudentSubscriptionStatus.EXPIRING.value,
                    )),
                )
                .group_by(StudentSubscription.provider_id)
            )
        ).all()
        active_offer_map = {int(provider_id): int(count or 0) for provider_id, count in subscriber_rows}
        branding = {
            row.provider_id: row
            for row in (
                await session.scalars(
                    select(ProviderBrandProfile).where(ProviderBrandProfile.provider_id.in_(provider_ids))
                )
            ).all()
        }
        return [
            {
                "id": provider.id,
                "name": provider.name_ar,
                "description": provider.description,
                "logo_file_id": (branding.get(provider.id).logo_file_id if branding.get(provider.id) else provider.logo_file_id),
                "logo_url": (branding.get(provider.id).logo_url if branding.get(provider.id) else provider.logo_url),
                "rating": rating_map.get(provider.id, (0.0, 0))[0],
                "rating_count": rating_map.get(provider.id, (0.0, 0))[1],
                "subscriber_count": active_offer_map.get(provider.id, 0),
            }
            for provider in providers
        ]

    async def sections(self, session: AsyncSession, provider_id: int) -> list[CatalogSection]:
        live_offer = (
            select(OfferCatalogPlacement.id)
            .join(Offer, Offer.id == OfferCatalogPlacement.offer_id)
            .where(
                OfferCatalogPlacement.section_id == CatalogSection.id,
                OfferCatalogPlacement.provider_id == int(provider_id),
                OfferCatalogPlacement.is_active.is_(True),
                Offer.status == OfferStatus.ACTIVE.value,
                Offer.is_active.is_(True),
            )
            .exists()
        )
        return list(
            (
                await session.scalars(
                    select(CatalogSection)
                    .where(
                        CatalogSection.provider_id == int(provider_id),
                        CatalogSection.is_active.is_(True),
                        live_offer,
                    )
                    .order_by(CatalogSection.sort_order, CatalogSection.id)
                )
            ).all()
        )

    async def services(self, session: AsyncSession, section_id: int) -> list[CatalogServiceItem]:
        live_offer = (
            select(OfferCatalogPlacement.id)
            .join(Offer, Offer.id == OfferCatalogPlacement.offer_id)
            .where(
                OfferCatalogPlacement.service_id == CatalogServiceItem.id,
                OfferCatalogPlacement.is_active.is_(True),
                Offer.status == OfferStatus.ACTIVE.value,
                Offer.is_active.is_(True),
            )
            .exists()
        )
        return list(
            (
                await session.scalars(
                    select(CatalogServiceItem)
                    .where(
                        CatalogServiceItem.section_id == int(section_id),
                        CatalogServiceItem.is_active.is_(True),
                        live_offer,
                    )
                    .order_by(CatalogServiceItem.sort_order, CatalogServiceItem.id)
                )
            ).all()
        )

    async def offers(self, session: AsyncSession, service_id: int) -> list[Offer]:
        now = datetime.now(UTC)
        return list(
            (
                await session.scalars(
                    select(Offer)
                    .join(OfferCatalogPlacement, OfferCatalogPlacement.offer_id == Offer.id)
                    .options(selectinload(Offer.provider))
                    .where(
                        OfferCatalogPlacement.service_id == int(service_id),
                        OfferCatalogPlacement.is_active.is_(True),
                        Offer.status == OfferStatus.ACTIVE.value,
                        Offer.is_active.is_(True),
                        or_(Offer.start_at.is_(None), Offer.start_at <= now),
                        or_(Offer.end_at.is_(None), Offer.end_at >= now),
                    )
                    .order_by(Offer.price_iqd, Offer.duration_days, Offer.id)
                )
            ).all()
        )

    @staticmethod
    def offer_button_text(offer: Offer) -> str:
        duration = (
            f"{offer.duration_days} يوم"
            if offer.duration_days and offer.duration_days not in {30, 90, 365}
            else {30: "شهر واحد", 90: "3 أشهر", 365: "سنة"}.get(offer.duration_days or 0, "حسب العرض")
        )
        return format_offer_button(
            service_name=offer.title,
            duration_label=duration,
            price_iqd=offer.price_iqd,
        )

    async def toggle_favorite(
        self,
        session: AsyncSession,
        *,
        user: User,
        target_type: str,
        target_id: int,
    ) -> bool:
        normalized = FavoriteTarget(target_type).value
        target = await self._resolve_favorite_target(session, normalized, int(target_id))
        if target is None:
            raise ValueError("العنصر غير متاح")
        existing = await session.scalar(
            select(StudentFavorite).where(
                StudentFavorite.user_id == user.id,
                StudentFavorite.target_type == normalized,
                StudentFavorite.target_id == int(target_id),
            )
        )
        if existing:
            await session.delete(existing)
            await session.flush()
            return False
        session.add(
            StudentFavorite(
                user_id=user.id,
                target_type=normalized,
                target_id=int(target_id),
            )
        )
        await session.flush()
        return True

    async def favorites(self, session: AsyncSession, *, user: User) -> dict[str, list[Any]]:
        rows = list(
            (
                await session.scalars(
                    select(StudentFavorite)
                    .where(StudentFavorite.user_id == user.id)
                    .order_by(StudentFavorite.created_at.desc(), StudentFavorite.id.desc())
                )
            ).all()
        )
        grouped: dict[str, list[Any]] = {target.value: [] for target in FavoriteTarget}
        for row in rows:
            target = await self._resolve_favorite_target(session, row.target_type, row.target_id)
            if target is not None:
                grouped.setdefault(row.target_type, []).append(target)
        return grouped

    async def _resolve_favorite_target(
        self, session: AsyncSession, target_type: str, target_id: int
    ) -> Any | None:
        if target_type == FavoriteTarget.PROVIDER.value:
            return await session.scalar(
                select(Provider).where(
                    Provider.id == target_id,
                    Provider.status == ProviderStatus.ACTIVE.value,
                    Provider.is_active.is_(True),
                )
            )
        if target_type == FavoriteTarget.SECTION.value:
            return await session.scalar(
                select(CatalogSection).where(
                    CatalogSection.id == target_id,
                    CatalogSection.is_active.is_(True),
                )
            )
        if target_type == FavoriteTarget.OFFER.value:
            return await session.scalar(
                select(Offer).where(
                    Offer.id == target_id,
                    Offer.status == OfferStatus.ACTIVE.value,
                    Offer.is_active.is_(True),
                )
            )
        return None

    async def persist_checkout_snapshot(
        self,
        session: AsyncSession,
        *,
        order_id: int,
        user_id: int,
        provider_id: int,
        offer_id: int,
        invoice: InvoiceBreakdown,
        metadata: dict[str, Any] | None = None,
    ) -> CheckoutSnapshot:
        row = await session.scalar(
            select(CheckoutSnapshot).where(CheckoutSnapshot.order_id == int(order_id))
        )
        values = asdict(invoice)
        if row is None:
            row = CheckoutSnapshot(
                order_id=int(order_id),
                user_id=int(user_id),
                provider_id=int(provider_id),
                offer_id=int(offer_id),
                service_price_iqd=values["service_price_iqd"],
                discount_iqd=values["discount_iqd"],
                bot_fee_iqd=values["bot_fee_iqd"],
                wallet_fee_deduction_iqd=values["wallet_fee_deduction_iqd"],
                cash_due_iqd=values["cash_due_iqd"],
                metadata_json=metadata or {},
            )
            session.add(row)
        else:
            row.service_price_iqd = values["service_price_iqd"]
            row.discount_iqd = values["discount_iqd"]
            row.bot_fee_iqd = values["bot_fee_iqd"]
            row.wallet_fee_deduction_iqd = values["wallet_fee_deduction_iqd"]
            row.cash_due_iqd = values["cash_due_iqd"]
            merged_metadata = dict(row.metadata_json or {})
            if metadata:
                merged_metadata.update(metadata)
            row.metadata_json = merged_metadata
        await session.flush()
        return row


    async def sync_checkout_snapshot_from_order(
        self,
        session: AsyncSession,
        *,
        order: Any,
        user_id: int,
        service_discount_iqd: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> CheckoutSnapshot:
        """Synchronize the immutable checkout view with the current locked order.

        The original service price is preserved from the first snapshot. Monetary
        coupons are represented as service discounts, while fee waivers reduce
        the bot-fee field instead of being misreported as a service discount.
        """

        existing = await session.scalar(
            select(CheckoutSnapshot).where(CheckoutSnapshot.order_id == int(order.id))
        )
        original_service_price = (
            int(existing.service_price_iqd)
            if existing is not None
            else max(0, int(order.subtotal_iqd) + max(0, int(service_discount_iqd)))
        )
        snapshot = dict(order.payment_snapshot or {})
        current_bot_fee = max(0, int(order.service_fee_iqd or 0))
        wallet_fee_used = net_wallet_fee_deduction(
            snapshot, current_bot_fee_iqd=current_bot_fee
        )
        invoice = InvoiceBreakdown(
            service_price_iqd=original_service_price,
            discount_iqd=min(max(0, int(service_discount_iqd)), original_service_price),
            bot_fee_iqd=current_bot_fee,
            wallet_fee_deduction_iqd=wallet_fee_used,
            cash_due_iqd=max(0, int(order.total_iqd or 0)),
            wallet_balance_after_iqd=max(
                0, int(snapshot.get("wallet_balance_before_iqd", 0) or 0) - wallet_fee_used
            ),
        )
        return await self.persist_checkout_snapshot(
            session,
            order_id=int(order.id),
            user_id=int(user_id),
            provider_id=int(order.provider_id),
            offer_id=int(order.offer_id),
            invoice=invoice,
            metadata=metadata,
        )

    async def working_status(
        self, session: AsyncSession, provider_id: int, *, now: datetime | None = None
    ) -> dict[str, Any]:
        current = now or datetime.now(ZoneInfo("Asia/Baghdad"))
        rows = list(
            (
                await session.scalars(
                    select(ProviderWorkingHour)
                    .where(
                        ProviderWorkingHour.provider_id == int(provider_id),
                        ProviderWorkingHour.is_active.is_(True),
                    )
                    .order_by(ProviderWorkingHour.weekday)
                )
            ).all()
        )
        if not rows:
            return {"configured": False, "is_open": True, "next_open_at": None}
        today = next((row for row in rows if row.weekday == current.weekday()), None)
        current_minute = current.hour * 60 + current.minute
        if today and not today.is_closed and today.opens_minute <= current_minute < today.closes_minute:
            return {"configured": True, "is_open": True, "next_open_at": None}
        for offset in range(0, 8):
            target_day = (current.weekday() + offset) % 7
            row = next((item for item in rows if item.weekday == target_day and not item.is_closed), None)
            if row is None:
                continue
            if offset == 0 and row.opens_minute <= current_minute:
                continue
            opening = (current + timedelta(days=offset)).replace(
                hour=row.opens_minute // 60,
                minute=row.opens_minute % 60,
                second=0,
                microsecond=0,
            )
            return {"configured": True, "is_open": False, "next_open_at": opening}
        return {"configured": True, "is_open": False, "next_open_at": None}

    async def invoice_preview(
        self,
        *,
        service_price_iqd: int,
        bot_fee_iqd: int,
        wallet_balance_iqd: int,
        discount_iqd: int = 0,
    ) -> InvoiceBreakdown:
        return calculate_invoice(
            service_price_iqd=service_price_iqd,
            bot_fee_iqd=bot_fee_iqd,
            wallet_balance_iqd=wallet_balance_iqd,
            discount_iqd=discount_iqd,
        )

    async def clear_legacy_offer_favorites(self, session: AsyncSession, *, user_id: int) -> int:
        result = await session.execute(delete(StudentFavorite).where(StudentFavorite.user_id == int(user_id)))
        return int(result.rowcount or 0)
