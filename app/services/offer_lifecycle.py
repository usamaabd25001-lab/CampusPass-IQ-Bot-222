from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Announcement,
    AnnouncementStatus,
    DeliveryType,
    InventoryItem,
    InventoryStatus,
    Offer,
    OfferStatus,
    Provider,
    ProviderStaff,
    SystemSetting,
    User,
)
from app.services.announcements import AnnouncementService
from app.services.notifications import NotificationService
from app.services.templates import MessageTemplateService


class OfferLifecycleService:
    """Owns offer-time and stock transitions.

    The service is deliberately idempotent: the scheduler can run more than once
    without sending duplicate broadcasts or repeating transition alerts.
    """

    INVENTORY_DELIVERY_TYPES = {
        DeliveryType.INVENTORY_ACCOUNT.value,
        DeliveryType.INVENTORY_CODE.value,
    }

    def __init__(
        self,
        announcements: AnnouncementService,
        templates: MessageTemplateService,
        notifications: NotificationService,
    ) -> None:
        self.announcements = announcements
        self.templates = templates
        self.notifications = notifications

    @staticmethod
    async def _claim_event(
        session: AsyncSession,
        key: str,
        value: str = "done",
    ) -> bool:
        row = await session.scalar(
            select(SystemSetting).where(SystemSetting.key == key).with_for_update()
        )
        if row is not None:
            return False
        session.add(SystemSetting(key=key[:120], value=value[:2000], is_secret=False))
        await session.flush()
        return True

    async def queue_launch_announcement(
        self,
        session: AsyncSession,
        offer: Offer,
        actor_user_id: int | None,
    ) -> Announcement | None:
        """Create one student broadcast for the first successful, purchasable publication."""
        if offer.delivery_type in self.INVENTORY_DELIVERY_TYPES:
            available = int(
                await session.scalar(
                    select(func.count()).select_from(InventoryItem).where(
                        InventoryItem.offer_id == offer.id,
                        InventoryItem.status == InventoryStatus.AVAILABLE.value,
                        or_(InventoryItem.expires_at.is_(None), InventoryItem.expires_at > datetime.now(UTC)),
                    )
                )
                or 0
            )
            if available <= 0:
                return None
        if not await self._claim_event(session, f"offer.launch.{offer.id}"):
            return None
        provider = offer.provider or await session.get(Provider, offer.provider_id)
        if provider is None:
            return None
        ends_at = (
            offer.end_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
            if offer.end_at
            else "مستمر حتى نفاد المخزون"
        )
        body = await self.templates.render(
            session,
            "offer.launched",
            {
                "platform_name": provider.name_ar,
                "description": offer.description or offer.title,
                "price": f"{offer.price_iqd:,} د.ع",
                "ends_at": ends_at,
            },
        )
        announcement = Announcement(
            title=f"🔥 عرض جديد من {provider.name_ar}",
            body=body,
            media_type="photo" if (offer.image_file_id or provider.logo_file_id) else None,
            media_file_id=offer.image_file_id or provider.logo_file_id,
            button_text="🔥 مشاهدة العرض",
            button_url="action:offers",
            target_scope="students",
            starts_at=datetime.now(UTC),
            ends_at=offer.end_at,
            status=AnnouncementStatus.SCHEDULED.value,
            created_by_user_id=actor_user_id,
        )
        session.add(announcement)
        await session.flush()
        return announcement

    async def _notify_provider_once(
        self,
        session: AsyncSession,
        offer: Offer,
        event: str,
        title: str,
        body: str,
    ) -> None:
        key = f"offer.alert.{event}.{offer.id}.{offer.updated_at.timestamp():.0f}"
        if not await self._claim_event(session, key):
            return
        users = list(
            (
                await session.scalars(
                    select(User)
                    .join(ProviderStaff, ProviderStaff.user_id == User.id)
                    .where(
                        ProviderStaff.provider_id == offer.provider_id,
                        ProviderStaff.is_active.is_(True),
                        or_(
                            ProviderStaff.can_manage_inventory.is_(True),
                            ProviderStaff.can_manage_offers.is_(True),
                            or_(
                                ProviderStaff.role == "OWNER",
                                func.lower(ProviderStaff.title).in_(
                                    ("owner", "platform_owner", "provider_owner", "مالك")
                                ),
                            ),
                        ),
                        User.is_active.is_(True),
                    )
                    .distinct()
                )
            ).all()
        )
        for user in users:
            await self.notifications.send_user(
                session,
                user,
                title,
                body,
                idempotency_key=f"offer:{event}:{offer.id}:user:{user.id}",
            )

    async def run_cycle(self, session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
        """Apply only due lifecycle transitions using bounded indexed queries."""

        now = now or datetime.now(UTC)
        expired_result = await session.execute(
            update(InventoryItem)
            .where(
                InventoryItem.status == InventoryStatus.AVAILABLE.value,
                InventoryItem.expires_at.is_not(None),
                InventoryItem.expires_at <= now,
            )
            .values(
                status=InventoryStatus.EXPIRED.value,
                remediation_note="انتهت الصلاحية تلقائيًا",
            )
        )
        inventory_expired = max(0, int(expired_result.rowcount or 0))

        candidate_statuses = {
            OfferStatus.ACTIVE.value,
            OfferStatus.OUT_OF_STOCK.value,
        }
        offers = list(
            (
                await session.scalars(
                    select(Offer)
                    .options(selectinload(Offer.provider))
                    .where(
                        Offer.status.in_(candidate_statuses),
                        or_(
                            and_(
                                Offer.end_at.is_not(None),
                                Offer.end_at <= now,
                            ),
                            Offer.delivery_type.in_(self.INVENTORY_DELIVERY_TYPES),
                        ),
                    )
                    .order_by(Offer.id)
                )
            ).all()
        )

        inventory_offer_ids = [
            offer.id
            for offer in offers
            if offer.delivery_type in self.INVENTORY_DELIVERY_TYPES
        ]
        counts: dict[int, int] = {}
        if inventory_offer_ids:
            counts = dict(
                (
                    await session.execute(
                        select(InventoryItem.offer_id, func.count(InventoryItem.id))
                        .where(
                            InventoryItem.offer_id.in_(inventory_offer_ids),
                            InventoryItem.status == InventoryStatus.AVAILABLE.value,
                            or_(
                                InventoryItem.expires_at.is_(None),
                                InventoryItem.expires_at > now,
                            ),
                        )
                        .group_by(InventoryItem.offer_id)
                    )
                ).all()
            )

        result = {
            "inventory_expired": inventory_expired,
            "promotions_ended": 0,
            "out_of_stock": 0,
            "reactivated": 0,
            "expired": 0,
        }
        for offer in offers:
            inventory_offer = offer.delivery_type in self.INVENTORY_DELIVERY_TYPES
            available = int(counts.get(offer.id, 0))
            ended = bool(offer.end_at and offer.end_at <= now)
            promotion = offer.original_price_iqd is not None

            if ended and promotion:
                offer.price_iqd = int(offer.original_price_iqd or offer.price_iqd)
                offer.original_price_iqd = None
                offer.start_at = None
                offer.end_at = None
                if inventory_offer and available <= 0:
                    offer.status = OfferStatus.OUT_OF_STOCK.value
                    offer.is_active = False
                else:
                    offer.status = OfferStatus.ACTIVE.value
                    offer.is_active = True
                result["promotions_ended"] += 1
                await self._notify_provider_once(
                    session,
                    offer,
                    "promotion-ended",
                    "انتهى العرض المؤقت",
                    f"انتهى الخصم على {offer.title} وعاد السعر الطبيعي تلقائيًا.",
                )
                continue

            if ended and not promotion:
                offer.status = OfferStatus.EXPIRED.value
                offer.is_active = False
                result["expired"] += 1
                await self._notify_provider_once(
                    session,
                    offer,
                    "expired",
                    "انتهت صلاحية العرض",
                    f"تم إخفاء {offer.title} تلقائيًا بعد انتهاء وقته.",
                )
                continue

            if inventory_offer and available <= 0 and offer.status == OfferStatus.ACTIVE.value:
                if promotion:
                    offer.price_iqd = int(offer.original_price_iqd or offer.price_iqd)
                    offer.original_price_iqd = None
                    offer.start_at = None
                    offer.end_at = None
                offer.status = OfferStatus.OUT_OF_STOCK.value
                offer.is_active = False
                result["out_of_stock"] += 1
                await self._notify_provider_once(
                    session,
                    offer,
                    "out-of-stock",
                    "نفد مخزون العرض",
                    f"تم إخفاء {offer.title} تلقائيًا. افتح العروض المتوقفة لتحديث الحسابات أو إضافة مخزون.",
                )
                continue

            if (
                inventory_offer
                and available > 0
                and offer.status == OfferStatus.OUT_OF_STOCK.value
            ):
                offer.status = OfferStatus.ACTIVE.value
                offer.is_active = True
                result["reactivated"] += 1

        await session.flush()
        return result

