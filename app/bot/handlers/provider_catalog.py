from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.provider import _require_entitlement, _staff, _staff_for_provider
from app.bot.states import (
    ProviderBrandingStates,
    ProviderCatalogEditStates,
    ProviderCatalogSectionStates,
    ProviderCatalogServiceStates,
    ProviderCredentialUpdateStates,
    ProviderEmailStates,
    ProviderGuideStates,
    ProviderFulfillmentStates,
    ProviderInventoryStates,
    ProviderOfferStates,
    ProviderPaymentMethodStates,
    ProviderTicketReplyStates,
)
from app.bot.keyboards.inline import with_navigation
from app.bot.ui import edit_or_send, callback_notice
from app.core.emoji import smart_emoji
from app.core.utils import safe
from app.db.models import (
    ActivationMode,
    CatalogSection,
    CatalogServiceItem,
    Category,
    DeliveryType,
    EmailAccount,
    InventoryFingerprint,
    InventoryItem,
    InventoryStatus,
    Offer,
    OfferActivationGuide,
    OfferCatalogPlacement,
    OfferStatus,
    OfferValidityPolicy,
    Order,
    PaymentMethod,
    ProviderStaff,
    SubscriptionStartTrigger,
    SupportTicket,
    TicketMessage,
    TicketStatus,
    ValidityType,
)
from app.services.branding import BrandingCandidate
from app.services.container import Services

router = Router(name="provider_catalog")
logger = logging.getLogger(__name__)


def _markup(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return with_navigation(InlineKeyboardMarkup(inline_keyboard=rows))


async def _active_manager(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
    *,
    permission: str,
) -> tuple[ProviderStaff | None, dict]:
    if not message.from_user:
        return None, {}
    data = await state.get_data()
    expected_provider = int(data.get("provider_id") or 0)
    _user, staff = await _staff_for_provider(
        session, services, message.from_user.id, expected_provider
    )
    if not staff:
        await state.clear()
        await message.answer("تعذر فتح المنصة المرتبطة بهذه العملية. افتح لوحة المنصة مجددًا.")
        return None, data
    if not getattr(staff, permission, False):
        await state.clear()
        await message.answer("لا تملك الصلاحية المطلوبة لهذه العملية.")
        return None, data
    return staff, data


async def _active_callback_manager(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
    *,
    permission: str,
    expected_state: str,
) -> tuple[ProviderStaff | None, dict]:
    """Validate stale/forged wizard callbacks against the active provider session."""
    if not callback.from_user or not callback.message:
        return None, {}
    current_state = await state.get_state()
    if current_state != expected_state:
        # A delayed click from the previous wizard screen can arrive after the
        # next state was already stored. Never replace the current screen with
        # a false "step expired" warning; acknowledge happened at handler entry,
        # so the stale callback is safely ignored without touching FSM data.
        logger.debug(
            "Ignored stale provider wizard callback data=%s expected=%s current=%s user=%s",
            callback.data,
            expected_state,
            current_state,
            callback.from_user.id,
        )
        return None, await state.get_data()
    data = await state.get_data()
    expected_provider = int(data.get("provider_id") or 0)
    _user, staff = await _staff_for_provider(
        session, services, callback.from_user.id, expected_provider
    )
    if not staff:
        await state.clear()
        await edit_or_send(callback.message, "تعذر فتح المنصة المرتبطة بهذه العملية.")
        return None, data
    if not getattr(staff, permission, False):
        await state.clear()
        await edit_or_send(callback.message, "لا تملك الصلاحية المطلوبة لهذه العملية.")
        return None, data
    return staff, data


async def _catalog_overview(
    message: Message,
    session: AsyncSession,
    services: Services,
    staff: ProviderStaff,
) -> None:
    provider = staff.provider
    now = datetime.now(UTC)
    # One bounded maintenance query keeps stale inventory from appearing as available.
    stale_items = list(
        (
            await session.scalars(
                select(InventoryItem)
                .join(Offer, Offer.id == InventoryItem.offer_id)
                .where(
                    Offer.provider_id == provider.id,
                    InventoryItem.status == InventoryStatus.AVAILABLE.value,
                    InventoryItem.expires_at.is_not(None),
                    InventoryItem.expires_at <= now,
                )
                .limit(500)
            )
        ).all()
    )
    for item in stale_items:
        item.status = InventoryStatus.EXPIRED.value
        item.remediation_note = "انتهت الصلاحية تلقائيًا"
    if stale_items:
        await session.flush()

    total_offers = int(
        await session.scalar(
            select(func.count()).select_from(Offer).where(Offer.provider_id == provider.id)
        )
        or 0
    )
    await edit_or_send(
        message,
        f"🛍 <b>متجري والعروض — {safe(provider.name_ar)}</b>\n\n"
        "<b>القسم</b> = تصنيف، <b>الخدمة</b> = منتج/خدمة، "
        "<b>العرض</b> = باقة سعرية.\n"
        f"إجمالي العروض: <b>{total_offers}</b>",
        reply_markup=_markup(
            [
                [
                    InlineKeyboardButton(
                        text="➕ إضافة عرض",
                        web_app=WebAppInfo(
                            url=(services.settings.public_base_url.rstrip("/") + f"/webapp/provider/offer?provider_id={provider.id}")
                        ) if services.settings.public_base_url else None,
                        callback_data=(None if services.settings.public_base_url else "provider:offer_add"),
                        style="success",
                    )
                ],
                [
                    InlineKeyboardButton(text="📋 العروض الحالية", callback_data="provider:offers", style="primary"),
                    InlineKeyboardButton(text="⏳ المنتهية والمتوقفة", callback_data="p:oe", style="danger"),
                ],
                [
                    InlineKeyboardButton(text="🗂 تعديل المتجر", callback_data="p:cs", style="primary"),
                    InlineKeyboardButton(text="📦 المخزون", callback_data="provider:inventory", style="primary"),
                ],
                [
                    InlineKeyboardButton(text="📨 بريد التفعيل وOTP", callback_data="provider:emails", style="primary"),
                ],
                [
                    InlineKeyboardButton(
                        text="↩️ لوحة المنصة",
                        callback_data=f"provider:select:{provider.id}",
                    )
                ],
            ]
        ),
        back_callback="back_to_platform",
    )


async def _offer_status_counts(
    session: AsyncSession, provider_id: int
) -> dict[str, int]:
    now = datetime.now(UTC)
    rows = list(
        (
            await session.execute(
                select(Offer.status, func.count(Offer.id))
                .where(Offer.provider_id == provider_id)
                .group_by(Offer.status)
            )
        ).all()
    )
    counts = {str(status): int(count) for status, count in rows}
    timed_expired = int(
        await session.scalar(
            select(func.count())
            .select_from(Offer)
            .where(
                Offer.provider_id == provider_id,
                Offer.end_at.is_not(None),
                Offer.end_at <= now,
                Offer.status != OfferStatus.EXPIRED.value,
            )
        )
        or 0
    )
    return {
        "active": counts.get(OfferStatus.ACTIVE.value, 0),
        "draft": counts.get(OfferStatus.DRAFT.value, 0),
        "paused": counts.get(OfferStatus.PAUSED.value, 0),
        "expired": counts.get(OfferStatus.EXPIRED.value, 0) + timed_expired,
        "stock": counts.get(OfferStatus.OUT_OF_STOCK.value, 0),
    }


async def _render_offer_status_overview(
    message: Message, session: AsyncSession, staff: ProviderStaff
) -> None:
    counts = await _offer_status_counts(session, staff.provider_id)
    await edit_or_send(
        message,
        "📋 <b>عروضي</b>\nاختر حالة العروض:",
        reply_markup=_markup(
            [
                [
                    InlineKeyboardButton(
                        text=f"✅ فعالة ({counts['active']})", callback_data="p:oa", style="success"
                    ),
                    InlineKeyboardButton(
                        text=f"📝 مسودة ({counts['draft']})", callback_data="p:os:d"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=f"⏸ متوقفة ({counts['paused']})", callback_data="p:os:p"
                    ),
                    InlineKeyboardButton(
                        text=f"⌛ منتهية ({counts['expired']})", callback_data="p:oe", style="danger"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=f"📦 تحتاج مخزون ({counts['stock']})",
                        callback_data="p:os:s",
                        style="danger",
                    )
                ],
                [InlineKeyboardButton(text="↩️ متجري والعروض", callback_data="provider:catalog")],
            ]
        ),
    )


async def _catalog_structure_overview(
    message: Message,
    session: AsyncSession,
    services: Services,
    staff: ProviderStaff,
) -> None:
    provider = staff.provider
    sections = await services.catalog.create_default_provider_catalog(session, provider)
    service_rows = list(
        (
            await session.scalars(
                select(CatalogServiceItem)
                .where(CatalogServiceItem.provider_id == provider.id)
                .order_by(
                    CatalogServiceItem.section_id,
                    CatalogServiceItem.sort_order,
                    CatalogServiceItem.id,
                )
            )
        ).all()
    )
    placement_counts = dict(
        (
            await session.execute(
                select(
                    OfferCatalogPlacement.service_id,
                    func.count(OfferCatalogPlacement.id),
                )
                .where(OfferCatalogPlacement.provider_id == provider.id)
                .group_by(OfferCatalogPlacement.service_id)
            )
        ).all()
    )
    services_by_section: dict[int, list[CatalogServiceItem]] = {}
    for service_item in service_rows:
        services_by_section.setdefault(int(service_item.section_id), []).append(service_item)

    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="➕ إضافة تصنيف",
                callback_data="provider:section_add",
                style="success",
            )
        ]
    ]
    lines = [
        f"🗂 <b>تنظيم متجر {safe(provider.name_ar)}</b>\n",
        "التصنيف يجمع المنتجات والخدمات. إضافة العرض تتم من شاشة المتجر الرئيسية.",
    ]
    for section in sections:
        items = services_by_section.get(int(section.id), [])
        lines.append(f"\n\n{section.emoji} <b>{safe(section.name)}</b>")
        if items:
            for service_item in items:
                lines.append(
                    f"\n  • {service_item.emoji} {safe(service_item.name)} — "
                    f"{int(placement_counts.get(service_item.id, 0))} عرض"
                )
        else:
            lines.append("\n  • لا توجد منتجات أو خدمات")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"➕ منتج/خدمة داخل {section.name[:25]}",
                    callback_data=f"provider:service_add:{section.id}",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="⚙️ إدارة التصنيف",
                    callback_data=f"provider:section_manage:{section.id}",
                ),
            ]
        )
        for service_item in items:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"⚙️ {service_item.emoji} {service_item.name[:35]}",
                        callback_data=f"provider:service_manage:{service_item.id}",
                    )
                ]
            )
    rows.append(
        [InlineKeyboardButton(text="↩️ متجري والعروض", callback_data="provider:catalog")]
    )
    await edit_or_send(message, "".join(lines), reply_markup=_markup(rows))


@router.callback_query(F.data == "provider:catalog")
async def provider_catalog(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_offers:
        await edit_or_send(callback.message, "لا تملك صلاحية إدارة العروض.")
        return
    if not await _require_entitlement(callback, session, services, staff, "offers.manage"):
        return
    await _catalog_overview(callback.message, session, services, staff)


@router.callback_query(F.data == "p:cs")
async def provider_catalog_structure(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_offers:
        await edit_or_send(callback.message, "لا تملك صلاحية إدارة العروض.")
        return
    await _catalog_structure_overview(callback.message, session, services, staff)


@router.callback_query(F.data == "provider:offers")
async def provider_offers_overview(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_offers:
        await edit_or_send(callback.message, "لا تملك صلاحية إدارة العروض.")
        return
    await _render_offer_status_overview(callback.message, session, staff)


@router.callback_query(F.data.startswith("p:os:"))
async def provider_offers_by_status(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_offers:
        await edit_or_send(callback.message, "لا تملك صلاحية إدارة العروض.")
        return
    code = (callback.data or "").rsplit(":", 1)[-1]
    status_map = {
        "d": (OfferStatus.DRAFT.value, "📝 العروض المسودة"),
        "p": (OfferStatus.PAUSED.value, "⏸ العروض المتوقفة"),
        "s": (OfferStatus.OUT_OF_STOCK.value, "📦 عروض تحتاج مخزون"),
    }
    selected = status_map.get(code)
    if selected is None:
        await edit_or_send(callback.message, "حالة العرض غير صحيحة.")
        return
    status, title = selected
    offers = list(
        (
            await session.scalars(
                select(Offer)
                .where(Offer.provider_id == staff.provider_id, Offer.status == status)
                .order_by(Offer.updated_at.desc(), Offer.id.desc())
                .limit(100)
            )
        ).all()
    )
    rows = [
        [
            InlineKeyboardButton(
                text=f"⚙️ {offer.title[:34]}",
                callback_data=f"provider:offer_manage:{offer.id}",
            )
        ]
        for offer in offers
    ]
    rows.append([InlineKeyboardButton(text="↩️ عروضي", callback_data="provider:offers")])
    await edit_or_send(
        callback.message,
        title if offers else f"{title}\nلا توجد عناصر في هذه الحالة.",
        reply_markup=_markup(rows),
    )


@router.callback_query(F.data == "p:oa")
async def provider_active_offers(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_offers:
        return
    now = datetime.now(UTC)
    offers = list(
        (
            await session.scalars(
                select(Offer)
                .where(
                    Offer.provider_id == staff.provider_id,
                    Offer.is_active.is_(True),
                    Offer.status == OfferStatus.ACTIVE.value,
                    or_(Offer.end_at.is_(None), Offer.end_at > now),
                )
                .order_by(Offer.updated_at.desc(), Offer.id.desc())
            )
        ).all()
    )
    rows = [
        [InlineKeyboardButton(text=f"⚙️ {offer.title[:34]}", callback_data=f"provider:offer_manage:{offer.id}")]
        for offer in offers
    ]
    rows.append([InlineKeyboardButton(text="↩️ عروضي", callback_data="provider:offers")])
    await edit_or_send(
        callback.message,
        "✅ <b>العروض الفعالة</b>" if offers else "لا توجد عروض فعالة حاليًا.",
        reply_markup=_markup(rows),
    )


async def _render_expired_offers(
    message: Message, session: AsyncSession, staff: ProviderStaff
) -> None:
    now = datetime.now(UTC)
    stale_items = list(
        (
            await session.scalars(
                select(InventoryItem)
                .join(Offer, Offer.id == InventoryItem.offer_id)
                .where(
                    Offer.provider_id == staff.provider_id,
                    InventoryItem.status == InventoryStatus.AVAILABLE.value,
                    InventoryItem.expires_at.is_not(None),
                    InventoryItem.expires_at <= now,
                )
            )
        ).all()
    )
    for item in stale_items:
        item.status = InventoryStatus.EXPIRED.value
        item.remediation_note = "انتهت الصلاحية تلقائيًا"
    if stale_items:
        await session.flush()

    inventory_types = {
        DeliveryType.INVENTORY_ACCOUNT.value,
        DeliveryType.INVENTORY_CODE.value,
    }
    inventory_offer_ids = set(
        (
            await session.scalars(
                select(Offer.id).where(
                    Offer.provider_id == staff.provider_id,
                    Offer.delivery_type.in_(inventory_types),
                )
            )
        ).all()
    )
    counts = dict(
        (
            await session.execute(
                select(InventoryItem.offer_id, func.count(InventoryItem.id))
                .where(
                    InventoryItem.offer_id.in_(inventory_offer_ids or {-1}),
                    InventoryItem.status == InventoryStatus.AVAILABLE.value,
                    or_(InventoryItem.expires_at.is_(None), InventoryItem.expires_at > now),
                )
                .group_by(InventoryItem.offer_id)
            )
        ).all()
    )
    offers = list(
        (
            await session.scalars(
                select(Offer).where(
                    Offer.provider_id == staff.provider_id,
                    Offer.status != OfferStatus.PAUSED.value,
                    or_(
                        Offer.status.in_({OfferStatus.EXPIRED.value, OfferStatus.OUT_OF_STOCK.value}),
                        (Offer.end_at.is_not(None)) & (Offer.end_at <= now),
                        and_(
                            Offer.id.in_(inventory_offer_ids or {-1}),
                            ~Offer.id.in_(set(counts) or {-1}),
                        ),
                    ),
                ).order_by(Offer.updated_at.desc(), Offer.id.desc())
            )
        ).all()
    )
    rows: list[list[InlineKeyboardButton]] = []
    lines = ["♻️ <b>العروض المتوقفة والمخزون المنتهي</b>"]
    for offer in offers:
        available = int(counts.get(offer.id, 0))
        editable_items = list(
            (
                await session.scalars(
                    select(InventoryItem).where(
                        InventoryItem.offer_id == offer.id,
                        InventoryItem.status.in_(
                            {InventoryStatus.EXPIRED.value, InventoryStatus.PROBLEM.value}
                        ),
                    ).order_by(InventoryItem.id.desc()).limit(8)
                )
            ).all()
        )
        lines.append(
            f"\n• {safe(offer.title)} — مخزون صالح: {available} | يحتاج تحديث: {len(editable_items)}"
        )
        for index in range(0, len(editable_items), 2):
            pair = editable_items[index:index + 2]
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"✏️ تحديث #{item.id}",
                        callback_data=f"p:ciu:{item.id}",
                        style="success",
                    )
                    for item in pair
                ]
            )
        if offer.delivery_type in inventory_types:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="➕ إضافة حساب/كود",
                        callback_data=f"p:cred:{offer.id}",
                        style="primary",
                    ),
                    InlineKeyboardButton(
                        text="⏸ إيقاف العرض",
                        callback_data=f"p:stop:{offer.id}",
                        style="danger",
                    ),
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="⚙️ تعديل العرض",
                        callback_data=f"provider:offer_manage:{offer.id}",
                        style="primary",
                    ),
                    InlineKeyboardButton(
                        text="⏸ إيقاف العرض",
                        callback_data=f"p:stop:{offer.id}",
                        style="danger",
                    ),
                ]
            )
    rows.append([InlineKeyboardButton(text="↩️ متجري والعروض", callback_data="provider:catalog")])
    await edit_or_send(
        message,
        "".join(lines) if offers else "لا توجد عروض متوقفة أو حسابات منتهية تحتاج معالجة.",
        reply_markup=_markup(rows),
    )


@router.callback_query(F.data == "p:oe")
async def provider_expired_offers(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_offers:
        await edit_or_send(callback.message, "لا تملك صلاحية إدارة العروض.")
        return
    await _render_expired_offers(callback.message, session, staff)


@router.callback_query(F.data.startswith("p:stop:"))
async def provider_stop_expired_offer(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    try:
        offer_id = int((callback.data or "").split(":")[2])
    except (ValueError, IndexError):
        await edit_or_send(callback.message, "بيانات العرض غير صحيحة.")
        return
    offer = await session.get(Offer, offer_id)
    if not staff or not offer or offer.provider_id != staff.provider_id:
        await edit_or_send(callback.message, "العرض غير موجود أو لا يخص منصتك.")
        return
    offer.is_active = False
    offer.status = OfferStatus.PAUSED.value
    await session.flush()
    await _render_expired_offers(callback.message, session, staff)


@router.callback_query(F.data.startswith("p:ciu:"))
async def credential_update_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    try:
        item_id = int((callback.data or "").split(":")[2])
    except (ValueError, IndexError):
        await edit_or_send(callback.message, "بيانات الحساب غير صحيحة.")
        return
    item = await session.get(InventoryItem, item_id)
    offer = await session.get(Offer, item.offer_id) if item else None
    if not offer:
        await edit_or_send(callback.message, "تعذر العثور على الحساب المطلوب.")
        return
    _user, staff = await _staff_for_provider(
        session, services, callback.from_user.id, offer.provider_id
    )
    if (
        not staff
        or not staff.can_manage_inventory
        or item is None
        or item.status in {InventoryStatus.RESERVED.value, InventoryStatus.DELIVERED.value}
    ):
        await edit_or_send(callback.message, "لا يمكن تعديل هذا الحساب أو لا تملك الصلاحية.")
        return
    await state.clear()
    await state.update_data(
        provider_id=offer.provider_id,
        credential_item_id=item.id,
        offer_id=offer.id,
        item_kind=item.item_kind,
        item_label=item.label,
    )
    if item.item_kind == "account":
        await state.set_state(ProviderCredentialUpdateStates.email)
        await edit_or_send(callback.message, "📧 اكتب الإيميل الجديد للحساب:")
    else:
        await state.set_state(ProviderCredentialUpdateStates.payload)
        await edit_or_send(callback.message, "🔑 أرسل الكود أو بيانات الاعتماد الجديدة:")


@router.message(ProviderCredentialUpdateStates.email)
async def credential_update_email(
    message: Message, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    staff, _data = await _active_manager(
        message, state, session, services, permission="can_manage_inventory"
    )
    if not staff:
        return
    email = (message.text or "").strip().lower()
    if not _valid_inventory_email(email):
        await message.answer("❌ صيغة الإيميل غير صحيحة. مثال: name@gmail.com")
        return
    await state.update_data(item_email=email)
    await state.set_state(ProviderCredentialUpdateStates.password)
    await message.answer("🔐 اكتب كلمة المرور الجديدة:")


@router.message(ProviderCredentialUpdateStates.password)
async def credential_update_password(
    message: Message, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    staff, _data = await _active_manager(
        message, state, session, services, permission="can_manage_inventory"
    )
    if not staff:
        return
    password = (message.text or "").strip()
    if len(password) < 2:
        await message.answer("كلمة المرور فارغة أو قصيرة جدًا.")
        return
    await state.update_data(item_password=password)
    await state.set_state(ProviderCredentialUpdateStates.instructions)
    await message.answer("📖 اكتب ملاحظة للحساب أو أرسل -:")


@router.message(ProviderCredentialUpdateStates.instructions)
async def credential_update_instructions(
    message: Message, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    staff, data = await _active_manager(
        message, state, session, services, permission="can_manage_inventory"
    )
    if not staff:
        return
    note = (message.text or "").strip()
    payload = json.dumps(
        {
            "login_email": str(data["item_email"]),
            "login_password": str(data["item_password"]),
            "instructions": "" if note == "-" else note[:2000],
        },
        ensure_ascii=False,
    )
    await _credential_update_prepare(message, state, session, services, data, payload)


@router.message(ProviderCredentialUpdateStates.payload)
async def credential_update_payload(
    message: Message, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    staff, data = await _active_manager(
        message, state, session, services, permission="can_manage_inventory"
    )
    if not staff:
        return
    payload = (message.text or "").strip()
    if len(payload) < 2:
        await message.answer("البيانات فارغة.")
        return
    await _credential_update_prepare(message, state, session, services, data, payload)


async def _credential_update_prepare(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
    data: dict,
    payload: str,
) -> None:
    normalized = " ".join(payload.split())
    fingerprint = services.fulfillment.secrets.hash_value(
        f"{data['offer_id']}:{data['item_kind']}:{normalized}"
    )
    duplicate = await session.scalar(
        select(InventoryFingerprint.id).where(
            InventoryFingerprint.offer_id == int(data["offer_id"]),
            InventoryFingerprint.fingerprint == fingerprint,
            InventoryFingerprint.inventory_item_id != int(data["credential_item_id"]),
        )
    )
    if duplicate:
        await message.answer("هذه البيانات مستخدمة في عنصر مخزون آخر لهذا العرض.")
        return
    await state.update_data(item_payload=payload, item_fingerprint=fingerprint)
    await state.set_state(ProviderCredentialUpdateStates.expires_at)
    await message.answer("📅 اكتب تاريخ الانتهاء YYYY-MM-DD، أو - إذا لا يوجد:")


@router.message(ProviderCredentialUpdateStates.expires_at)
async def credential_update_finish(
    message: Message, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    staff, data = await _active_manager(
        message, state, session, services, permission="can_manage_inventory"
    )
    if not staff:
        return
    expires_at = None
    raw = (message.text or "").strip()
    if raw != "-":
        try:
            expires_at = datetime.strptime(raw, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=UTC
            )
        except ValueError:
            await message.answer("صيغة التاريخ غير صحيحة، مثال: 2026-09-30")
            return
        if expires_at <= datetime.now(UTC):
            await message.answer("تاريخ الانتهاء يجب أن يكون في المستقبل.")
            return
    item = await session.get(InventoryItem, int(data["credential_item_id"]))
    offer = await session.get(Offer, int(data["offer_id"]))
    if (
        item is None
        or offer is None
        or offer.provider_id != staff.provider_id
        or item.offer_id != offer.id
        or item.status in {InventoryStatus.RESERVED.value, InventoryStatus.DELIVERED.value}
    ):
        await state.clear()
        await message.answer("تعذر تحديث الحساب؛ ربما تغيرت حالته.")
        return
    policy = await services.student_subscriptions.policy(session, offer)
    if policy.validity_type == ValidityType.INVENTORY_END.value and not expires_at:
        await message.answer("هذا العرض يتطلب تاريخ انتهاء لكل حساب.")
        return

    item.encrypted_payload = services.fulfillment.secrets.encrypt(str(data["item_payload"]))
    item.expires_at = expires_at
    item.status = InventoryStatus.AVAILABLE.value
    item.reserved_order_id = None
    item.reserved_at = None
    item.compromised_at = None
    item.remediation_note = "تم تحديث بيانات الاعتماد يدويًا دون إنشاء عرض جديد"
    fingerprint_row = await session.scalar(
        select(InventoryFingerprint).where(
            InventoryFingerprint.inventory_item_id == item.id
        )
    )
    if fingerprint_row is None:
        session.add(
            InventoryFingerprint(
                offer_id=offer.id,
                inventory_item_id=item.id,
                fingerprint=str(data["item_fingerprint"]),
            )
        )
    else:
        fingerprint_row.fingerprint = str(data["item_fingerprint"])

    reactivated = False
    if (
        offer.status in {OfferStatus.OUT_OF_STOCK.value, OfferStatus.EXPIRED.value}
        and (offer.end_at is None or offer.end_at > datetime.now(UTC))
    ):
        offer.status = OfferStatus.ACTIVE.value
        offer.is_active = True
        reactivated = True
    await session.flush()
    if reactivated:
        await services.offer_lifecycle.queue_launch_announcement(
            session, offer, staff.user_id
        )
    await state.clear()
    await message.answer(
        "✅ تم تحديث بيانات الاعتماد داخل نفس عنصر المخزون مع الحفاظ على العرض وإحصائياته.",
        reply_markup=_markup(
            [[InlineKeyboardButton(text="♻️ العودة للعروض المتوقفة", callback_data="p:oe")]]
        ),
    )


async def _render_provider_branding(
    message: Message,
    staff: ProviderStaff,
) -> None:
    provider = staff.provider
    rows = [
        [
            InlineKeyboardButton(
                text="🟢 إضافة صورة" if not provider.logo_file_id else "🟢 تغيير الصورة",
                callback_data="provider:branding:upload",
                style="success",
            )
        ],
        [InlineKeyboardButton(text="↩️ لوحة المنصة", callback_data="back_to_platform")],
    ]
    text = (
        "🖼 <b>شعار المنصة</b>\n\n"
        "المواصفات: JPG/PNG/WebP، حد أقصى 8MB، حد أدنى 128×128، "
        "ويُفضل أن تكون النسبة 1:1."
    )
    if provider.logo_file_id:
        sent = await message.answer_photo(
            provider.logo_file_id,
            caption=text + "\n\nالشعار الحالي محفوظ ✅",
            reply_markup=_markup(rows),
        )
        if sent.message_id != message.message_id:
            from app.bot.ui import delete_safely

            await delete_safely(message)
        return
    await edit_or_send(message, text + "\n\nلا يوجد شعار محفوظ حاليًا.", reply_markup=_markup(rows))


@router.callback_query(F.data == "provider:branding")
async def provider_branding_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_branding:
        await edit_or_send(callback.message, "لا تملك صلاحية إدارة شعار المنصة.")
        return
    await state.clear()
    await state.update_data(provider_id=staff.provider_id, navigation_parent="platform")
    await _render_provider_branding(callback.message, staff)


@router.callback_query(F.data == "provider:branding:upload")
async def provider_branding_upload_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_branding:
        await edit_or_send(callback.message, "لا تملك صلاحية إدارة شعار المنصة.")
        return
    previous = await state.get_data()
    resume = str(previous.get("branding_resume") or "platform")
    await state.clear()
    await state.update_data(
        provider_id=staff.provider_id,
        branding_resume=resume,
        navigation_parent="platform",
    )
    await state.set_state(ProviderBrandingStates.logo)
    await edit_or_send(
        callback.message,
        "🖼 أرسل الشعار كصورة داخل تيليجرام. لن يتغير الشعار الحالي قبل المعاينة والتأكيد.\n\n"
        "JPG/PNG/WebP — بحد أقصى 8MB — ويفضل 1:1.",
        back_callback="back_to_platform",
    )


@router.message(ProviderBrandingStates.logo)
async def provider_branding_preview(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, data = await _active_manager(
        message, state, session, services, permission="can_manage_branding"
    )
    if not staff:
        return
    if not message.photo:
        await message.answer("أرسل الشعار كصورة داخل تيليجرام، وليس ملفًا أو نصًا.")
        return
    try:
        candidate = await services.branding.validate_photo(message.photo[-1])
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(
        branding_candidate={
            "file_id": candidate.file_id,
            "file_unique_id": candidate.file_unique_id,
            "file_size": candidate.file_size,
            "image_format": candidate.image_format,
            "width": candidate.width,
            "height": candidate.height,
            "warning": candidate.warning,
        },
        provider_id=staff.provider_id,
        branding_resume=str(data.get("branding_resume") or "platform"),
    )
    await state.set_state(ProviderBrandingStates.confirm)
    warning = f"\n⚠️ {candidate.warning}" if candidate.warning else ""
    await message.answer_photo(
        candidate.file_id,
        caption=(
            "🔎 <b>معاينة الشعار الجديد</b>\n"
            f"الصيغة: {candidate.image_format} — الأبعاد: {candidate.width}×{candidate.height}"
            f"{warning}\n\nلن يُحفظ قبل الضغط على تأكيد."
        ),
        reply_markup=_markup(
            [
                [
                    InlineKeyboardButton(
                        text="✅ تأكيد الشعار",
                        callback_data="provider:branding:confirm",
                        style="success",
                    ),
                    InlineKeyboardButton(
                        text="❌ إلغاء",
                        callback_data="provider:branding:cancel",
                        style="danger",
                    ),
                ]
            ]
        ),
    )


@router.callback_query(F.data == "provider:branding:confirm")
async def provider_branding_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    if await state.get_state() != ProviderBrandingStates.confirm.state:
        await callback_notice(callback, "المعاينة قديمة؛ ارفع الشعار من جديد", show_alert=True)
        return
    data = await state.get_data()
    _user, staff = await _staff_for_provider(
        session, services, callback.from_user.id, int(data.get("provider_id") or 0)
    )
    if not staff or not staff.can_manage_branding:
        await edit_or_send(callback.message, "لا تملك صلاحية إدارة شعار المنصة.")
        return
    raw = data.get("branding_candidate") or {}
    try:
        candidate = BrandingCandidate(**raw)
    except (TypeError, ValueError):
        await edit_or_send(callback.message, "بيانات المعاينة غير مكتملة؛ ارفع الشعار من جديد.")
        return
    await services.branding.save_candidate(session, staff.provider, candidate)
    resume = str(data.get("branding_resume") or "platform")
    await state.clear()
    target = "provider:offer_add" if resume == "offer_add" else "back_to_platform"
    await edit_or_send(
        callback.message,
        "تم حفظ الشعار الجديد وربطه بالتقارير ✅",
        reply_markup=_markup(
            [[InlineKeyboardButton(text="متابعة", callback_data=target, style="success")]]
        ),
    )


@router.callback_query(F.data == "provider:branding:cancel")
async def provider_branding_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    data = await state.get_data()
    provider_id = int(data.get("provider_id") or 0)
    _user, staff = await _staff_for_provider(
        session, services, callback.from_user.id, provider_id
    )
    await state.clear()
    if not staff:
        await edit_or_send(callback.message, "تم إلغاء تغيير الشعار.")
        return
    await _render_provider_branding(callback.message, staff)


@router.callback_query(F.data == "provider:section_add")
async def section_add_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_offers:
        return
    if not await _require_entitlement(callback, session, services, staff, "offers.manage"):
        return
    await state.clear()
    await state.update_data(provider_id=staff.provider_id)
    await state.set_state(ProviderCatalogSectionStates.name)
    await edit_or_send(callback.message, "اكتب اسم القسم، مثال: أدوات الذكاء الاصطناعي")


@router.message(ProviderCatalogSectionStates.name)
async def section_name(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, data = await _active_manager(
        message,
        state,
        session,
        services,
        permission="can_manage_offers",
    )
    if not staff:
        return
    value = " ".join((message.text or "").split())
    if not 2 <= len(value) <= 140:
        await message.answer("اكتب اسم قسم واضحًا من حرفين إلى 140 حرفًا.")
        return
    duplicate = await session.scalar(
        select(CatalogSection.id).where(
            CatalogSection.provider_id == int(data["provider_id"]),
            CatalogSection.name == value,
        )
    )
    if duplicate:
        await message.answer("هذا القسم موجود مسبقًا.")
        return
    section = CatalogSection(
        provider_id=staff.provider_id,
        name=value,
        emoji=smart_emoji(value),
    )
    session.add(section)
    await session.flush()
    if bool(data.get("offer_add_resume")):
        await state.update_data(section_id=section.id)
        await state.set_state(ProviderCatalogServiceStates.name)
        await message.answer(
            f"تم إنشاء التصنيف {section.emoji} <b>{safe(section.name)}</b> ✅\n"
            "الآن اكتب اسم المنتج أو الخدمة التي سيُربط بها العرض:"
        )
        return
    await state.clear()
    await message.answer(
        f"تمت إضافة التصنيف {section.emoji} <b>{safe(section.name)}</b> تلقائيًا ✅",
        reply_markup=_markup(
            [[InlineKeyboardButton(text="🛍 العودة للمتجر", callback_data="provider:catalog")]]
        ),
    )


@router.message(ProviderCatalogSectionStates.emoji)
async def section_finish_legacy(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    """Complete sessions left on the retired manual-emoji step after deployment."""
    staff, data = await _active_manager(
        message, state, session, services, permission="can_manage_offers"
    )
    if not staff:
        return
    name = str(data.get("section_name") or "قسم جديد").strip()
    duplicate = await session.scalar(
        select(CatalogSection.id).where(
            CatalogSection.provider_id == staff.provider_id,
            CatalogSection.name == name,
        )
    )
    if not duplicate:
        session.add(
            CatalogSection(
                provider_id=staff.provider_id, name=name, emoji=smart_emoji(name)
            )
        )
        await session.flush()
    await state.clear()
    await message.answer(
        "تم إكمال الخطوة تلقائيًا بالإيموجي المناسب ✅",
        reply_markup=_markup(
            [[InlineKeyboardButton(text="🛍 العودة للمتجر", callback_data="provider:catalog")]]
        ),
    )


@router.callback_query(F.data.startswith("provider:service_add:"))
async def service_add_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_offers:
        return
    section_id = int((callback.data or "").split(":")[2])
    section = await session.get(CatalogSection, section_id)
    if not section or section.provider_id != staff.provider_id:
        await edit_or_send(callback.message, "القسم لا يخص هذه المنصة.")
        return
    await state.clear()
    await state.update_data(provider_id=staff.provider_id, section_id=section.id)
    await state.set_state(ProviderCatalogServiceStates.name)
    await edit_or_send(callback.message, f"اكتب اسم الخدمة داخل {section.emoji} {safe(section.name)}")


@router.message(ProviderCatalogServiceStates.name)
async def service_name(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, data = await _active_manager(
        message,
        state,
        session,
        services,
        permission="can_manage_offers",
    )
    if not staff:
        return
    value = " ".join((message.text or "").split())
    if not 2 <= len(value) <= 160:
        await message.answer("اكتب اسم خدمة واضحًا.")
        return
    duplicate = await session.scalar(
        select(CatalogServiceItem.id).where(
            CatalogServiceItem.section_id == int(data["section_id"]),
            CatalogServiceItem.name == value,
        )
    )
    if duplicate:
        await message.answer("هذه الخدمة موجودة داخل القسم مسبقًا.")
        return
    service_item = CatalogServiceItem(
        provider_id=staff.provider_id,
        section_id=int(data["section_id"]),
        name=value,
        emoji=smart_emoji(value),
    )
    session.add(service_item)
    await session.flush()
    if bool(data.get("offer_add_resume")):
        await state.clear()
        await state.update_data(
            provider_id=staff.provider_id,
            service_id=service_item.id,
            section_id=service_item.section_id,
        )
        await state.set_state(ProviderOfferStates.title)
        await message.answer(
            f"تم إنشاء المنتج/الخدمة {service_item.emoji} <b>{safe(service_item.name)}</b> ✅\n"
            "اكتب اسم العرض، مثال: Gemini Advanced — 30 يومًا"
        )
        return
    await state.clear()
    await message.answer(
        f"تمت إضافة الخدمة {service_item.emoji} <b>{safe(service_item.name)}</b> تلقائيًا ✅",
        reply_markup=_markup(
            [[InlineKeyboardButton(text="↩️ تنظيم المتجر", callback_data="p:cs")]]
        ),
    )


@router.message(ProviderCatalogServiceStates.emoji)
async def service_finish_legacy(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    """Complete sessions left on the retired manual-emoji step after deployment."""
    staff, data = await _active_manager(
        message, state, session, services, permission="can_manage_offers"
    )
    if not staff:
        return
    name = str(data.get("service_name") or "خدمة جديدة").strip()
    section_id = int(data.get("section_id") or 0)
    duplicate = await session.scalar(
        select(CatalogServiceItem.id).where(
            CatalogServiceItem.section_id == section_id,
            CatalogServiceItem.name == name,
        )
    )
    if not duplicate:
        session.add(
            CatalogServiceItem(
                provider_id=staff.provider_id,
                section_id=section_id,
                name=name,
                emoji=smart_emoji(name),
            )
        )
        await session.flush()
    await state.clear()
    await message.answer(
        "تم إكمال الخطوة تلقائيًا بالإيموجي المناسب ✅",
        reply_markup=_markup(
            [[InlineKeyboardButton(text="↩️ تنظيم المتجر", callback_data="p:cs")]]
        ),
    )


# ---------------- Safe provider catalog CRUD ----------------
async def _managed_staff_for_entity(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> ProviderStaff | None:
    """Resolve staff from the entity encoded in the callback, not a mutable selected tab."""
    if not callback.from_user or not callback.message:
        return None
    data = callback.data or ""
    provider_id = 0
    try:
        entity_id = int(data.rsplit(":", 1)[-1])
    except (TypeError, ValueError):
        entity_id = 0
    if entity_id:
        if data.startswith("provider:section_"):
            provider_id = int(
                await session.scalar(
                    select(CatalogSection.provider_id).where(CatalogSection.id == entity_id)
                )
                or 0
            )
        elif data.startswith("provider:service_"):
            provider_id = int(
                await session.scalar(
                    select(CatalogServiceItem.provider_id).where(CatalogServiceItem.id == entity_id)
                )
                or 0
            )
        elif data.startswith("provider:offer_"):
            provider_id = int(
                await session.scalar(select(Offer.provider_id).where(Offer.id == entity_id))
                or 0
            )
    if provider_id:
        _user, staff = await _staff_for_provider(
            session, services, callback.from_user.id, provider_id
        )
    else:
        _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_offers:
        await edit_or_send(callback.message, "لا تملك صلاحية إدارة هذا العنصر أو لم يعد موجودًا.")
        return None
    if not await _require_entitlement(callback, session, services, staff, "offers.manage"):
        return None
    return staff


async def _render_section_manage(
    message: Message, session: AsyncSession, section: CatalogSection
) -> None:
    service_count = int(
        await session.scalar(
            select(func.count()).select_from(CatalogServiceItem).where(
                CatalogServiceItem.section_id == section.id
            )
        )
        or 0
    )
    await edit_or_send(
        message,
        f"⚙️ <b>إدارة القسم</b>\n\n"
        f"الاسم: {section.emoji} <b>{safe(section.name)}</b>\n"
        f"الخدمات: {service_count}\n"
        f"الحالة: {'ظاهر ✅' if section.is_active else 'مخفي ⏸'}",
        reply_markup=_markup([
            [
                InlineKeyboardButton(text="✏️ تعديل الاسم", callback_data=f"provider:section_rename:{section.id}", style="primary"),
                InlineKeyboardButton(
                    text="⏸ إخفاء" if section.is_active else "▶️ إظهار",
                    callback_data=f"provider:section_toggle:{section.id}",
                    style="danger" if section.is_active else "success",
                ),
            ],
            [InlineKeyboardButton(text="🗑 حذف القسم الفارغ", callback_data=f"provider:section_delete:{section.id}", style="danger")],
            [InlineKeyboardButton(text="↩️ المتجر", callback_data="provider:catalog")],
        ]),
    )


@router.callback_query(F.data.startswith("provider:section_manage:"))
async def section_manage(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    staff = await _managed_staff_for_entity(callback, session, services)
    if not staff or not callback.message:
        return
    section = await session.get(CatalogSection, int((callback.data or "").split(":")[2]))
    if not section or section.provider_id != staff.provider_id:
        await edit_or_send(callback.message, "القسم غير موجود أو لا يخص منصتك.")
        return
    await _render_section_manage(callback.message, session, section)


@router.callback_query(F.data.startswith("provider:section_toggle:"))
async def section_toggle(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    staff = await _managed_staff_for_entity(callback, session, services)
    if not staff or not callback.message:
        return
    section = await session.get(CatalogSection, int((callback.data or "").split(":")[2]))
    if not section or section.provider_id != staff.provider_id:
        await edit_or_send(callback.message, "غير مصرح.")
        return
    section.is_active = not section.is_active
    await session.flush()
    await _render_section_manage(callback.message, session, section)


@router.callback_query(F.data.startswith("provider:section_rename:"))
async def section_rename_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    staff = await _managed_staff_for_entity(callback, session, services)
    if not staff or not callback.message:
        return
    section = await session.get(CatalogSection, int((callback.data or "").split(":")[2]))
    if not section or section.provider_id != staff.provider_id:
        return
    await state.clear()
    await state.update_data(provider_id=staff.provider_id, edit_section_id=section.id)
    await state.set_state(ProviderCatalogEditStates.section_name)
    await edit_or_send(callback.message, 
        f"الاسم الحالي: <b>{safe(section.name)}</b>\nاكتب الاسم الجديد أو اضغط ⬅️ رجوع."
    )


@router.message(ProviderCatalogEditStates.section_name)
async def section_rename_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, data = await _active_manager(
        message, state, session, services, permission="can_manage_offers"
    )
    if not staff:
        return
    section = await session.get(CatalogSection, int(data.get("edit_section_id") or 0))
    name = " ".join((message.text or "").split())
    if not section or section.provider_id != staff.provider_id or not 2 <= len(name) <= 140:
        await message.answer("الاسم غير صالح.")
        return
    duplicate = await session.scalar(
        select(CatalogSection.id).where(
            CatalogSection.provider_id == staff.provider_id,
            CatalogSection.name == name,
            CatalogSection.id != section.id,
        )
    )
    if duplicate:
        await message.answer("يوجد قسم آخر بهذا الاسم.")
        return
    section.name = name
    await state.clear()
    await message.answer(
        "تم تعديل اسم القسم ✅",
        reply_markup=_markup(
            [[InlineKeyboardButton(text="🛍 العودة للمتجر", callback_data="provider:catalog")]]
        ),
    )


@router.callback_query(F.data.startswith("provider:section_delete:"))
async def section_delete(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    staff = await _managed_staff_for_entity(callback, session, services)
    if not staff:
        return
    section = await session.get(CatalogSection, int((callback.data or "").split(":")[2]))
    if not section or section.provider_id != staff.provider_id:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    count = int(
        await session.scalar(
            select(func.count()).select_from(CatalogServiceItem).where(
                CatalogServiceItem.section_id == section.id
            )
        )
        or 0
    )
    if count:
        await callback_notice(callback, "لا يمكن حذف قسم يحتوي خدمات. أخفه أو انقل/احذف الخدمات أولًا.", show_alert=True)
        return
    await session.delete(section)
    await callback_notice(callback, "تم حذف القسم الفارغ ✅", show_alert=True)


async def _render_service_manage(
    message: Message, session: AsyncSession, service_item: CatalogServiceItem
) -> None:
    offers = list(
        (await session.scalars(
            select(Offer)
            .join(OfferCatalogPlacement, OfferCatalogPlacement.offer_id == Offer.id)
            .where(OfferCatalogPlacement.service_id == service_item.id)
            .order_by(Offer.created_at.desc())
        )).all()
    )
    rows: list[list[InlineKeyboardButton]] = [[
        InlineKeyboardButton(text="✏️ تعديل الاسم", callback_data=f"provider:service_rename:{service_item.id}", style="primary"),
        InlineKeyboardButton(
            text="⏸ إخفاء" if service_item.is_active else "▶️ إظهار",
            callback_data=f"provider:service_toggle:{service_item.id}",
            style="danger" if service_item.is_active else "success",
        ),
    ]]
    for offer in offers:
        rows.append([InlineKeyboardButton(text=f"⚙️ عرض: {offer.title[:38]}", callback_data=f"provider:offer_manage:{offer.id}")])
    rows.extend([
        [InlineKeyboardButton(text="🗑 حذف الخدمة الفارغة", callback_data=f"provider:service_delete:{service_item.id}", style="danger")],
        [InlineKeyboardButton(text="↩️ المتجر", callback_data="provider:catalog")],
    ])
    await edit_or_send(
        message,
        f"⚙️ <b>إدارة الخدمة</b>\n\n"
        f"الخدمة: {service_item.emoji} <b>{safe(service_item.name)}</b>\n"
        f"العروض: {len(offers)}\n"
        f"الحالة: {'ظاهرة ✅' if service_item.is_active else 'مخفية ⏸'}",
        reply_markup=_markup(rows),
    )


@router.callback_query(F.data.startswith("provider:service_manage:"))
async def service_manage(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    staff = await _managed_staff_for_entity(callback, session, services)
    if not staff or not callback.message:
        return
    service_item = await session.get(CatalogServiceItem, int((callback.data or "").split(":")[2]))
    if not service_item or service_item.provider_id != staff.provider_id:
        await edit_or_send(callback.message, "الخدمة غير موجودة أو لا تخص منصتك.")
        return
    await _render_service_manage(callback.message, session, service_item)


@router.callback_query(F.data.startswith("provider:service_toggle:"))
async def service_toggle(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    staff = await _managed_staff_for_entity(callback, session, services)
    if not staff or not callback.message:
        return
    item = await session.get(CatalogServiceItem, int((callback.data or "").split(":")[2]))
    if not item or item.provider_id != staff.provider_id:
        await edit_or_send(callback.message, "غير مصرح.")
        return
    item.is_active = not item.is_active
    await session.flush()
    await _render_service_manage(callback.message, session, item)


@router.callback_query(F.data.startswith("provider:service_rename:"))
async def service_rename_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    staff = await _managed_staff_for_entity(callback, session, services)
    if not staff or not callback.message:
        return
    item = await session.get(CatalogServiceItem, int((callback.data or "").split(":")[2]))
    if not item or item.provider_id != staff.provider_id:
        return
    await state.clear()
    await state.update_data(provider_id=staff.provider_id, edit_service_id=item.id)
    await state.set_state(ProviderCatalogEditStates.service_name)
    await edit_or_send(callback.message, 
        f"الاسم الحالي: <b>{safe(item.name)}</b>\nاكتب اسم الخدمة الجديد أو اضغط ⬅️ رجوع."
    )


@router.message(ProviderCatalogEditStates.service_name)
async def service_rename_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, data = await _active_manager(
        message, state, session, services, permission="can_manage_offers"
    )
    if not staff:
        return
    item = await session.get(CatalogServiceItem, int(data.get("edit_service_id") or 0))
    name = " ".join((message.text or "").split())
    if not item or item.provider_id != staff.provider_id or not 2 <= len(name) <= 160:
        await message.answer("الاسم غير صالح.")
        return
    duplicate = await session.scalar(
        select(CatalogServiceItem.id).where(
            CatalogServiceItem.section_id == item.section_id,
            CatalogServiceItem.name == name,
            CatalogServiceItem.id != item.id,
        )
    )
    if duplicate:
        await message.answer("توجد خدمة أخرى بهذا الاسم داخل القسم.")
        return
    item.name = name
    await state.clear()
    await message.answer(
        "تم تعديل اسم الخدمة ✅",
        reply_markup=_markup(
            [[InlineKeyboardButton(text="🛍 العودة للمتجر", callback_data="provider:catalog")]]
        ),
    )


@router.callback_query(F.data.startswith("provider:service_delete:"))
async def service_delete(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    staff = await _managed_staff_for_entity(callback, session, services)
    if not staff:
        return
    item = await session.get(CatalogServiceItem, int((callback.data or "").split(":")[2]))
    if not item or item.provider_id != staff.provider_id:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    count = int(
        await session.scalar(
            select(func.count()).select_from(OfferCatalogPlacement).where(
                OfferCatalogPlacement.service_id == item.id
            )
        )
        or 0
    )
    if count:
        await callback_notice(callback, "لا يمكن حذف خدمة مرتبطة بعروض. أخفها أو أوقف عروضها أولًا.", show_alert=True)
        return
    await session.delete(item)
    await callback_notice(callback, "تم حذف الخدمة الفارغة ✅", show_alert=True)


async def _render_offer_manage(
    message: Message, session: AsyncSession, services: Services, offer: Offer
) -> None:
    order_count = int(
        await session.scalar(select(func.count()).select_from(Order).where(Order.offer_id == offer.id))
        or 0
    )
    guide = await services.activation_guides.get_for_offer(session, offer.id)
    await edit_or_send(
        message,
        f"⚙️ <b>إدارة العرض</b>\n\n"
        f"الاسم: <b>{safe(offer.title)}</b>\n"
        f"السعر: <b>{offer.price_iqd:,} د.ع</b>\n"
        f"الطلبات التاريخية: {order_count}\n"
        f"التعليمات: {'موجودة ✅' if guide else 'غير موجودة ❌'}\n"
        f"الحالة: {'فعال ✅' if offer.is_active and offer.status == OfferStatus.ACTIVE.value else 'متوقف ⏸'}",
        reply_markup=_markup([
            [
                InlineKeyboardButton(text="💰 تعديل السعر", callback_data=f"provider:offer_price_edit:{offer.id}", style="primary"),
                InlineKeyboardButton(
                    text="⏸ إيقاف" if offer.is_active else "▶️ تشغيل",
                    callback_data=f"provider:offer_toggle:{offer.id}",
                    style="danger" if offer.is_active else "success",
                ),
            ],
            [
                InlineKeyboardButton(text="📖 تعليمات التفعيل", callback_data=f"guide:view:offer:{offer.id}"),
                InlineKeyboardButton(text="🔑 إدارة المخزون", callback_data=f"provider:inventory_offer:{offer.id}", style="primary"),
            ],
            [
                InlineKeyboardButton(text="🤝 باقة أصدقائي فقط", callback_data=f"provider:friends:{offer.id}", style="primary"),
                InlineKeyboardButton(text="🛡️ الضمان", callback_data=f"provider:warranty:{offer.id}", style="success"),
            ],
            [
                InlineKeyboardButton(
                    text="🗑 حذف نهائي" if not order_count else "🗄 أرشفة العرض",
                    callback_data=f"provider:offer_archive:{offer.id}",
                    style="danger",
                ),
                InlineKeyboardButton(text="↩️ المتجر", callback_data="provider:catalog"),
            ],
        ]),
    )


@router.callback_query(F.data.startswith("provider:offer_manage:"))
async def offer_manage(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    staff = await _managed_staff_for_entity(callback, session, services)
    if not staff or not callback.message:
        return
    offer = await session.get(Offer, int((callback.data or "").split(":")[2]))
    if not offer or offer.provider_id != staff.provider_id:
        await edit_or_send(callback.message, "العرض غير موجود أو لا يخص منصتك.")
        return
    await _render_offer_manage(callback.message, session, services, offer)


@router.callback_query(F.data.startswith("provider:offer_toggle:"))
async def offer_toggle(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    staff = await _managed_staff_for_entity(callback, session, services)
    if not staff or not callback.message:
        return
    offer = await session.get(Offer, int((callback.data or "").split(":")[2]))
    if not offer or offer.provider_id != staff.provider_id:
        await edit_or_send(callback.message, "غير مصرح.")
        return
    if not offer.is_active:
        guide = await services.activation_guides.get_for_offer(session, offer.id)
        if not guide:
            await edit_or_send(callback.message, "لا يمكن تشغيل العرض قبل إضافة تعليمات التفعيل.")
            return
        offer.is_active = True
        offer.status = OfferStatus.ACTIVE.value
    else:
        offer.is_active = False
        offer.status = OfferStatus.PAUSED.value
    await session.flush()
    await _render_offer_manage(callback.message, session, services, offer)


@router.callback_query(F.data.startswith("provider:offer_price_edit:"))
async def offer_price_edit_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    staff = await _managed_staff_for_entity(callback, session, services)
    if not staff or not callback.message:
        return
    offer = await session.get(Offer, int((callback.data or "").split(":")[2]))
    if not offer or offer.provider_id != staff.provider_id:
        return
    await state.clear()
    await state.update_data(
        provider_id=staff.provider_id,
        edit_offer_id=offer.id,
        edit_offer_old_price=offer.price_iqd,
    )
    await state.set_state(ProviderCatalogEditStates.offer_price)
    await edit_or_send(callback.message, 
        f"السعر الحالي: <b>{offer.price_iqd:,} د.ع</b>\n"
        "اكتب السعر الجديد كاملًا. مثال: 10000 وليس 10."
    )


@router.message(ProviderCatalogEditStates.offer_price)
async def offer_price_edit_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, _data = await _active_manager(
        message, state, session, services, permission="can_manage_offers"
    )
    if not staff:
        return
    try:
        result = await services.pricing.validate_offer_price(session, message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(edit_offer_price=result.value)
    await state.set_state(ProviderCatalogEditStates.offer_price_confirm)
    warning = (
        "\n⚠️ السعر منخفض جدًا؛ راجعه جيدًا." if result.suspiciously_low else ""
    )
    await message.answer(
        f"السعر الجديد: <b>{result.formatted}</b>\n"
        f"كتابةً: <b>{result.words}</b>{warning}",
        reply_markup=_markup(
            [
                [InlineKeyboardButton(text="✅ حفظ السعر", callback_data="provider:offer_price_edit_confirm", style="success")],
                [InlineKeyboardButton(text="✏️ إعادة الكتابة", callback_data="provider:offer_price_edit_retry")],
                [InlineKeyboardButton(text="❌ إلغاء", callback_data="nav:cancel", style="danger")],
            ]
        ),
    )


@router.callback_query(F.data == "provider:offer_price_edit_retry")
async def offer_price_edit_retry(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ProviderCatalogEditStates.offer_price)
    if callback.message:
        await edit_or_send(callback.message, "اكتب السعر من جديد كاملًا:")


@router.callback_query(F.data == "provider:offer_price_edit_confirm")
async def offer_price_edit_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    data = await state.get_data()
    _user, staff = await _staff(session, services, callback.from_user.id)
    offer = await session.get(Offer, int(data.get("edit_offer_id") or 0))
    if not staff or not offer or offer.provider_id != staff.provider_id:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    old_price = int(data.get("edit_offer_old_price", offer.price_iqd))
    offer.price_iqd = int(data.get("edit_offer_price") or 0)
    actor = await services.users.get_or_create(
        session,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name,
    )
    await services.pricing.log_price_change(
        session,
        key=f"provider.{offer.provider_id}.offer.{offer.id}.price_iqd",
        old_value=old_price,
        new_value=offer.price_iqd,
        actor=actor,
        reason="تعديل سعر العرض من لوحة المنصة",
    )
    await state.clear()
    await callback_notice(callback, "تم تعديل السعر ✅", show_alert=True)
    await edit_or_send(callback.message, 
        f"السعر الجديد للعرض: <b>{offer.price_iqd:,} د.ع</b>",
        reply_markup=_markup(
            [[InlineKeyboardButton(text="🛍 العودة للمتجر", callback_data="provider:catalog")]]
        ),
    )


@router.callback_query(F.data.startswith("provider:offer_archive:"))
async def offer_archive_or_delete(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    staff = await _managed_staff_for_entity(callback, session, services)
    if not staff:
        return
    offer = await session.get(Offer, int((callback.data or "").split(":")[2]))
    if not offer or offer.provider_id != staff.provider_id:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    order_count = int(
        await session.scalar(
            select(func.count()).select_from(Order).where(Order.offer_id == offer.id)
        )
        or 0
    )
    inventory_count = int(
        await session.scalar(
            select(func.count()).select_from(InventoryItem).where(InventoryItem.offer_id == offer.id)
        )
        or 0
    )
    email_count = int(
        await session.scalar(
            select(func.count()).select_from(EmailAccount).where(EmailAccount.offer_id == offer.id)
        )
        or 0
    )
    if order_count or inventory_count or email_count:
        offer.is_active = False
        offer.status = OfferStatus.PAUSED.value
        await callback_notice(callback, 
            "تمت أرشفة العرض بدل حذفه لحماية الطلبات أو المخزون أو حسابات البريد ✅",
            show_alert=True,
        )
        return
    await session.delete(offer)
    await callback_notice(callback, "تم حذف العرض الفارغ نهائيًا ✅", show_alert=True)


@router.callback_query(F.data == "provider:offer_new_section")
async def offer_new_section_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_offers:
        await edit_or_send(callback.message, "لا تملك صلاحية إدارة العروض.")
        return
    await state.clear()
    await state.update_data(provider_id=staff.provider_id, offer_add_resume=True)
    await state.set_state(ProviderCatalogSectionStates.name)
    await edit_or_send(
        callback.message,
        "اكتب اسم التصنيف الجديد، مثال: أدوات الذكاء الاصطناعي",
    )


@router.callback_query(F.data == "provider:offer_new_service")
async def offer_new_service_choose_section(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_offers:
        await edit_or_send(callback.message, "لا تملك صلاحية إدارة العروض.")
        return
    sections = list(
        (
            await session.scalars(
                select(CatalogSection)
                .where(
                    CatalogSection.provider_id == staff.provider_id,
                    CatalogSection.is_active.is_(True),
                )
                .order_by(CatalogSection.sort_order, CatalogSection.id)
            )
        ).all()
    )
    rows = [
        [
            InlineKeyboardButton(
                text=f"{section.emoji} {section.name[:36]}",
                callback_data=f"provider:offer_service_new:{section.id}",
                style="primary",
            )
        ]
        for section in sections
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="➕ إنشاء تصنيف جديد",
                callback_data="provider:offer_new_section",
                style="success",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="↩️ اختيار المنتج", callback_data="provider:offer_add")])
    await edit_or_send(
        callback.message,
        "اختر التصنيف الذي سيحتوي المنتج/الخدمة الجديدة:",
        reply_markup=_markup(rows),
    )


@router.callback_query(F.data.startswith("provider:offer_service_new:"))
async def offer_new_service_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    try:
        section_id = int((callback.data or "").rsplit(":", 1)[-1])
    except (TypeError, ValueError):
        await edit_or_send(callback.message, "التصنيف المحدد غير صالح.")
        return
    section = await session.get(CatalogSection, section_id)
    if not staff or not section or section.provider_id != staff.provider_id:
        await edit_or_send(callback.message, "التصنيف غير موجود أو لا يخص منصتك.")
        return
    await state.clear()
    await state.update_data(
        provider_id=staff.provider_id,
        section_id=section.id,
        offer_add_resume=True,
    )
    await state.set_state(ProviderCatalogServiceStates.name)
    await edit_or_send(
        callback.message,
        f"اكتب اسم المنتج أو الخدمة داخل {section.emoji} {safe(section.name)}",
    )


@router.callback_query(F.data == "provider:offer_add")
async def offer_add_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_offers:
        await edit_or_send(callback.message, "لا تملك صلاحية إدارة العروض.")
        return
    entitlement = await services.subscriptions.effective_entitlement(
        session, staff.provider_id, "offers.max"
    )
    if not entitlement.enabled:
        await edit_or_send(callback.message, "إدارة العروض غير متاحة في باقة المنصة.")
        return
    current_count = int(
        await session.scalar(
            select(func.count()).select_from(Offer).where(Offer.provider_id == staff.provider_id)
        )
        or 0
    )
    if (
        entitlement.limit is not None
        and entitlement.limit >= 0
        and current_count >= entitlement.limit
    ):
        await edit_or_send(callback.message, "وصلت المنصة إلى الحد الأقصى للعروض في باقتها.")
        return
    service_items = list(
        (
            await session.scalars(
                select(CatalogServiceItem)
                .where(
                    CatalogServiceItem.provider_id == staff.provider_id,
                    CatalogServiceItem.is_active.is_(True),
                )
                .order_by(CatalogServiceItem.section_id, CatalogServiceItem.sort_order)
            )
        ).all()
    )
    await state.clear()
    await state.update_data(provider_id=staff.provider_id)
    rows = [
        [
            InlineKeyboardButton(
                text=f"{item.emoji} {item.name}",
                callback_data=f"provider:offer_service:{item.id}",
                style="primary",
            )
        ]
        for item in service_items
    ]
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="➕ إنشاء منتج/خدمة جديدة",
                    callback_data="provider:offer_new_service",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ إنشاء تصنيف جديد",
                    callback_data="provider:offer_new_section",
                )
            ],
            [InlineKeyboardButton(text="↩️ المتجر", callback_data="provider:catalog")],
        ]
    )
    await edit_or_send(
        callback.message,
        "اختر منتجًا/خدمة موجودة، أو أنشئها من داخل نفس تدفق العرض:",
        reply_markup=_markup(rows),
    )


@router.callback_query(F.data.startswith("provider:offer_service:"))
async def offer_service_pick(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    service_id = int((callback.data or "").split(":")[2])
    service_item = await session.get(CatalogServiceItem, service_id)
    if not staff or not service_item or service_item.provider_id != staff.provider_id:
        await edit_or_send(callback.message, "الخدمة غير متاحة لهذه المنصة.")
        return
    await state.clear()
    await state.update_data(
        provider_id=staff.provider_id,
        service_id=service_item.id,
        section_id=service_item.section_id,
    )
    await state.set_state(ProviderOfferStates.title)
    await edit_or_send(callback.message, "اكتب اسم العرض، مثال: Gemini Advanced — 30 يومًا")


@router.message(ProviderOfferStates.title)
async def offer_title(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, _data = await _active_manager(
        message,
        state,
        session,
        services,
        permission="can_manage_offers",
    )
    if not staff:
        return
    title = " ".join((message.text or "").split())
    if not 3 <= len(title) <= 220:
        await message.answer("اكتب اسم عرض واضحًا.")
        return
    await state.update_data(offer_title=title)
    await state.set_state(ProviderOfferStates.description)
    await message.answer("اكتب وصف العرض وطريقة الاستفادة، أو اكتب -")


@router.message(ProviderOfferStates.description)
async def offer_description(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, _data = await _active_manager(
        message,
        state,
        session,
        services,
        permission="can_manage_offers",
    )
    if not staff:
        return
    value = (message.text or "").strip()
    await state.update_data(offer_description="" if value == "-" else value[:3000])
    await state.set_state(ProviderOfferStates.price)
    await message.answer("اكتب سعر الاشتراك بالدينار العراقي:")


async def _ask_provider_delivery(
    message: Message,
    state: FSMContext,
    *,
    in_place: bool = False,
) -> None:
    async def render(
        text: str,
        *,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        if in_place:
            await edit_or_send(message, text, reply_markup=reply_markup)
        else:
            await message.answer(text, reply_markup=reply_markup)

    await state.set_state(ProviderOfferStates.delivery_type)
    await render(
        "🔐 اختر طريقة تسليم وتفعيل العرض:",
        reply_markup=_markup(
            [
                [InlineKeyboardButton(text="📦 تسليم حساب جاهز", callback_data="p:od:a:ep", style="primary")],
                [InlineKeyboardButton(text="📨 دعوة أو رمز بالبريد", callback_data="p:od:e:ec", style="primary")],
                [InlineKeyboardButton(text="📦 حساب جاهز + رمز", callback_data="p:od:a:epc", style="success")],
                [InlineKeyboardButton(text="🔑 كود تفعيل فقط", callback_data="p:od:c:ac", style="primary")],
                [InlineKeyboardButton(text="🧾 بيانات مخصصة", callback_data="p:od:a:cd")],
                [InlineKeyboardButton(text="🧑‍💼 تفعيل يدوي", callback_data="p:od:m:m")],
                [InlineKeyboardButton(text="⬅️ رجوع", callback_data="provider:offer_price_retry")],
            ]
        ),
    )


async def _confirm_provider_price(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
    amount: int,
) -> None:
    """Store the normal price, then decide whether this is a timed promotion."""
    fee = int(services.settings.default_service_fee_iqd or 0)
    await state.update_data(
        offer_regular_price=int(amount),
        offer_price=int(amount),
        offer_original_price=None,
        offer_start_at=None,
        offer_end_at=None,
        offer_fee=fee,
    )
    await state.set_state(ProviderOfferStates.promotion_type)
    await edit_or_send(
        message,
        "هل هذا اشتراك بسعره الطبيعي أم عرض طلابي مؤقت؟",
        reply_markup=_markup(
            [
                [
                    InlineKeyboardButton(text="🛍 اشتراك عادي", callback_data="p:pt:n", style="primary"),
                    InlineKeyboardButton(text="🔥 عرض مؤقت", callback_data="p:pt:t", style="success"),
                ],
                [InlineKeyboardButton(text="⬅️ تعديل السعر", callback_data="provider:offer_price_retry")],
            ]
        ),
    )


@router.callback_query(F.data.in_({"p:pt:n", "p:pt:t"}))
async def offer_promotion_type(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    staff, data = await _active_callback_manager(
        callback,
        state,
        session,
        services,
        permission="can_manage_offers",
        expected_state=ProviderOfferStates.promotion_type.state,
    )
    if not staff or not callback.message:
        return
    if callback.data == "p:pt:n":
        regular = int(data["offer_regular_price"])
        await state.update_data(
            offer_price=regular,
            offer_original_price=None,
            offer_start_at=None,
            offer_end_at=None,
        )
        await _ask_provider_delivery(callback.message, state, in_place=True)
        return
    await state.set_state(ProviderOfferStates.promotion_price)
    await edit_or_send(
        callback.message,
        f"اكتب سعر العرض بعد الخصم. يجب أن يكون أقل من السعر الطبيعي "
        f"<b>{int(data['offer_regular_price']):,} د.ع</b>.",
    )


@router.message(ProviderOfferStates.promotion_price)
async def offer_promotion_price(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, data = await _active_manager(
        message, state, session, services, permission="can_manage_offers"
    )
    if not staff:
        return
    try:
        result = await services.pricing.validate_offer_price(session, message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    regular = int(data["offer_regular_price"])
    if result.value >= regular:
        await message.answer("سعر العرض يجب أن يكون أقل من السعر الطبيعي.")
        return
    await state.update_data(
        offer_price=int(result.value),
        offer_original_price=regular,
        offer_start_at=datetime.now(UTC),
    )
    await state.set_state(ProviderOfferStates.promotion_end)
    await message.answer(
        "⏰ اكتب وقت انتهاء العرض بتوقيت بغداد:\n"
        "<code>YYYY-MM-DD HH:MM</code> أو تاريخ فقط <code>YYYY-MM-DD</code>."
    )


@router.message(ProviderOfferStates.promotion_end)
async def offer_promotion_end(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, _data = await _active_manager(
        message, state, session, services, permission="can_manage_offers"
    )
    if not staff:
        return
    raw = (message.text or "").strip()
    parsed = None
    for pattern, end_of_day in (("%Y-%m-%d %H:%M", False), ("%Y-%m-%d", True)):
        try:
            parsed = datetime.strptime(raw, pattern)
            if end_of_day:
                parsed = parsed.replace(hour=23, minute=59, second=59)
            break
        except ValueError:
            continue
    if parsed is None:
        await message.answer("صيغة الوقت غير صحيحة. مثال: 2026-08-05 21:30")
        return
    end_at = parsed.replace(tzinfo=ZoneInfo(services.settings.timezone)).astimezone(UTC)
    if end_at <= datetime.now(UTC):
        await message.answer("وقت انتهاء العرض يجب أن يكون في المستقبل.")
        return
    await state.update_data(offer_end_at=end_at)
    await _ask_provider_delivery(message, state)


@router.message(ProviderOfferStates.price)
async def offer_price(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, _data = await _active_manager(
        message,
        state,
        session,
        services,
        permission="can_manage_offers",
    )
    if not staff:
        return
    try:
        result = await services.pricing.validate_offer_price(session, message.text or "")
    except ValueError as exc:
        await message.answer(f"{exc}\n\nمثال صحيح: <code>10000</code> = عشرة آلاف دينار.")
        return
    await state.update_data(pending_offer_price=result.value)
    warning = ""
    rows = [
        [InlineKeyboardButton(text="✅ نعم، اعتماد السعر", callback_data=f"provider:offer_price_accept:{result.value}", style="success")],
        [InlineKeyboardButton(text="✏️ تعديل السعر", callback_data="provider:offer_price_retry", style="primary")],
        [InlineKeyboardButton(text="⬅️ رجوع للوصف", callback_data="provider:offer_price_back")],
    ]
    if result.suspiciously_low:
        warning = (
            "\n\n⚠️ <b>تنبيه مهم:</b> هذا السعر منخفض جدًا. "
            "إذا كنت تقصد عشرة آلاف فاكتب 10000 وليس 10."
        )
        if result.suggested_value:
            rows.insert(
                1,
                [InlineKeyboardButton(text=f"✅ كنت أقصد {result.suggested_value:,} د.ع", callback_data=f"provider:offer_price_accept:{result.suggested_value}", style="success")],
            )
    await message.answer(
        "💰 <b>مراجعة السعر</b>\n\n"
        f"الرقم: <b>{result.formatted}</b>\n"
        f"كتابةً: <b>{result.words}</b>"
        f"{warning}\n\nلن يُحفظ السعر قبل التأكيد.",
        reply_markup=_markup(rows),
    )


@router.callback_query(F.data.startswith("provider:offer_price_accept:"))
async def offer_price_accept(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    # Answer immediately so Telegram never leaves the button spinning.
    await callback.answer()
    if not callback.message:
        return

    staff, _data = await _active_callback_manager(
        callback,
        state,
        session,
        services,
        permission="can_manage_offers",
        expected_state=ProviderOfferStates.price.state,
    )
    if not staff:
        return

    try:
        amount = int((callback.data or "").rsplit(":", 1)[-1])
        if amount <= 0:
            raise ValueError("offer price must be positive")

        # Remove the old confirmation buttons to prevent accidental double clicks.
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            # A Telegram edit failure must never block the offer wizard.
            logger.debug("Could not clear offer price keyboard", exc_info=True)

        await _confirm_provider_price(callback.message, state, session, services, amount)
    except (TypeError, ValueError):
        logger.warning(
            "Rejected malformed provider offer price callback: %r",
            callback.data,
            exc_info=True,
        )
        await state.set_state(ProviderOfferStates.price)
        await edit_or_send(callback.message, 
            "❌ تعذر قراءة السعر من الزر، ولم تُفقد معلومات العرض.\n"
            "اكتب السعر مرة ثانية، مثال: <code>10000</code>."
        )
    except Exception:
        logger.exception("Provider offer price confirmation failed")
        await state.set_state(ProviderOfferStates.price)
        await edit_or_send(callback.message, 
            "❌ تعذر اعتماد السعر مؤقتًا، ولم تُفقد معلومات العرض.\n"
            "اضغط إعادة المحاولة أو اكتب السعر من جديد: <code>10000</code>."
        )


@router.callback_query(F.data == "provider:offer_price_retry")
async def offer_price_retry(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ProviderOfferStates.price)
    if callback.message:
        await edit_or_send(callback.message, 
            "اكتب السعر كاملًا بالأرقام. مثال: <code>10000</code> يعني عشرة آلاف دينار."
        )


@router.callback_query(F.data == "provider:offer_price_back")
async def offer_price_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ProviderOfferStates.description)
    if callback.message:
        await edit_or_send(callback.message, "اكتب وصف العرض من جديد، أو اكتب -:")


@router.callback_query(F.data.startswith("provider:offer_delivery:") | F.data.startswith("p:od:"))
async def offer_delivery_pick(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    staff, _data = await _active_callback_manager(
        callback,
        state,
        session,
        services,
        permission="can_manage_offers",
        expected_state=ProviderOfferStates.delivery_type.state,
    )
    if not staff or not callback.message:
        return
    parts = (callback.data or "").split(":")
    if parts[:2] == ["p", "od"]:
        delivery_type = {
            "a": DeliveryType.INVENTORY_ACCOUNT.value,
            "c": DeliveryType.INVENTORY_CODE.value,
            "e": DeliveryType.EMAIL_CODE.value,
            "m": DeliveryType.MANUAL.value,
        }.get(parts[2] if len(parts) > 2 else "", "")
        activation_mode = {
            "ep": ActivationMode.EMAIL_PASSWORD.value,
            "epc": ActivationMode.EMAIL_PASSWORD_CODE.value,
            "ec": ActivationMode.EMAIL_CODE.value,
            "ac": ActivationMode.ACTIVATION_CODE.value,
            "cd": ActivationMode.CUSTOM_DATA.value,
            "m": ActivationMode.MANUAL.value,
        }.get(parts[3] if len(parts) > 3 else "", ActivationMode.MANUAL.value)
    else:
        delivery_type = parts[2] if len(parts) > 2 else ""
        activation_mode = parts[3] if len(parts) > 3 else ActivationMode.MANUAL.value
    allowed = {
        DeliveryType.INVENTORY_ACCOUNT.value,
        DeliveryType.INVENTORY_CODE.value,
        DeliveryType.EMAIL_CODE.value,
        DeliveryType.MANUAL.value,
    }
    if delivery_type not in allowed:
        return
    if activation_mode not in {mode.value for mode in ActivationMode}:
        activation_mode = ActivationMode.MANUAL.value
    await state.update_data(
        offer_delivery=delivery_type,
        offer_activation_mode=activation_mode,
    )
    await state.set_state(ProviderOfferStates.validity_type)
    await edit_or_send(callback.message, 
        "كيف تُحسب مدة الاشتراك؟",
        reply_markup=_markup(
            [
                [
                    InlineKeyboardButton(
                        text="⏳ بالأيام (مثلاً: 7 أيام)",
                        callback_data="p:ov:d",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🗓 بالأشهر (مثلاً: شهر واحد)",
                        callback_data="p:ov:o",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📅 تاريخ نهاية ثابت",
                        callback_data="p:ov:f",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📦 حسب تاريخ الحساب",
                        callback_data="p:ov:i",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="✍️ يحدد عند التسليم",
                        callback_data="p:ov:m",
                    )
                ],
            ]
        ),
    )


async def _ask_start_trigger(
    message: Message,
    state: FSMContext,
    *,
    in_place: bool = False,
) -> None:
    async def render(
        text: str,
        *,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        if in_place:
            await edit_or_send(message, text, reply_markup=reply_markup)
        else:
            await message.answer(text, reply_markup=reply_markup)

    await state.set_state(ProviderOfferStates.start_trigger)
    await render(
        "متى تبدأ مدة الاشتراك؟",
        reply_markup=_markup(
            [
                [
                    InlineKeyboardButton(
                        text="بعد قبول الدفع",
                        callback_data="p:os:p",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="عند إرسال البيانات",
                        callback_data="p:os:d",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="بعد تأكيد المستخدم نجاح التفعيل",
                        callback_data="p:os:u",
                    )
                ],
            ]
        ),
    )


@router.callback_query(F.data.startswith("provider:offer_validity:") | F.data.startswith("p:ov:"))
async def offer_validity_pick(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    staff, data = await _active_callback_manager(
        callback,
        state,
        session,
        services,
        permission="can_manage_offers",
        expected_state=ProviderOfferStates.validity_type.state,
    )
    if not staff or not callback.message:
        return
    validity_token = (callback.data or "").split(":")[2]
    validity = {
        "d": ValidityType.DAYS_FROM_ACTIVATION.value,
        "o": ValidityType.MONTHS_FROM_ACTIVATION.value,
        "f": ValidityType.FIXED_OFFER_END.value,
        "i": ValidityType.INVENTORY_END.value,
        "m": ValidityType.MANUAL.value,
    }.get(validity_token, validity_token)
    allowed = {
        ValidityType.DAYS_FROM_ACTIVATION.value,
        ValidityType.MONTHS_FROM_ACTIVATION.value,
        ValidityType.FIXED_OFFER_END.value,
        ValidityType.INVENTORY_END.value,
        ValidityType.MANUAL.value,
    }
    if validity not in allowed:
        await edit_or_send(callback.message, "نوع الصلاحية غير معتمد.")
        return
    if validity == ValidityType.INVENTORY_END.value and data.get("offer_delivery") not in {
        DeliveryType.INVENTORY_ACCOUNT.value,
        DeliveryType.INVENTORY_CODE.value,
    }:
        await edit_or_send(callback.message, "صلاحية الحساب تحتاج أن يكون التسليم من المخزون.")
        return
    await state.update_data(offer_validity=validity, offer_validity_value=None, fixed_end=None)
    if validity in {
        ValidityType.DAYS_FROM_ACTIVATION.value,
        ValidityType.MONTHS_FROM_ACTIVATION.value,
    }:
        await state.set_state(ProviderOfferStates.validity_value)
        unit = "الأيام" if validity == ValidityType.DAYS_FROM_ACTIVATION.value else "الأشهر"
        await edit_or_send(callback.message, f"اكتب عدد {unit}:")
        return
    if validity == ValidityType.FIXED_OFFER_END.value:
        await state.set_state(ProviderOfferStates.validity_value)
        await edit_or_send(callback.message, "اكتب تاريخ النهاية بصيغة YYYY-MM-DD")
        return
    await _ask_start_trigger(callback.message, state, in_place=True)


@router.message(ProviderOfferStates.validity_value)
async def offer_validity_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, data = await _active_manager(
        message,
        state,
        session,
        services,
        permission="can_manage_offers",
    )
    if not staff:
        return
    validity = str(data["offer_validity"])
    if validity in {
        ValidityType.DAYS_FROM_ACTIVATION.value,
        ValidityType.MONTHS_FROM_ACTIVATION.value,
    }:
        try:
            value = int((message.text or "").strip())
        except ValueError:
            await message.answer("اكتب الرقم فقط.")
            return
        maximum = 1095 if validity == ValidityType.DAYS_FROM_ACTIVATION.value else 36
        if not 1 <= value <= maximum:
            await message.answer(f"القيمة يجب أن تكون بين 1 و{maximum}.")
            return
        await state.update_data(offer_validity_value=value)
    else:
        try:
            fixed_end = datetime.strptime((message.text or "").strip(), "%Y-%m-%d").replace(
                hour=23,
                minute=59,
                second=59,
                tzinfo=UTC,
            )
        except ValueError:
            await message.answer("صيغة التاريخ غير صحيحة. مثال: 2026-09-30")
            return
        if fixed_end <= datetime.now(UTC):
            await message.answer("تاريخ النهاية يجب أن يكون في المستقبل.")
            return
        await state.update_data(fixed_end=fixed_end)
    await _ask_start_trigger(message, state)


@router.callback_query(F.data.startswith("provider:offer_start:") | F.data.startswith("p:os:"))
async def offer_start_pick(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    staff, _data = await _active_callback_manager(
        callback,
        state,
        session,
        services,
        permission="can_manage_offers",
        expected_state=ProviderOfferStates.start_trigger.state,
    )
    if not staff or not callback.message:
        return
    trigger_token = (callback.data or "").split(":")[2]
    trigger = {
        "p": SubscriptionStartTrigger.PAYMENT_APPROVED.value,
        "d": SubscriptionStartTrigger.DELIVERY.value,
        "u": SubscriptionStartTrigger.USER_ACTIVATED.value,
    }.get(trigger_token, trigger_token)
    if trigger not in {
        SubscriptionStartTrigger.PAYMENT_APPROVED.value,
        SubscriptionStartTrigger.DELIVERY.value,
        SubscriptionStartTrigger.USER_ACTIVATED.value,
    }:
        return
    await state.update_data(offer_start_trigger=trigger)
    await state.set_state(ProviderOfferStates.daily_limit)
    await edit_or_send(callback.message, "اكتب الحد اليومي للطلبات، أو اكتب - لغير محدود:")


@router.message(ProviderOfferStates.daily_limit)
async def offer_daily_limit(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, _data = await _active_manager(
        message,
        state,
        session,
        services,
        permission="can_manage_offers",
    )
    if not staff:
        return
    raw = (message.text or "").strip()
    daily_limit = None
    if raw != "-":
        try:
            daily_limit = int(raw)
        except ValueError:
            await message.answer("اكتب رقمًا أو -")
            return
        if not 1 <= daily_limit <= 100000:
            await message.answer("الحد يجب أن يكون بين 1 و100000.")
            return
    await state.update_data(offer_daily_limit=daily_limit)
    await state.set_state(ProviderOfferStates.terms)
    await message.answer("اكتب شروط العرض وسياسة الاستخدام، أو اكتب -")


@router.message(ProviderOfferStates.terms)
async def offer_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    """Create the offer as a draft, then force a guide before publication."""
    staff, data = await _active_manager(
        message,
        state,
        session,
        services,
        permission="can_manage_offers",
    )
    if not staff:
        return
    section = await session.get(CatalogSection, int(data["section_id"]))
    service_item = await session.get(CatalogServiceItem, int(data["service_id"]))
    if not section or not service_item or section.provider_id != staff.provider_id:
        await state.clear()
        await message.answer("تعذر العثور على القسم أو الخدمة.")
        return
    category = await session.scalar(select(Category).where(Category.name == section.name))
    if not category:
        category = await session.scalar(
            select(Category)
            .where(Category.is_active.is_(True))
            .order_by(Category.sort_order)
            .limit(1)
        )
    if not category:
        category = Category(name="خدمات رقمية", emoji="🛍")
        session.add(category)
        await session.flush()
    terms = (message.text or "").strip()
    duration_days = (
        int(data["offer_validity_value"])
        if data["offer_validity"] == ValidityType.DAYS_FROM_ACTIVATION.value
        else None
    )
    offer = Offer(
        provider_id=staff.provider_id,
        category_id=category.id,
        title=str(data["offer_title"]),
        description=str(data.get("offer_description") or ""),
        original_price_iqd=(
            int(data["offer_original_price"])
            if data.get("offer_original_price") is not None
            else None
        ),
        price_iqd=int(data["offer_price"]),
        service_fee_iqd=int(data["offer_fee"]),
        start_at=data.get("offer_start_at"),
        end_at=data.get("offer_end_at"),
        duration_days=duration_days,
        delivery_type=str(data["offer_delivery"]),
        daily_limit=data.get("offer_daily_limit"),
        terms="" if terms == "-" else terms[:4000],
        status=OfferStatus.DRAFT.value,
        is_active=False,
    )
    session.add(offer)
    await session.flush()
    session.add(
        OfferCatalogPlacement(
            offer_id=offer.id,
            provider_id=staff.provider_id,
            section_id=section.id,
            service_id=service_item.id,
        )
    )
    session.add(
        OfferValidityPolicy(
            offer_id=offer.id,
            validity_type=str(data["offer_validity"]),
            duration_value=data.get("offer_validity_value"),
            fixed_end_at=data.get("fixed_end"),
            start_trigger=str(data["offer_start_trigger"]),
        )
    )
    await services.workflows.ensure_offer(session, offer)
    await state.update_data(
        guide_offer_id=offer.id,
        guide_activation_mode=str(
            data.get("offer_activation_mode") or ActivationMode.MANUAL.value
        ),
        guide_steps=[],
    )
    await state.set_state(ProviderGuideStates.intro)
    await message.answer(
        "✅ تم حفظ العرض كمسودة.\n\n"
        "📖 <b>تعليمات التسجيل والتفعيل إجبارية</b>\n"
        "اكتب مقدمة قصيرة للطالب، مثل التنبيهات قبل تسجيل الدخول. "
        "اكتب <code>-</code> إذا لا توجد مقدمة.\n\n"
        "لن يظهر العرض للطلاب قبل إضافة خطوة تعليمات واحدة على الأقل.",
    )


@router.callback_query(F.data.startswith("provider:guide_resume:"))
async def provider_guide_resume_from_webapp(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    parts = (callback.data or "").split(":", 4)
    if len(parts) < 5:
        await edit_or_send(callback.message, "تعذر قراءة مسودة العرض.")
        return
    try:
        offer_id = int(parts[3])
    except ValueError:
        await edit_or_send(callback.message, "معرف العرض غير صحيح.")
        return
    activation_mode = parts[4]
    if activation_mode not in {mode.value for mode in ActivationMode}:
        activation_mode = ActivationMode.MANUAL.value
    offer = await session.get(Offer, offer_id)
    if offer is None:
        await edit_or_send(callback.message, "تعذر العثور على مسودة العرض.")
        return
    _user, staff = await _staff_for_provider(
        session, services, callback.from_user.id, offer.provider_id
    )
    if not staff or not staff.can_manage_offers or offer.provider_id != staff.provider_id:
        await edit_or_send(callback.message, "لا تملك صلاحية إكمال هذا العرض.")
        return
    if offer.status not in {OfferStatus.DRAFT.value, OfferStatus.REVIEW.value}:
        await edit_or_send(callback.message, "هذا العرض لم يعد في حالة تسمح بإكمال دليل التفعيل.")
        return
    await state.clear()
    await state.update_data(
        provider_id=staff.provider_id,
        guide_offer_id=offer.id,
        guide_activation_mode=activation_mode,
        guide_steps=[],
    )
    await state.set_state(ProviderGuideStates.intro)
    await edit_or_send(
        callback.message,
        "📖 <b>تعليمات التسجيل والتفعيل إجبارية</b>\n"
        "اكتب مقدمة قصيرة للطالب، أو اكتب <code>-</code> إذا لا توجد مقدمة.\n\n"
        "لن يظهر العرض للطلاب قبل إضافة خطوة تعليمات واحدة على الأقل.",
    )


def _guide_kind_keyboard() -> InlineKeyboardMarkup:
    return _markup(
        [
            [
                InlineKeyboardButton(text="📝 نص", callback_data="provider:guide_kind:text", style="primary"),
                InlineKeyboardButton(text="🖼 صورة", callback_data="provider:guide_kind:photo", style="primary"),
            ],
            [
                InlineKeyboardButton(text="🎞 فيديو", callback_data="provider:guide_kind:video"),
                InlineKeyboardButton(text="📎 ملف", callback_data="provider:guide_kind:document"),
            ],
            [InlineKeyboardButton(text="🔗 رابط", callback_data="provider:guide_kind:link")],
            [InlineKeyboardButton(text="❌ إلغاء المسودة", callback_data="provider:guide_cancel", style="danger")],
        ]
    )


@router.message(ProviderGuideStates.intro)
async def provider_guide_intro(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, data = await _active_manager(
        message, state, session, services, permission="can_manage_offers"
    )
    if not staff:
        return
    offer = await session.get(Offer, int(data.get("guide_offer_id") or 0))
    if not offer or offer.provider_id != staff.provider_id:
        await state.clear()
        await message.answer("تعذر العثور على مسودة العرض.")
        return
    intro = (message.text or "").strip()
    await state.update_data(guide_intro="" if intro == "-" else intro[:4000])
    await state.set_state(ProviderGuideStates.step_kind)
    await message.answer(
        "اختر نوع الخطوة الأولى. يمكن دمج النص والصور والفيديو والملفات والروابط:",
        reply_markup=_guide_kind_keyboard(),
    )


@router.callback_query(F.data.startswith("provider:guide_kind:"))
async def provider_guide_kind(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    staff, _data = await _active_callback_manager(
        callback,
        state,
        session,
        services,
        permission="can_manage_offers",
        expected_state=ProviderGuideStates.step_kind.state,
    )
    if not staff or not callback.message:
        return
    kind = (callback.data or "").split(":")[-1]
    if kind not in {"text", "photo", "video", "document", "link"}:
        return
    await state.update_data(guide_current_kind=kind)
    await state.set_state(ProviderGuideStates.step_content)
    prompts = {
        "text": "اكتب نص هذه الخطوة:",
        "photo": "أرسل صورة الخطوة، ويمكنك كتابة الشرح في وصف الصورة:",
        "video": "أرسل فيديو قصير، ويمكنك كتابة الشرح في وصف الفيديو:",
        "document": "أرسل ملف التعليمات، ويمكنك كتابة وصف معه:",
        "link": "أرسل الرابط كاملًا، ويجوز بعده كتابة عنوان الزر بهذا الشكل:\nhttps://example.com | فتح الموقع",
    }
    await edit_or_send(callback.message, prompts[kind])


@router.message(ProviderGuideStates.step_content)
async def provider_guide_content(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, data = await _active_manager(
        message, state, session, services, permission="can_manage_offers"
    )
    if not staff:
        return
    kind = str(data.get("guide_current_kind") or "")
    step: dict[str, str] | None = None
    if kind == "text" and message.text:
        step = {"kind": "text", "text": message.text.strip()[:4000]}
    elif kind == "photo" and message.photo:
        step = {
            "kind": "photo",
            "telegram_file_id": message.photo[-1].file_id,
            "text": (message.caption or "").strip()[:1000],
        }
    elif kind == "video" and message.video:
        step = {
            "kind": "video",
            "telegram_file_id": message.video.file_id,
            "text": (message.caption or "").strip()[:1000],
        }
    elif kind == "document" and message.document:
        step = {
            "kind": "document",
            "telegram_file_id": message.document.file_id,
            "text": (message.caption or "").strip()[:1000],
        }
    elif kind == "link" and message.text:
        parts = [part.strip() for part in message.text.split("|", 1)]
        url = parts[0]
        if url.startswith(("https://", "http://")):
            step = {
                "kind": "link",
                "url": url[:2000],
                "button_text": (parts[1] if len(parts) > 1 else "فتح الرابط")[:120],
                "text": "افتح الرابط واتبع التعليمات.",
            }
    if not step:
        await message.answer("المحتوى لا يطابق النوع المختار. أرسله مرة ثانية أو اضغط ❌ إلغاء العملية.")
        return
    steps = list(data.get("guide_steps") or [])
    steps.append(step)
    await state.update_data(guide_steps=steps)
    await state.set_state(ProviderGuideStates.more_steps)
    await message.answer(
        f"✅ تمت إضافة الخطوة رقم {len(steps)}.",
        reply_markup=_markup(
            [
                [InlineKeyboardButton(text="➕ إضافة خطوة أخرى", callback_data="provider:guide_more", style="primary")],
                [InlineKeyboardButton(text="↩️ حذف آخر خطوة", callback_data="provider:guide_remove_last")],
                [InlineKeyboardButton(text="✅ إنهاء ونشر العرض", callback_data="provider:guide_finish", style="success")],
                [InlineKeyboardButton(text="❌ إلغاء المسودة", callback_data="provider:guide_cancel", style="danger")],
            ]
        ),
    )


@router.callback_query(F.data == "provider:guide_more")
async def provider_guide_more(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ProviderGuideStates.step_kind)
    if callback.message:
        await edit_or_send(callback.message, "اختر نوع الخطوة التالية:", reply_markup=_guide_kind_keyboard())


@router.callback_query(F.data == "provider:guide_remove_last")
async def provider_guide_remove_last(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    steps = list(data.get("guide_steps") or [])
    if steps:
        steps.pop()
    await state.update_data(guide_steps=steps)
    await state.set_state(ProviderGuideStates.step_kind)
    if callback.message:
        await edit_or_send(callback.message, 
            f"حُذفت آخر خطوة. المتبقي: {len(steps)}. اختر نوع خطوة:",
            reply_markup=_guide_kind_keyboard(),
        )


async def _publish_or_continue_email_setup(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
    *,
    offer: Offer,
    staff: ProviderStaff,
    activation_mode: str,
) -> None:
    if activation_mode in {ActivationMode.EMAIL_CODE.value, ActivationMode.EMAIL_PASSWORD_CODE.value}:
        offer.status = OfferStatus.DRAFT.value
        offer.is_active = False
        await state.clear()
        await state.update_data(
            provider_id=staff.provider_id,
            email_offer_id=offer.id,
            activate_offer_after_email=True,
        )
        await state.set_state(ProviderEmailStates.provider_kind)
        await edit_or_send(
            message,
            "✅ تم حفظ نوع الحساب والتعليمات. بقي ربط البريد حتى يستطيع البوت جلب الرمز.\n\n"
            "📨 اختر مزود البريد:",
            reply_markup=_markup(
                [
                    [InlineKeyboardButton(text="🔴 Gmail", callback_data="provider:email_kind:gmail", style="primary")],
                    [InlineKeyboardButton(text="🔵 Outlook / Hotmail / Microsoft", callback_data="provider:email_kind:outlook", style="primary")],
                    [InlineKeyboardButton(text="🟣 Yahoo", callback_data="provider:email_kind:yahoo", style="primary")],
                ]
            ),
        )
        return
    inventory_offer = offer.delivery_type in {
        DeliveryType.INVENTORY_ACCOUNT.value,
        DeliveryType.INVENTORY_CODE.value,
    }
    offer.status = OfferStatus.OUT_OF_STOCK.value if inventory_offer else OfferStatus.ACTIVE.value
    offer.is_active = not inventory_offer
    await services.offer_lifecycle.queue_launch_announcement(session, offer, staff.user_id)
    await state.clear()
    await edit_or_send(
        message,
        (
            f"✅ تم حفظ العرض <b>{safe(offer.title)}</b> وإعدادات تسليمه.\n"
            "أضف حساباً أو كوداً واحداً على الأقل ليظهر للطلاب."
            if inventory_offer
            else f"✅ تم نشر العرض <b>{safe(offer.title)}</b>."
        ),
        reply_markup=_markup(
            [
                [InlineKeyboardButton(text="👁 معاينة التعليمات", callback_data=f"guide:view:offer:{offer.id}", style="primary")],
                [InlineKeyboardButton(text="🔑 إضافة مخزون", callback_data=f"provider:inventory_offer:{offer.id}", style="success")],
                [InlineKeyboardButton(text="🛍 العودة للمتجر", callback_data="provider:catalog")],
            ]
        ),
    )


@router.callback_query(F.data == "provider:guide_finish")
async def provider_guide_finish(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    data = await state.get_data()
    offer = await session.get(Offer, int(data.get("guide_offer_id") or 0))
    _user, staff = await _staff_for_provider(
        session, services, callback.from_user.id, offer.provider_id if offer else 0
    )
    if not staff or not offer or offer.provider_id != staff.provider_id:
        await state.clear()
        await edit_or_send(callback.message, "تعذر العثور على العرض أو الصلاحية.")
        return
    steps = list(data.get("guide_steps") or [])
    if not steps:
        await edit_or_send(callback.message, "يجب إضافة خطوة واحدة على الأقل قبل النشر.")
        return
    activation_mode = str(data.get("guide_activation_mode") or ActivationMode.MANUAL.value)
    await services.activation_guides.upsert(
        session,
        offer=offer,
        activation_mode=activation_mode,
        title="طريقة التسجيل والتفعيل",
        intro_text=str(data.get("guide_intro") or ""),
        steps=steps,
        actor_user_id=staff.user_id,
        acknowledgement_required=True,
        show_before_delivery=True,
    )
    await state.update_data(
        fulfillment_offer_id=offer.id,
        fulfillment_activation_mode=activation_mode,
    )
    await state.set_state(ProviderFulfillmentStates.account_type)
    await edit_or_send(
        callback.message,
        "ما نوع الحساب أو الخدمة؟",
        reply_markup=_markup(
            [
                [InlineKeyboardButton(text="👤 حساب خاص", callback_data="provider:fulfillment:type:private", style="primary")],
                [InlineKeyboardButton(text="👥 حساب مشترك", callback_data="provider:fulfillment:type:shared", style="primary")],
                [InlineKeyboardButton(text="🤝 تفعيل باقة أصدقائي فقط", callback_data="provider:fulfillment:type:friends_only", style="success")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("provider:fulfillment:type:"))
async def provider_fulfillment_type(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    staff, _data = await _active_callback_manager(
        callback, state, session, services,
        permission="can_manage_offers",
        expected_state=ProviderFulfillmentStates.account_type.state,
    )
    if not staff or not callback.message:
        return
    account_type = (callback.data or "").split(":")[3]
    if account_type not in {"private", "shared", "friends_only"}:
        return
    await state.update_data(fulfillment_account_type=account_type)
    if account_type == "friends_only":
        await edit_or_send(
            callback.message,
            "🤝 <b>باقة أصدقائي فقط</b>\n\n"
            "الحساب يُحجز لمجموعة معروفة، ويجب أن يكتمل العدد والدفع بالكامل قبل "
            "إرسال بيانات الحساب لجميع الأعضاء في اللحظة نفسها. هل توافق على فتح هذه الميزة؟",
            reply_markup=_markup([
                [InlineKeyboardButton(
                    text="✅ أوافق وأفعّلها",
                    callback_data="provider:fulfillment:friends_agree",
                    style="success",
                )],
                [InlineKeyboardButton(
                    text="❌ إلغاء",
                    callback_data="provider:fulfillment:friends_cancel",
                    style="danger",
                )],
            ]),
        )
        return
    if account_type == "shared":
        await state.set_state(ProviderFulfillmentStates.capacity)
        await edit_or_send(
            callback.message,
            "حدد سعة الحساب المشترك أو اختر غير محدود.",
            reply_markup=_markup([
                [InlineKeyboardButton(text="♾️ غير محدود", callback_data="provider:fulfillment:capacity:unlimited")],
                [InlineKeyboardButton(text="🔢 تحديد عدد", callback_data="provider:fulfillment:capacity:number", style="primary")],
            ]),
        )
        return
    await state.update_data(fulfillment_capacity=1, fulfillment_unlimited=False)
    await state.set_state(ProviderFulfillmentStates.temporary_mode)
    await edit_or_send(
        callback.message,
        "هل الحساب دائم طوال مدة الاشتراك أم مؤقت بالساعات؟",
        reply_markup=_markup([
            [InlineKeyboardButton(text="📅 طوال مدة الاشتراك", callback_data="provider:fulfillment:temporary:no", style="primary")],
            [InlineKeyboardButton(text="⏱ حساب مؤقت", callback_data="provider:fulfillment:temporary:yes", style="danger")],
        ]),
    )


@router.callback_query(F.data == "provider:fulfillment:friends_agree")
async def provider_fulfillment_friends_agree(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    await state.set_state(ProviderFulfillmentStates.capacity)
    await edit_or_send(
        callback.message,
        "👥 اكتب العدد الكامل للأصدقاء المطلوب. لن يُرسل الحساب قبل اكتمال العدد.",
        reply_markup=_markup([[InlineKeyboardButton(
            text="🔢 تحديد عدد الأصدقاء",
            callback_data="provider:fulfillment:capacity:number",
            style="primary",
        )]]),
    )


@router.callback_query(F.data == "provider:fulfillment:friends_cancel")
async def provider_fulfillment_friends_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ProviderFulfillmentStates.account_type)
    if callback.message:
        await edit_or_send(callback.message, "اختر نوع حساب آخر.")


@router.callback_query(F.data.startswith("provider:fulfillment:capacity:"))
async def provider_fulfillment_capacity_choice(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    choice = (callback.data or "").split(":")[3]
    if choice == "unlimited":
        await state.update_data(fulfillment_capacity=None, fulfillment_unlimited=True)
        await state.set_state(ProviderFulfillmentStates.temporary_mode)
        await edit_or_send(callback.message, "هل الحساب مؤقت؟", reply_markup=_markup([
            [InlineKeyboardButton(text="لا", callback_data="provider:fulfillment:temporary:no", style="primary")],
            [InlineKeyboardButton(text="نعم", callback_data="provider:fulfillment:temporary:yes", style="danger")],
        ]))
    else:
        await edit_or_send(callback.message, "اكتب العدد المسموح كاملاً، مثال: 5")


@router.message(ProviderFulfillmentStates.capacity)
async def provider_fulfillment_capacity_number(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")).strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 10000:
        await message.answer("اكتب عدداً صحيحاً من 1 إلى 10000.")
        return
    await state.update_data(fulfillment_capacity=int(raw), fulfillment_unlimited=False)
    await state.set_state(ProviderFulfillmentStates.temporary_mode)
    await message.answer("هل الحساب مؤقت؟", reply_markup=_markup([
        [InlineKeyboardButton(text="لا، طوال الاشتراك", callback_data="provider:fulfillment:temporary:no", style="primary")],
        [InlineKeyboardButton(text="نعم، مؤقت", callback_data="provider:fulfillment:temporary:yes", style="danger")],
    ]))


@router.callback_query(F.data.startswith("provider:fulfillment:temporary:"))
async def provider_fulfillment_temporary(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    temporary = (callback.data or "").endswith(":yes")
    if temporary:
        await state.set_state(ProviderFulfillmentStates.temporary_minutes)
        await edit_or_send(callback.message, "اكتب مدة الاستخدام بالدقائق، مثال: 180 لثلاث ساعات.")
        return
    await state.update_data(fulfillment_temporary_minutes=None, fulfillment_logout_required=False)
    await state.set_state(ProviderFulfillmentStates.student_email)
    await edit_or_send(callback.message, "هل التفعيل يتم على إيميل الطالب؟", reply_markup=_markup([
        [InlineKeyboardButton(text="✅ نعم", callback_data="provider:fulfillment:email:yes", style="success")],
        [InlineKeyboardButton(text="❌ لا", callback_data="provider:fulfillment:email:no", style="primary")],
    ]))


@router.message(ProviderFulfillmentStates.temporary_minutes)
async def provider_fulfillment_temporary_minutes(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")).strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 43200:
        await message.answer("اكتب مدة صحيحة بالدقائق.")
        return
    await state.update_data(
        fulfillment_temporary_minutes=int(raw),
        fulfillment_logout_required=True,
    )
    await state.set_state(ProviderFulfillmentStates.student_email)
    await message.answer("هل التفعيل يتم على إيميل الطالب؟", reply_markup=_markup([
        [InlineKeyboardButton(text="✅ نعم", callback_data="provider:fulfillment:email:yes", style="success")],
        [InlineKeyboardButton(text="❌ لا", callback_data="provider:fulfillment:email:no", style="primary")],
    ]))


@router.callback_query(F.data.startswith("provider:fulfillment:email:"))
async def provider_fulfillment_email(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    required = (callback.data or "").endswith(":yes")
    await state.update_data(fulfillment_student_email=required)
    if required:
        await state.set_state(ProviderFulfillmentStates.student_code)
        await edit_or_send(callback.message, "قد تطلب الخدمة رمزاً يصل إلى إيميل الطالب؟", reply_markup=_markup([
            [InlineKeyboardButton(text="✅ نعم، فعّل نقل الرمز", callback_data="provider:fulfillment:student_code:yes", style="success")],
            [InlineKeyboardButton(text="❌ لا", callback_data="provider:fulfillment:student_code:no", style="primary")],
        ]))
        return
    await _finish_fulfillment_setup(callback.message, state, callback.from_user.id if callback.from_user else 0)


@router.callback_query(F.data.startswith("provider:fulfillment:student_code:"))
async def provider_fulfillment_student_code(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    await state.update_data(fulfillment_student_code=(callback.data or "").endswith(":yes"))
    await _finish_fulfillment_setup(callback.message, state, callback.from_user.id if callback.from_user else 0)


async def _finish_fulfillment_setup(message: Message, state: FSMContext, telegram_id: int) -> None:
    # Actual database save is delegated to a callback-like continuation handler
    # by using the FSM context injection available to message handlers.
    await message.answer(
        "✅ تم جمع إعدادات نوع الحساب. اضغط الحفظ والنشر.",
        reply_markup=_markup([[InlineKeyboardButton(
            text="💾 حفظ إعدادات التسليم والمتابعة",
            callback_data="provider:fulfillment:save",
            style="success",
        )]]),
    )


@router.callback_query(F.data == "provider:fulfillment:save")
async def provider_fulfillment_save(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    data = await state.get_data()
    offer = await session.get(Offer, int(data.get("fulfillment_offer_id") or 0))
    _user, staff = await _staff_for_provider(
        session, services, callback.from_user.id, offer.provider_id if offer else 0
    )
    if not offer or not staff or offer.provider_id != staff.provider_id:
        await state.clear()
        return
    activation_mode = str(data.get("fulfillment_activation_mode") or ActivationMode.MANUAL.value)
    await services.provider_operations.configure_fulfillment(
        session,
        provider_id=staff.provider_id,
        offer_id=offer.id,
        account_type=str(data.get("fulfillment_account_type") or "private"),
        activation_mode=activation_mode,
        shared_capacity=data.get("fulfillment_capacity"),
        unlimited_capacity=bool(data.get("fulfillment_unlimited", False)),
        temporary_access_minutes=data.get("fulfillment_temporary_minutes"),
        logout_proof_required=bool(data.get("fulfillment_logout_required", False)),
        student_email_required=bool(data.get("fulfillment_student_email", False)),
        student_code_relay_enabled=bool(data.get("fulfillment_student_code", False)),
        otp_lease_seconds=min(60, int(services.settings.otp_account_lease_seconds)),
        max_otp_attempts=3,
        metadata={"configured_by_user_id": staff.user_id},
    )
    await _publish_or_continue_email_setup(
        callback.message,
        state,
        session,
        services,
        offer=offer,
        staff=staff,
        activation_mode=activation_mode,
    )


@router.callback_query(F.data == "provider:guide_cancel")
async def provider_guide_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    data = await state.get_data()
    offer = await session.get(Offer, int(data.get("guide_offer_id") or 0))
    _user, staff = await _staff_for_provider(
        session, services, callback.from_user.id, offer.provider_id if offer else 0
    )
    if offer and staff and offer.provider_id == staff.provider_id:
        offer.status = OfferStatus.DRAFT.value
        offer.is_active = False
    await state.clear()
    await edit_or_send(callback.message, "تم إيقاف إنشاء العرض. بقي كمسودة غير ظاهرة للطلاب.")


@router.callback_query(F.data == "provider:inventory")
async def provider_inventory(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_inventory:
        await edit_or_send(callback.message, "لا تملك صلاحية إدارة المخزون.")
        return
    if not await _require_entitlement(callback, session, services, staff, "inventory.manage"):
        return
    offers = list(
        (
            await session.scalars(
                select(Offer)
                .where(
                    Offer.provider_id == staff.provider_id,
                    Offer.delivery_type.in_(
                        [DeliveryType.INVENTORY_ACCOUNT.value, DeliveryType.INVENTORY_CODE.value]
                    ),
                )
                .order_by(Offer.created_at.desc())
            )
        ).all()
    )
    rows: list[list[InlineKeyboardButton]] = []
    lines = ["🔑 <b>مخزون المنصة</b>"]
    for offer in offers:
        available = int(
            await session.scalar(
                select(func.count())
                .select_from(InventoryItem)
                .where(InventoryItem.offer_id == offer.id, InventoryItem.status == "available")
            )
            or 0
        )
        lines.append(f"\n• {safe(offer.title)} — المتاح {available}")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"➕ مخزون: {offer.title[:35]}",
                    callback_data=f"provider:inventory_offer:{offer.id}",
                    style="success",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="↩️ متجري والعروض", callback_data="provider:catalog"
            )
        ]
    )
    await edit_or_send(callback.message, 
        "".join(lines) if offers else "لا توجد عروض من نوع حساب أو كود بعد.",
        reply_markup=_markup(rows),
    )


async def _start_inventory_add(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    staff: ProviderStaff,
    offer_id: int,
    *,
    reactivate_after_inventory: bool = False,
) -> None:
    offer = await session.get(Offer, offer_id)
    if (
        not staff.can_manage_inventory
        or not offer
        or offer.provider_id != staff.provider_id
        or offer.delivery_type not in {DeliveryType.INVENTORY_ACCOUNT.value, DeliveryType.INVENTORY_CODE.value}
    ):
        await edit_or_send(message, "العرض غير صالح لإضافة المخزون أو لا يخص منصتك.")
        return
    guide = await session.scalar(select(OfferActivationGuide).where(OfferActivationGuide.offer_id == offer.id))
    activation_mode = str(guide.activation_mode if guide else "")
    item_kind = "account" if offer.delivery_type == DeliveryType.INVENTORY_ACCOUNT.value else "code"
    simple_account = activation_mode in {
        ActivationMode.EMAIL_PASSWORD.value,
        ActivationMode.EMAIL_PASSWORD_CODE.value,
    }
    await state.clear()
    await state.update_data(
        provider_id=staff.provider_id,
        offer_id=offer.id,
        item_kind=item_kind,
        inventory_simple_account=simple_account,
        reactivate_after_inventory=reactivate_after_inventory,
    )
    await state.set_state(ProviderInventoryStates.label)
    await edit_or_send(message, "اكتب عنوان العنصر، مثال: حساب Gemini أو كود شهر:")


@router.callback_query(F.data.startswith("p:cred:"))
async def inventory_refresh_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    try:
        offer_id = int((callback.data or "").split(":")[2])
    except (ValueError, IndexError):
        await edit_or_send(callback.message, "بيانات العرض غير صحيحة.")
        return
    provider_id = int(
        await session.scalar(select(Offer.provider_id).where(Offer.id == offer_id)) or 0
    )
    _user, staff = await _staff_for_provider(
        session, services, callback.from_user.id, provider_id
    )
    if not staff:
        await edit_or_send(callback.message, "العرض غير موجود أو لا تملك إدارته.")
        return
    if not await _require_entitlement(callback, session, services, staff, "inventory.manage"):
        return
    await _start_inventory_add(
        callback.message, state, session, staff, offer_id, reactivate_after_inventory=True
    )


@router.callback_query(F.data.startswith("provider:inventory_offer:"))
async def inventory_add_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    try:
        offer_id = int((callback.data or "").split(":")[2])
    except (ValueError, IndexError):
        await edit_or_send(callback.message, "بيانات العرض غير صحيحة.")
        return
    provider_id = int(
        await session.scalar(select(Offer.provider_id).where(Offer.id == offer_id)) or 0
    )
    _user, staff = await _staff_for_provider(
        session, services, callback.from_user.id, provider_id
    )
    if not staff:
        await edit_or_send(callback.message, "العرض غير موجود أو لا تملك إدارته.")
        return
    if not await _require_entitlement(callback, session, services, staff, "inventory.manage"):
        return
    await _start_inventory_add(callback.message, state, session, staff, offer_id)


@router.message(ProviderInventoryStates.label)
async def inventory_label(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, data = await _active_manager(
        message,
        state,
        session,
        services,
        permission="can_manage_inventory",
    )
    if not staff:
        return
    label = (message.text or "").strip()[:120]
    if len(label) < 2:
        await message.answer("اكتب عنوانًا واضحًا.")
        return
    await state.update_data(item_label=label)
    if data.get("item_kind") == "account" and data.get("inventory_simple_account"):
        await state.set_state(ProviderInventoryStates.email)
        await message.answer(
            "📧 اكتب إيميل الحساب فقط.\n\n"
            "مثال: <code>student@example.com</code>\n"
            "[للرجوع استخدم زر ⬅️ رجوع أو /cancel]"
        )
        return
    await state.set_state(ProviderInventoryStates.payload)
    prompt = (
        "🔑 أرسل كود التفعيل فقط:"
        if data.get("item_kind") == "code"
        else "🧾 أرسل بيانات العنصر المخصصة كنص عادي. لا تحتاج JSON."
    )
    await message.answer(prompt)


def _valid_inventory_email(value: str) -> bool:
    if len(value) > 255 or value.count("@") != 1 or " " in value:
        return False
    local, domain = value.rsplit("@", 1)
    return bool(local and "." in domain and len(domain) >= 3)


@router.message(ProviderInventoryStates.email)
async def inventory_email(
    message: Message, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    staff, _data = await _active_manager(
        message, state, session, services, permission="can_manage_inventory"
    )
    if not staff:
        return
    email = (message.text or "").strip().lower()
    if not _valid_inventory_email(email):
        await message.answer("❌ صيغة الإيميل غير صحيحة. مثال: name@gmail.com")
        return
    await state.update_data(item_email=email)
    await state.set_state(ProviderInventoryStates.password)
    await message.answer(
        "🔐 أرسل كلمة مرور الحساب. سيتم تشفيرها ولن تظهر في لوحة الإدارة."
    )


@router.message(ProviderInventoryStates.password)
async def inventory_password(
    message: Message, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    staff, _data = await _active_manager(
        message, state, session, services, permission="can_manage_inventory"
    )
    if not staff:
        return
    password = (message.text or "").strip()
    if len(password) < 2:
        await message.answer("كلمة المرور فارغة أو قصيرة جدًا.")
        return
    await state.update_data(item_password=password)
    await state.set_state(ProviderInventoryStates.instructions)
    await message.answer(
        "📖 اكتب ملاحظة قصيرة خاصة بهذا الحساب، أو أرسل <code>-</code>.\n"
        "تعليمات العرض العامة بالصور والنصوص ستظهر للطالب تلقائيًا."
    )


@router.message(ProviderInventoryStates.instructions)
async def inventory_instructions(
    message: Message, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    staff, data = await _active_manager(
        message, state, session, services, permission="can_manage_inventory"
    )
    if not staff:
        return
    note = (message.text or "").strip()
    payload = json.dumps(
        {
            "login_email": str(data["item_email"]),
            "login_password": str(data["item_password"]),
            "instructions": "" if note == "-" else note[:2000],
        },
        ensure_ascii=False,
    )
    normalized = " ".join(payload.split())
    fingerprint = services.fulfillment.secrets.hash_value(
        f"{data['offer_id']}:{data['item_kind']}:{normalized}"
    )
    duplicate = await session.scalar(
        select(InventoryFingerprint.id).where(
            InventoryFingerprint.offer_id == int(data["offer_id"]),
            InventoryFingerprint.fingerprint == fingerprint,
        )
    )
    if duplicate:
        await message.answer("هذا الحساب مضاف مسبقًا لهذا العرض ⚠️")
        return
    await state.update_data(item_payload=payload, item_fingerprint=fingerprint)
    await state.set_state(ProviderInventoryStates.expires_at)
    await message.answer("📅 اكتب تاريخ انتهاء الحساب YYYY-MM-DD، أو - إذا لا يوجد:")


@router.message(ProviderInventoryStates.payload)
async def inventory_payload(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, data = await _active_manager(
        message,
        state,
        session,
        services,
        permission="can_manage_inventory",
    )
    if not staff:
        return
    payload = (message.text or "").strip()
    if len(payload) < 2:
        await message.answer("البيانات فارغة.")
        return
    normalized = " ".join(payload.split())
    fingerprint = services.fulfillment.secrets.hash_value(
        f"{data['offer_id']}:{data['item_kind']}:{normalized}"
    )
    duplicate = await session.scalar(
        select(InventoryFingerprint.id).where(
            InventoryFingerprint.offer_id == int(data["offer_id"]),
            InventoryFingerprint.fingerprint == fingerprint,
        )
    )
    if duplicate:
        await message.answer("هذا الحساب أو الكود مضاف مسبقًا لهذا العرض ⚠️")
        return
    await state.update_data(item_payload=payload, item_fingerprint=fingerprint)
    await state.set_state(ProviderInventoryStates.expires_at)
    await message.answer("اكتب تاريخ انتهاء الحساب YYYY-MM-DD، أو - إذا لا يوجد:")


@router.message(ProviderInventoryStates.expires_at)
async def inventory_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, data = await _active_manager(
        message,
        state,
        session,
        services,
        permission="can_manage_inventory",
    )
    if not staff:
        return
    expires_at = None
    raw = (message.text or "").strip()
    if raw != "-":
        try:
            expires_at = datetime.strptime(raw, "%Y-%m-%d").replace(
                hour=23,
                minute=59,
                second=59,
                tzinfo=UTC,
            )
        except ValueError:
            await message.answer("صيغة التاريخ غير صحيحة، مثال: 2026-09-30")
            return
        if expires_at <= datetime.now(UTC):
            await message.answer("تاريخ الانتهاء يجب أن يكون في المستقبل.")
            return
    offer = await session.get(Offer, int(data["offer_id"]))
    if not offer or offer.provider_id != staff.provider_id:
        await state.clear()
        return
    policy = await services.student_subscriptions.policy(session, offer)
    if policy.validity_type == ValidityType.INVENTORY_END.value and not expires_at:
        await message.answer(
            "هذا العرض يعتمد تاريخ انتهاء الحساب، لذلك يجب إدخال تاريخ لكل عنصر مخزون."
        )
        return
    duplicate = await session.scalar(
        select(InventoryFingerprint.id).where(
            InventoryFingerprint.offer_id == offer.id,
            InventoryFingerprint.fingerprint == str(data["item_fingerprint"]),
        )
    )
    if duplicate:
        await state.clear()
        await message.answer("هذا العنصر أضيف مسبقًا ولم تتم إضافته مرة ثانية.")
        return
    item = InventoryItem(
        offer_id=offer.id,
        item_kind=str(data["item_kind"]),
        label=str(data["item_label"]),
        encrypted_payload=services.fulfillment.secrets.encrypt(str(data["item_payload"])),
        expires_at=expires_at,
        created_by_user_id=staff.user_id,
    )
    session.add(item)
    await session.flush()
    session.add(
        InventoryFingerprint(
            offer_id=offer.id,
            inventory_item_id=item.id,
            fingerprint=str(data["item_fingerprint"]),
        )
    )
    reactivated = False
    if data.get("reactivate_after_inventory") or offer.status == OfferStatus.OUT_OF_STOCK.value:
        expired_items = list(
            (
                await session.scalars(
                    select(InventoryItem).where(
                        InventoryItem.offer_id == offer.id,
                        InventoryItem.status == InventoryStatus.EXPIRED.value,
                        InventoryItem.id != item.id,
                    )
                )
            ).all()
        )
        for expired_item in expired_items:
            expired_item.status = InventoryStatus.PROBLEM.value
            expired_item.remediation_note = "استبدلت ببيانات اعتماد مجددة"
        if offer.end_at and offer.end_at <= datetime.now(UTC):
            offer.end_at = None
        offer.status = OfferStatus.ACTIVE.value
        offer.is_active = True
        await session.flush()
        reactivated = True
    if reactivated:
        await services.offer_lifecycle.queue_launch_announcement(
            session, offer, staff.user_id
        )
    await state.clear()
    await message.answer(
        "تم تشفير العنصر وإضافته للمخزون وإعادة تفعيل العرض ✅"
        if reactivated
        else "تم تشفير العنصر وإضافته للمخزون ✅",
        reply_markup=_markup(
            [[InlineKeyboardButton(text="🔑 العودة للمخزون", callback_data="provider:inventory")]]
        ),
    )


async def _render_provider_payment_methods(
    message: Message, session: AsyncSession, staff: ProviderStaff
) -> None:
    methods = list(
        (await session.scalars(
            select(PaymentMethod).where(PaymentMethod.provider_id == staff.provider_id).order_by(
                PaymentMethod.sort_order, PaymentMethod.id
            )
        )).all()
    )
    rows = [[InlineKeyboardButton(text="➕ إضافة طريقة دفع", callback_data="provider:pm_add", style="success")]]
    lines = ["🏦 <b>طرق دفع المنصة</b>"]
    for method in methods:
        icon = "✅" if method.is_active else "⏸"
        lines.append(f"\n• {icon} {safe(method.name)} — {safe(method.recipient)}")
        rows.append([InlineKeyboardButton(
            text=f"{icon} {method.name[:35]}",
            callback_data=f"provider:pm_toggle:{method.id}",
            style="success" if method.is_active else "danger",
        )])
    rows.append([InlineKeyboardButton(text="↩️ لوحة المنصة", callback_data=f"provider:select:{staff.provider_id}")])
    await edit_or_send(message, "".join(lines), reply_markup=_markup(rows))


@router.callback_query(F.data == "provider:payment_methods")
async def provider_payment_methods(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_review_payments:
        await edit_or_send(callback.message, "لا تملك صلاحية إدارة طرق الدفع.")
        return
    await _render_provider_payment_methods(callback.message, session, staff)


@router.callback_query(F.data == "provider:pm_add")
async def payment_method_add_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_review_payments:
        return
    await state.clear()
    await state.update_data(provider_id=staff.provider_id)
    await state.set_state(ProviderPaymentMethodStates.method_type)
    await edit_or_send(
        callback.message,
        "اختر طريقة الدفع التي ستظهر للطالب:",
        reply_markup=_markup(
            [
                [InlineKeyboardButton(
                    text="💳 دفع إلكتروني (ماستر كارد، زين كاش)",
                    callback_data="provider:pm_type:electronic",
                    style="primary",
                )],
                [InlineKeyboardButton(
                    text="📱 دفع بالرصيد (آسيا، زين، كورك)",
                    callback_data="provider:pm_type:mobile_balance",
                    style="primary",
                )],
            ]
        ),
    )


@router.callback_query(F.data.startswith("provider:pm_type:"))
async def payment_method_type(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    staff, _data = await _active_callback_manager(
        callback,
        state,
        session,
        services,
        permission="can_review_payments",
        expected_state=ProviderPaymentMethodStates.method_type.state,
    )
    if not staff or not callback.message:
        return
    channel = (callback.data or "").split(":")[2]
    if channel not in {"electronic", "mobile_balance"}:
        return
    await state.update_data(pm_channel=channel, pm_balance_mode=None)
    if channel == "mobile_balance":
        await state.set_state(ProviderPaymentMethodStates.balance_mode)
        await edit_or_send(
            callback.message,
            "كيف يستلم صاحب المنصة دفع الرصيد؟",
            reply_markup=_markup(
                [
                    [InlineKeyboardButton(
                        text="📲 تحويل رصيد إلى رقم",
                        callback_data="provider:pm_balance:phone_transfer",
                        style="primary",
                    )],
                    [InlineKeyboardButton(
                        text="🧾 إرسال صورة كارت تعبئة",
                        callback_data="provider:pm_balance:recharge_card",
                        style="primary",
                    )],
                ]
            ),
        )
        return
    await state.set_state(ProviderPaymentMethodStates.recipient)
    await edit_or_send(callback.message, "اكتب رقم الحساب أو رابط الدفع الذي سيظهر للطالب:")


@router.callback_query(F.data.startswith("provider:pm_balance:"))
async def payment_method_balance_mode(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    staff, _data = await _active_callback_manager(
        callback,
        state,
        session,
        services,
        permission="can_review_payments",
        expected_state=ProviderPaymentMethodStates.balance_mode.state,
    )
    if not staff or not callback.message:
        return
    mode = (callback.data or "").split(":")[2]
    if mode not in {"phone_transfer", "recharge_card"}:
        return
    await state.update_data(pm_balance_mode=mode)
    await state.set_state(ProviderPaymentMethodStates.recipient)
    prompt = (
        "اكتب رقم الهاتف الذي يستقبل تحويل الرصيد:"
        if mode == "phone_transfer"
        else "اكتب اسم شركة الاتصال أو تعليمات الجهة المستلمة للكارت:"
    )
    await edit_or_send(callback.message, prompt)


@router.message(ProviderPaymentMethodStates.recipient)
async def payment_method_recipient(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, _data = await _active_manager(
        message, state, session, services, permission="can_review_payments"
    )
    if not staff:
        return
    recipient = (message.text or "").strip()[:255]
    if len(recipient) < 3:
        await message.answer("اكتب بيانات استلام واضحة.")
        return
    await state.update_data(pm_recipient=recipient)
    await state.set_state(ProviderPaymentMethodStates.instructions)
    await message.answer(
        "اكتب تعليمات الدفع ورفع الإثبات. ويمكنك تضمين طريقة استخراج الوصل."
    )


@router.message(ProviderPaymentMethodStates.instructions)
async def payment_method_instructions(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, _data = await _active_manager(
        message, state, session, services, permission="can_review_payments"
    )
    if not staff:
        return
    instructions = (message.text or "").strip()[:4000]
    if len(instructions) < 3:
        await message.answer("اكتب تعليمات واضحة.")
        return
    await state.update_data(pm_instructions=instructions)
    await state.set_state(ProviderPaymentMethodStates.proof_guide)
    await message.answer(
        "أرسل صورة توضيحية لطريقة استخراج الوصل، أو اكتب <code>-</code> لتخطي الصورة.",
    )


@router.message(ProviderPaymentMethodStates.proof_guide)
async def payment_method_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, data = await _active_manager(
        message, state, session, services, permission="can_review_payments"
    )
    if not staff:
        return
    guide_file_id = message.photo[-1].file_id if message.photo else None
    skip = (message.text or "").strip() == "-"
    if not guide_file_id and not skip:
        await message.answer("أرسل صورة، أو اكتب - لتخطيها.")
        return
    try:
        method = await services.provider_operations.create_payment_method(
            session,
            provider_id=staff.provider_id,
            channel=str(data["pm_channel"]),
            recipient=str(data["pm_recipient"]),
            instructions=str(data["pm_instructions"]),
            balance_mode=data.get("pm_balance_mode"),
            proof_guide_file_id=guide_file_id,
            proof_guide_text=str(data["pm_instructions"]),
        )
    except ValueError as exc:
        await message.answer(safe(str(exc)))
        return
    await state.clear()
    await message.answer(
        f"تمت إضافة طريقة الدفع {method.icon} <b>{safe(method.name)}</b> ✅",
        reply_markup=_markup(
            [[InlineKeyboardButton(text="💳 طرق الدفع", callback_data="provider:payment_methods")]]
        ),
    )


@router.callback_query(F.data.startswith("provider:pm_toggle:"))
async def payment_method_toggle(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    method = await session.get(PaymentMethod, int((callback.data or "").split(":")[2]))
    if (
        not staff
        or not staff.can_review_payments
        or not method
        or method.provider_id != staff.provider_id
    ):
        await edit_or_send(callback.message, "غير مصرح.")
        return
    method.is_active = not method.is_active
    await session.flush()
    await _render_provider_payment_methods(callback.message, session, staff)


@router.callback_query(F.data.startswith("provider:ticket:"))
async def provider_ticket_details(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    ticket = await session.get(SupportTicket, int((callback.data or "").split(":")[2]))
    if not staff or not staff.can_support or not ticket or ticket.provider_id != staff.provider_id:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    messages = list(
        (
            await session.scalars(
                select(TicketMessage)
                .where(TicketMessage.ticket_id == ticket.id)
                .order_by(TicketMessage.created_at.desc())
                .limit(10)
            )
        ).all()
    )
    lines = [
        f"🎫 <b>{safe(ticket.subject)}</b>",
        f"\nرقم التذكرة: <code>{ticket.public_id}</code>",
        f"\nالحالة: {safe(ticket.status)}",
    ]
    for item in reversed(messages):
        lines.append(f"\n\n<b>{safe(item.sender_role)}:</b> {safe(item.text)}")
    await state.clear()
    await state.update_data(provider_id=staff.provider_id, ticket_id=ticket.id)
    await edit_or_send(callback.message, 
        "".join(lines),
        reply_markup=_markup(
            [
                [
                    InlineKeyboardButton(
                        text="✍️ الرد على التذكرة",
                        callback_data=f"provider:ticket_reply:{ticket.id}",
                        style="success",
                    )
                ],
                [InlineKeyboardButton(text="↩️ التذاكر", callback_data="provider:tickets")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("provider:ticket_reply:"))
async def provider_ticket_reply_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    ticket_id = int((callback.data or "").split(":")[2])
    ticket = await session.get(SupportTicket, ticket_id)
    if not staff or not staff.can_support or not ticket or ticket.provider_id != staff.provider_id:
        return
    await state.clear()
    await state.update_data(provider_id=staff.provider_id, ticket_id=ticket.id)
    await state.set_state(ProviderTicketReplyStates.text)
    await edit_or_send(callback.message, "اكتب رد المنصة على المستخدم:")


@router.message(ProviderTicketReplyStates.text)
async def provider_ticket_reply_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    staff, data = await _active_manager(
        message,
        state,
        session,
        services,
        permission="can_support",
    )
    if not staff:
        return
    text = (message.text or "").strip()[:4000]
    if len(text) < 2:
        await message.answer("اكتب ردًا واضحًا.")
        return
    ticket = await session.get(SupportTicket, int(data["ticket_id"]))
    if not ticket or ticket.provider_id != staff.provider_id:
        await state.clear()
        return
    session.add(
        TicketMessage(
            ticket_id=ticket.id,
            sender_user_id=staff.user_id,
            sender_role="provider",
            text=text,
        )
    )
    ticket.status = TicketStatus.WAITING_USER.value
    user = await services.users.get_by_id(session, ticket.user_id)
    if user:
        await services.notifications.send_user(
            session,
            user,
            f"رد منصة على التذكرة {ticket.public_id}",
            safe(text),
        )
    await state.clear()
    await message.answer("تم إرسال الرد للمستخدم ✅")
