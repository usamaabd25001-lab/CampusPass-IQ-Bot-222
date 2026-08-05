from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin.common import admin_actor, admin_back, require_admin
from app.bot.states import (
    AdminAssignStaffStates,
    AdminCatalogSectionStates,
    AdminCatalogServiceStates,
    AdminCategoryStates,
    AdminEmailStates,
    AdminInventoryStates,
    AdminOfferImageStates,
    AdminOfferStates,
    AdminPaymentMethodStates,
    AdminProviderLogoStates,
    AdminProviderStates,
)
from app.bot.ui import edit_or_send, callback_notice
from app.core.config import Settings
from app.core.emoji import smart_emoji
from app.core.utils import parse_money, safe
from app.db.models import (
    CatalogSection,
    CatalogServiceItem,
    Category,
    DeliveryType,
    EmailAccount,
    EmailAccountStatus,
    InventoryFingerprint,
    InventoryItem,
    Offer,
    OfferCatalogPlacement,
    OfferStatus,
    OfferValidityPolicy,
    PaymentMethod,
    Provider,
    ProviderStaff,
    ProviderStatus,
    ReportPlan,
    SubscriptionStartTrigger,
    ValidityType,
)
from app.services.branding import BrandingCandidate
from app.services.container import Services
from app.services.platform_access import mark_platform_authorization_dirty

router = Router(name="admin_catalog")


def _rows(
    items: list[tuple[str, str, str | None]], back: str = "admin:home"
) -> InlineKeyboardMarkup:
    rows = []
    for text, callback, style in items:
        rows.append([InlineKeyboardButton(text=text, callback_data=callback, style=style)])
    rows.append([InlineKeyboardButton(text="↩️ رجوع", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------- Providers ----------------
@router.callback_query(F.data == "admin:providers")
async def providers_list(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    providers = list(
        (
            await session.scalars(select(Provider).order_by(Provider.created_at.desc()).limit(50))
        ).all()
    )
    items = [("➕ إضافة منصة", "admin:provider_add", "success")]
    for p in providers:
        icon = "✅" if p.status == ProviderStatus.ACTIVE.value and p.is_active else "⏸"
        items.append((f"{icon} {p.name_ar} — {p.status}", f"admin:provider:{p.id}", "primary"))
    await edit_or_send(callback.message, "🏢 <b>المنصات</b>", reply_markup=_rows(items))


@router.callback_query(F.data == "admin:provider_add")
async def provider_add_start(
    callback: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.set_state(AdminProviderStates.name_ar)
    await edit_or_send(callback.message, "اكتب اسم المنصة بالعربي:")


@router.message(AdminProviderStates.name_ar)
async def provider_name_ar(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = " ".join((message.text or "").split())
    if len(value) < 2:
        return await message.answer("اكتب اسمًا واضحًا.")
    if await session.scalar(select(Provider.id).where(Provider.name_ar == value)):
        return await message.answer("اسم المنصة مستخدم مسبقًا. اختر اسمًا مختلفًا.")
    await state.update_data(name_ar=value)
    await state.set_state(AdminProviderStates.name_en)
    await message.answer("اكتب اسم المنصة بالإنجليزي، أو اكتب -")


@router.message(AdminProviderStates.name_en)
async def provider_name_en(message: Message, state: FSMContext) -> None:
    value = " ".join((message.text or "").split())
    await state.update_data(name_en="" if value == "-" else value[:180])
    await state.set_state(AdminProviderStates.slug)
    await message.answer("اكتب معرفًا إنجليزيًا فريدًا بدون مسافات، مثال: platform-x")


@router.message(AdminProviderStates.slug)
async def provider_slug(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = (message.text or "").strip().lower().replace(" ", "-")
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        return await message.answer("استخدم حروفًا إنجليزية وأرقامًا و - أو _ فقط.")
    if await session.scalar(select(Provider.id).where(Provider.slug == value)):
        return await message.answer("هذا المعرف مستخدم، اختر غيره.")
    await state.update_data(slug=value)
    await state.set_state(AdminProviderStates.description)
    await message.answer("اكتب وصف المنصة، أو اكتب -")


@router.message(AdminProviderStates.description)
async def provider_description(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    await state.update_data(description="" if value == "-" else value[:2000])
    await state.set_state(AdminProviderStates.contact)
    await message.answer("اكتب معرف التواصل بدون @، أو اكتب -")


@router.message(AdminProviderStates.contact)
async def provider_contact(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip().lstrip("@")
    await state.update_data(contact_username=None if value == "-" else value[:64])
    await state.set_state(AdminProviderStates.commission)
    await message.answer("اكتب نسبة إدارة خدمات المنصة من 0 إلى 100، مثال: 5")


@router.message(AdminProviderStates.commission)
async def provider_commission(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    try:
        percent = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب النسبة بالأرقام.")
    if not 0 <= percent <= 100:
        return await message.answer("النسبة يجب أن تكون بين 0 و100.")
    data = await state.get_data()
    provider = Provider(
        name_ar=data["name_ar"],
        name_en=data["name_en"],
        slug=data["slug"],
        description=data["description"],
        contact_username=data["contact_username"],
        management_percent=percent,
        status=ProviderStatus.PENDING.value,
        is_active=False,
    )
    session.add(provider)
    await session.flush()
    actor = await admin_actor(session, services, message)
    await services.subscriptions.ensure_subscription(session, provider, actor)
    await services.catalog.create_default_provider_catalog(session, provider)
    await services.audit.log(
        session, actor, "provider.created", "provider", str(provider.id), {"name": provider.name_ar}
    )
    await state.clear()
    await state.update_data(provider_logo_id=provider.id, logo_required=True)
    await state.set_state(AdminProviderLogoStates.logo)
    await message.answer(
        f"تم إنشاء المنصة <b>{safe(provider.name_ar)}</b> كمسودة ✅\n\n"
        "🖼 <b>الخطوة الإلزامية الآن:</b> أرسل شعار المنصة كصورة داخل تيليجرام. "
        "لن يتم تفعيل المنصة قبل حفظ الشعار وربطه بالتقارير."
    )


async def _render_admin_provider(message: Message, provider: Provider) -> None:
    active = provider.status == ProviderStatus.ACTIVE.value and provider.is_active
    rows = [
        [
            InlineKeyboardButton(
                text="⏸ إيقاف المنصة" if active else "▶️ تفعيل المنصة",
                callback_data=f"admin:provider_toggle:{provider.id}",
                style="danger" if active else "success",
            ),
            InlineKeyboardButton(
                text="💼 الاشتراك والخصائص",
                callback_data=f"admin:provider_sub:{provider.id}",
                style="success",
            ),
        ],
        [
            InlineKeyboardButton(
                text="📊 خطة التقارير",
                callback_data=f"admin:provider_plan:{provider.id}",
                style="primary",
            ),
            InlineKeyboardButton(
                text="🖼 تغيير الشعار",
                callback_data=f"admin:provider_logo:{provider.id}",
                style="success",
            ),
        ],
        [
            InlineKeyboardButton(
                text="📂 الأقسام والخدمات",
                callback_data=f"admin:provider_catalog:{provider.id}",
                style="primary",
            ),
            InlineKeyboardButton(
                text="👨‍💼 تعيين موظف",
                callback_data=f"admin:staff_add:{provider.id}",
            ),
        ],
        [InlineKeyboardButton(text="↩️ المنصات", callback_data="admin:providers")],
    ]
    await edit_or_send(
        message,
        f"🏢 <b>{safe(provider.name_ar)}</b>\n"
        f"الإنجليزي: {safe(provider.name_en)}\n"
        f"الحالة: {'فعال ✅' if active else 'متوقف ⏸'}\n"
        f"عمولة الإدارة: {provider.management_percent}%\n"
        f"خطة التقارير: {provider.report_plan}\n"
        f"التواصل: @{safe(provider.contact_username)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.regexp(r"^admin:provider:\d+$"))
async def provider_details(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    provider = await session.get(Provider, int((callback.data or "").split(":")[2]))
    if not provider:
        await edit_or_send(callback.message, "المنصة غير موجودة.")
        return
    await _render_admin_provider(callback.message, provider)


@router.callback_query(F.data.startswith("admin:provider_toggle:"))
async def provider_toggle(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    provider = await session.get(Provider, int((callback.data or "").split(":")[2]))
    if not provider:
        await edit_or_send(callback.message, "المنصة غير موجودة.")
        return
    activating = not (
        provider.status == ProviderStatus.ACTIVE.value and provider.is_active
    )
    if activating and not services.branding.has_logo(provider):
        await edit_or_send(
            callback.message,
            "🖼 لا يمكن تفعيل المنصة قبل رفع شعارها وربطه بالتقارير.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🖼 رفع الشعار الآن",
                            callback_data=f"admin:provider_logo:{provider.id}",
                            style="success",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="↩️ المنصة",
                            callback_data=f"admin:provider:{provider.id}",
                        )
                    ],
                ]
            ),
        )
        return
    provider.status = (
        ProviderStatus.ACTIVE.value if activating else ProviderStatus.PAUSED.value
    )
    provider.is_active = provider.status == ProviderStatus.ACTIVE.value
    await session.flush()
    mark_platform_authorization_dirty(session, provider_id=provider.id)
    await _render_admin_provider(callback.message, provider)


@router.callback_query(F.data.startswith("admin:provider_plan:"))
async def provider_plan(callback: CallbackQuery, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    pid = callback.data.split(":")[2]
    await edit_or_send(callback.message, 
        "اختر خطة التقارير:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="مجاني", callback_data=f"admin:set_plan:{pid}:free")],
                [
                    InlineKeyboardButton(
                        text="Lite — 2,000 د.ع",
                        callback_data=f"admin:set_plan:{pid}:lite",
                        style="primary",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Pro", callback_data=f"admin:set_plan:{pid}:pro", style="success"
                    )
                ],
            ]
        ),
    )


@router.callback_query(F.data.startswith("admin:set_plan:"))
async def provider_set_plan(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    _, _, pid, plan = (callback.data or "").split(":", 3)
    if plan not in {x.value for x in ReportPlan}:
        await edit_or_send(callback.message, "خطة غير صحيحة.")
        return
    provider = await session.get(Provider, int(pid))
    if not provider:
        await edit_or_send(callback.message, "المنصة غير موجودة.")
        return
    provider.report_plan = plan
    await session.flush()
    await _render_admin_provider(callback.message, provider)


@router.callback_query(F.data.startswith("admin:provider_logo:"))
async def provider_logo_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    try:
        provider_id = int((callback.data or "").rsplit(":", 1)[-1])
    except (TypeError, ValueError):
        await edit_or_send(callback.message, "معرف المنصة غير صالح.")
        return
    provider = await session.get(Provider, provider_id)
    if not provider:
        await edit_or_send(callback.message, "المنصة غير موجودة.")
        return
    await state.clear()
    text = (
        "🖼 <b>شعار المنصة</b>\n\n"
        "JPG/PNG/WebP — حد أقصى 8MB — حد أدنى 128×128 — ويفضل 1:1."
    )
    rows = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🖼 رفع شعار" if not provider.logo_file_id else "🖼 تغيير الشعار",
                    callback_data=f"admin:provider_logo_upload:{provider.id}",
                    style="success",
                )
            ],
            [InlineKeyboardButton(text="↩️ المنصة", callback_data=f"admin:provider:{provider.id}")],
        ]
    )
    if provider.logo_file_id:
        sent = await callback.message.answer_photo(
            provider.logo_file_id,
            caption=text + "\n\nالشعار الحالي محفوظ ✅",
            reply_markup=rows,
        )
        if sent.message_id != callback.message.message_id:
            from app.bot.ui import delete_safely

            await delete_safely(callback.message)
        return
    await edit_or_send(
        callback.message,
        text + "\n\nلا يوجد شعار محفوظ حاليًا.",
        reply_markup=rows,
    )


@router.callback_query(F.data.startswith("admin:provider_logo_upload:"))
async def provider_logo_upload_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    try:
        provider_id = int((callback.data or "").rsplit(":", 1)[-1])
    except (TypeError, ValueError):
        await edit_or_send(callback.message, "معرف المنصة غير صالح.")
        return
    provider = await session.get(Provider, provider_id)
    if not provider:
        await edit_or_send(callback.message, "المنصة غير موجودة.")
        return
    await state.clear()
    await state.update_data(
        provider_logo_id=provider.id,
        logo_required=provider.status == ProviderStatus.PENDING.value,
    )
    await state.set_state(AdminProviderLogoStates.logo)
    await edit_or_send(
        callback.message,
        "أرسل صورة الشعار داخل تيليجرام. سيبقى الشعار الحالي محفوظًا حتى تؤكد البديل.",
    )


@router.message(AdminProviderLogoStates.logo)
async def provider_logo_preview(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    data = await state.get_data()
    provider = await session.get(Provider, int(data.get("provider_logo_id") or 0))
    if not provider:
        await state.clear()
        await message.answer("المنصة غير موجودة.")
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
        }
    )
    await state.set_state(AdminProviderLogoStates.confirm)
    warning = f"\n⚠️ {candidate.warning}" if candidate.warning else ""
    await message.answer_photo(
        candidate.file_id,
        caption=(
            "🔎 <b>معاينة الشعار الجديد</b>\n"
            f"الصيغة: {candidate.image_format} — الأبعاد: {candidate.width}×{candidate.height}"
            f"{warning}\n\nلن يُحفظ قبل التأكيد."
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ تأكيد",
                        callback_data="admin:provider_logo_confirm",
                        style="success",
                    ),
                    InlineKeyboardButton(
                        text="❌ إلغاء",
                        callback_data="admin:provider_logo_cancel",
                        style="danger",
                    ),
                ]
            ]
        ),
    )


@router.callback_query(F.data == "admin:provider_logo_confirm")
async def provider_logo_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    if await state.get_state() != AdminProviderLogoStates.confirm.state:
        await callback_notice(callback, "المعاينة قديمة؛ ارفع الصورة من جديد", show_alert=True)
        return
    data = await state.get_data()
    provider = await session.get(Provider, int(data.get("provider_logo_id") or 0))
    if not provider:
        await state.clear()
        await edit_or_send(callback.message, "المنصة غير موجودة.")
        return
    try:
        candidate = BrandingCandidate(**(data.get("branding_candidate") or {}))
    except (TypeError, ValueError):
        await edit_or_send(callback.message, "بيانات المعاينة غير مكتملة.")
        return
    await services.branding.save_candidate(session, provider, candidate)
    activated = provider.status == ProviderStatus.PENDING.value
    if activated:
        provider.status = ProviderStatus.ACTIVE.value
        provider.is_active = True
        await session.flush()
        mark_platform_authorization_dirty(session, provider_id=provider.id)
    await state.clear()
    await edit_or_send(
        callback.message,
        "تم حفظ الشعار وربطه بالتقارير وتفعيل المنصة ✅"
        if activated
        else "تم تغيير الشعار وربطه بالتقارير ✅",
        reply_markup=admin_back(),
    )


@router.callback_query(F.data == "admin:provider_logo_cancel")
async def provider_logo_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    data = await state.get_data()
    provider_id = int(data.get("provider_logo_id") or 0)
    required = bool(data.get("logo_required"))
    await state.clear()
    await edit_or_send(
        callback.message,
        "تم إلغاء تغيير الشعار. بقيت المنصة مسودة ولن تُفعّل قبل رفع شعار."
        if required
        else "تم إلغاء تغيير الشعار، وبقي الشعار السابق محفوظًا.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="↩️ المنصة", callback_data=f"admin:provider:{provider_id}"
                    )
                ]
            ]
        ),
    )


# ---------------- Categories ----------------
async def _render_admin_categories(message: Message, session: AsyncSession) -> None:
    cats = list((await session.scalars(select(Category).order_by(Category.sort_order, Category.id))).all())
    rows: list[list[InlineKeyboardButton]] = [[
        InlineKeyboardButton(text="➕ إضافة فئة", callback_data="admin:category_add", style="success")
    ]]
    for category in cats:
        icon = "✅" if category.is_active else "❌"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {category.emoji} {category.name}",
            callback_data=f"admin:category_toggle:{category.id}",
            style="success" if category.is_active else "danger",
        )])
    rows.append([InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")])
    await edit_or_send(message, "📂 <b>فئات الخدمات</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "admin:categories")
async def categories_list(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await _render_admin_categories(callback.message, session)


@router.callback_query(F.data == "admin:category_add")
async def category_add(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.set_state(AdminCategoryStates.name)
    await edit_or_send(callback.message, "اكتب اسم الفئة:")


@router.message(AdminCategoryStates.name)
async def category_name(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    value = " ".join((message.text or "").split())[:120]
    if len(value) < 2:
        return await message.answer("اكتب اسمًا واضحًا.")
    if await session.scalar(select(Category.id).where(Category.name == value)):
        return await message.answer("هذه الفئة موجودة.")
    session.add(Category(name=value, emoji=smart_emoji(value)))
    await session.flush()
    await state.clear()
    await message.answer("تمت إضافة الفئة بالإيموجي المناسب تلقائيًا ✅", reply_markup=admin_back())


@router.message(AdminCategoryStates.emoji)
async def category_emoji_legacy(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Finish FSM sessions that were already waiting for a manual emoji."""
    data = await state.get_data()
    name = str(data.get("category_name") or "فئة جديدة")[:120]
    if not await session.scalar(select(Category.id).where(Category.name == name)):
        session.add(Category(name=name, emoji=smart_emoji(name)))
        await session.flush()
    await state.clear()
    await message.answer("تم إكمال الخطوة تلقائيًا ✅", reply_markup=admin_back())


@router.callback_query(F.data.startswith("admin:category_toggle:"))
async def category_toggle(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    row = await session.get(Category, int((callback.data or "").split(":")[2]))
    if not row:
        await edit_or_send(callback.message, "الفئة غير موجودة.")
        return
    row.is_active = not row.is_active
    await session.flush()
    await _render_admin_categories(callback.message, session)


# ---------------- Offers ----------------

@router.callback_query(F.data == "admin:offers")
async def offers_list(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    offers = list(
        (await session.scalars(select(Offer).order_by(Offer.created_at.desc()).limit(50))).all()
    )
    items = [
        ("➕ إضافة عرض", "admin:offer_add", "success"),
        ("📂 إدارة الفئات", "admin:categories", "primary"),
        ("💳 طرق الدفع", "admin:payment_methods", "primary"),
    ]
    items.extend((f"{o.title} — {o.status}", f"admin:offer:{o.id}", "primary") for o in offers)
    await edit_or_send(callback.message, "🛍 <b>العروض</b>", reply_markup=_rows(items))


@router.callback_query(F.data == "admin:offer_add")
async def offer_add_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    """V5 uses the same safe offer wizard for owner and platform staff.

    This removes duplicated questions and guarantees price confirmation, owner-controlled
    fees, activation mode and mandatory visual instructions.
    """
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    providers = list(
        (
            await session.scalars(
                select(Provider).where(Provider.is_active.is_(True)).order_by(Provider.name_ar)
            )
        ).all()
    )
    if not providers:
        await edit_or_send(callback.message, "أضف منصة أولًا.")
        return
    await edit_or_send(callback.message, 
        "اختر المنصة، ثم اضغط «🛍 متجري والعروض» وبعدها «➕ إضافة عرض».\n\n"
        "يستخدم المالك والمنصة نفس معالج v5 حتى لا تختلف الأسعار أو التعليمات:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"🏢 {provider.name_ar}",
                        callback_data=f"provider:select:{provider.id}",
                        style="primary",
                    )
                ]
                for provider in providers
            ]
            + [[InlineKeyboardButton(text="↩️ العروض", callback_data="admin:offers")]]
        ),
    )


@router.message(AdminOfferStates.provider_id)
async def offer_provider(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    try:
        pid = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب ID بالأرقام.")
    provider = await session.get(Provider, pid)
    if not provider:
        return await message.answer("المنصة غير موجودة.")
    await services.catalog.create_default_provider_catalog(session, provider)
    service_items = list(
        (
            await session.scalars(
                select(CatalogServiceItem)
                .where(
                    CatalogServiceItem.provider_id == pid,
                    CatalogServiceItem.is_active.is_(True),
                )
                .order_by(CatalogServiceItem.section_id, CatalogServiceItem.sort_order)
            )
        ).all()
    )
    if not service_items:
        await state.clear()
        return await message.answer(
            "لا توجد خدمات داخل المنصة. أضف خدمة من: المنصات ← الأقسام والخدمات.\n"
            f"معرف المنصة: <code>{pid}</code>"
        )
    await state.update_data(offer_provider_id=pid)
    await state.set_state(AdminOfferStates.service_id)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{item.emoji} {item.name}",
                    callback_data=f"admin:offer_pick_service:{item.id}",
                    style="primary",
                )
            ]
            for item in service_items
        ]
    )
    await message.answer("اختر الخدمة التي سيظهر العرض داخلها:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("admin:offer_pick_service:"))
async def offer_pick_service(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    data = await state.get_data()
    if await state.get_state() != AdminOfferStates.service_id:
        await edit_or_send(callback.message, "ابدأ إضافة العرض من جديد.")
        return
    service_id = int((callback.data or "").split(":")[2])
    item = await session.get(CatalogServiceItem, service_id)
    if not item or item.provider_id != int(data["offer_provider_id"]):
        await edit_or_send(callback.message, "الخدمة لا تخص هذه المنصة.")
        return
    section = await session.get(CatalogSection, item.section_id)
    category = await session.scalar(select(Category).where(Category.name == section.name))
    if not category:
        category = Category(name=section.name, emoji=section.emoji, is_active=True)
        session.add(category)
        await session.flush()
    await state.update_data(
        offer_service_id=item.id,
        offer_category_id=category.id,
    )
    await state.set_state(AdminOfferStates.title)
    await edit_or_send(callback.message, f"اكتب اسم العرض داخل خدمة {item.emoji} {safe(item.name)}:")


@router.message(AdminOfferStates.service_id)
async def offer_service_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        service_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("اختر الخدمة من الأزرار أو اكتب ID صحيحًا.")
        return
    data = await state.get_data()
    item = await session.get(CatalogServiceItem, service_id)
    if not item or item.provider_id != int(data["offer_provider_id"]):
        await message.answer("الخدمة لا تخص هذه المنصة.")
        return
    section = await session.get(CatalogSection, item.section_id)
    category = await session.scalar(select(Category).where(Category.name == section.name))
    if not category:
        category = Category(name=section.name, emoji=section.emoji, is_active=True)
        session.add(category)
        await session.flush()
    await state.update_data(offer_service_id=item.id, offer_category_id=category.id)
    await state.set_state(AdminOfferStates.title)
    await message.answer("اكتب اسم العرض:")


@router.message(AdminOfferStates.title)
async def offer_title(message: Message, state: FSMContext) -> None:
    value = " ".join((message.text or "").split())
    if len(value) < 3:
        return await message.answer("اكتب اسمًا أوضح.")
    await state.update_data(offer_title=value[:220])
    await state.set_state(AdminOfferStates.description)
    await message.answer("اكتب وصف العرض:")


@router.message(AdminOfferStates.description)
async def offer_description(message: Message, state: FSMContext) -> None:
    await state.update_data(offer_description=(message.text or "").strip()[:4000])
    await state.set_state(AdminOfferStates.price)
    await message.answer("اكتب سعر الاشتراك بالدينار:")


@router.message(AdminOfferStates.price)
async def offer_price(message: Message, state: FSMContext) -> None:
    amount = parse_money(message.text or "")
    if not amount:
        return await message.answer("اكتب سعرًا صحيحًا.")
    await state.update_data(offer_price=amount)
    await state.set_state(AdminOfferStates.service_fee)
    await message.answer("اكتب رسوم البوت، مثال 500:")


@router.message(AdminOfferStates.service_fee)
async def offer_fee(message: Message, state: FSMContext) -> None:
    amount = parse_money(message.text or "")
    if amount is None:
        return await message.answer("اكتب الرسوم بالأرقام.")
    await state.update_data(offer_fee=amount)
    await state.set_state(AdminOfferStates.delivery_type)
    await message.answer(
        "اكتب نوع التسليم:\ninventory_code\ninventory_account\nemail_code\nstudent_email_invite\nmanual\nfile_service"
    )


@router.message(AdminOfferStates.delivery_type)
async def offer_delivery(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip().lower()
    if value not in {x.value for x in DeliveryType}:
        return await message.answer("نوع التسليم غير صحيح.")
    await state.update_data(offer_delivery=value)
    await state.set_state(AdminOfferStates.activation_fields)
    await message.answer("اكتب حقول التفعيل مفصولة بفاصلة، مثال: email,username\nأو اكتب -")


@router.message(AdminOfferStates.activation_fields)
async def offer_fields(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    fields = (
        []
        if raw == "-"
        else [
            {
                "key": x.strip().lower(),
                "label": x.strip(),
                "type": "email" if "mail" in x.lower() else "text",
                "required": True,
            }
            for x in raw.split(",")
            if x.strip()
        ]
    )
    await state.update_data(offer_fields=fields)
    await state.set_state(AdminOfferStates.daily_limit)
    await message.answer("اكتب الحد اليومي أو 0 بدون حد:")


@router.message(AdminOfferStates.daily_limit)
async def offer_daily_limit(message: Message, state: FSMContext) -> None:
    try:
        limit = int((message.text or "0").strip())
    except ValueError:
        return await message.answer("اكتب رقمًا صحيحًا.")
    if limit < 0:
        return await message.answer("الحد لا يمكن أن يكون سالبًا.")
    await state.update_data(offer_daily_limit=limit or None)
    await state.set_state(AdminOfferStates.validity_type)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏳ بالأيام (مثلاً: 7 أيام)",
                    callback_data="admin:validity_pick:days_from_activation",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗓 بالأشهر (مثلاً: شهر واحد)",
                    callback_data="admin:validity_pick:months_from_activation",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 تاريخ نهاية ثابت",
                    callback_data="admin:validity_pick:fixed_offer_end",
                    style="danger",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 حسب تاريخ الحساب في المخزون",
                    callback_data="admin:validity_pick:inventory_end",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✍️ يحدد يدويًا عند التسليم",
                    callback_data="admin:validity_pick:manual",
                )
            ],
        ]
    )
    await message.answer("كيف تُحسب مدة الاشتراك؟", reply_markup=keyboard)


async def _ask_offer_start_trigger(
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

    await state.set_state(AdminOfferStates.start_trigger)
    await render(
        "متى يبدأ الاشتراك؟",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="بعد قبول الدفع",
                        callback_data="admin:start_trigger:payment_approved",
                        style="primary",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="عند إرسال بيانات الاشتراك",
                        callback_data="admin:start_trigger:delivery",
                        style="success",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="بعد تأكيد المستخدم نجاح التفعيل",
                        callback_data="admin:start_trigger:user_activated",
                        style="success",
                    )
                ],
            ]
        ),
    )


@router.callback_query(F.data.startswith("admin:validity_pick:"))
async def offer_validity_pick(
    callback: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    if await state.get_state() != AdminOfferStates.validity_type:
        await edit_or_send(callback.message, "ابدأ إضافة العرض من جديد.")
        return
    validity_type = (callback.data or "").split(":")[2]
    allowed = {x.value for x in ValidityType}
    if validity_type not in allowed:
        return
    await state.update_data(offer_validity_type=validity_type)
    if validity_type == ValidityType.DAYS_FROM_ACTIVATION.value:
        await state.set_state(AdminOfferStates.validity_value)
        await edit_or_send(callback.message, "اكتب عدد الأيام، مثال: 30")
        return
    if validity_type == ValidityType.MONTHS_FROM_ACTIVATION.value:
        await state.set_state(AdminOfferStates.validity_value)
        await edit_or_send(callback.message, "اكتب عدد الأشهر، مثال: 1")
        return
    if validity_type == ValidityType.FIXED_OFFER_END.value:
        await state.set_state(AdminOfferStates.validity_value)
        await edit_or_send(callback.message, "اكتب تاريخ الانتهاء الثابت YYYY-MM-DD")
        return
    await state.update_data(offer_validity_value=None, offer_fixed_end_at=None)
    await _ask_offer_start_trigger(callback.message, state, in_place=True)


@router.message(AdminOfferStates.validity_value)
async def offer_validity_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    validity_type = data["offer_validity_type"]
    raw = (message.text or "").strip()
    if validity_type in {
        ValidityType.DAYS_FROM_ACTIVATION.value,
        ValidityType.MONTHS_FROM_ACTIVATION.value,
    }:
        try:
            value = int(raw)
        except ValueError:
            return await message.answer("اكتب رقمًا صحيحًا.")
        if value < 1 or value > 3650:
            return await message.answer("القيمة يجب أن تكون بين 1 و3650.")
        await state.update_data(offer_validity_value=value, offer_fixed_end_at=None)
    else:
        try:
            fixed_end = datetime.strptime(raw, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=UTC
            )
        except ValueError:
            return await message.answer("صيغة التاريخ غير صحيحة. مثال: 2026-09-30")
        if fixed_end <= datetime.now(UTC):
            return await message.answer("تاريخ الانتهاء يجب أن يكون في المستقبل.")
        await state.update_data(offer_validity_value=None, offer_fixed_end_at=fixed_end)
    await _ask_offer_start_trigger(message, state)


@router.callback_query(F.data.startswith("admin:start_trigger:"))
async def offer_start_trigger(
    callback: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    if await state.get_state() != AdminOfferStates.start_trigger:
        await edit_or_send(callback.message, "ابدأ إضافة العرض من جديد.")
        return
    trigger = (callback.data or "").split(":")[2]
    if trigger not in {x.value for x in SubscriptionStartTrigger}:
        return
    await state.update_data(offer_start_trigger=trigger)
    await state.set_state(AdminOfferStates.warranty_hours)
    await edit_or_send(callback.message, "اكتب مدة ضمان التفعيل بالساعات، مثال: 24")


@router.message(AdminOfferStates.warranty_hours)
async def offer_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    try:
        warranty_hours = int((message.text or "24").strip())
    except ValueError:
        return await message.answer("اكتب عدد الساعات بالأرقام.")
    if warranty_hours < 1 or warranty_hours > 720:
        return await message.answer("مدة الضمان يجب أن تكون بين ساعة و720 ساعة.")
    data = await state.get_data()
    provider_id = int(data["offer_provider_id"])
    if not await services.subscriptions.feature_enabled(session, provider_id, "offers.manage"):
        return await message.answer("إدارة العروض غير متاحة في باقة هذه المنصة.")
    current_count = int(
        await session.scalar(
            select(func.count()).select_from(Offer).where(Offer.provider_id == provider_id)
        )
        or 0
    )
    try:
        await services.subscriptions.assert_within_limit(
            session, provider_id, "offers.max", current_count
        )
    except ValueError as exc:
        return await message.answer(str(exc))
    offer = Offer(
        provider_id=provider_id,
        category_id=int(data["offer_category_id"]),
        title=data["offer_title"],
        description=data["offer_description"],
        price_iqd=data["offer_price"],
        service_fee_iqd=data["offer_fee"],
        delivery_type=data["offer_delivery"],
        activation_fields=data["offer_fields"],
        daily_limit=data.get("offer_daily_limit"),
        duration_days=(
            int(data["offer_validity_value"])
            if data["offer_validity_type"] == ValidityType.DAYS_FROM_ACTIVATION.value
            else None
        ),
        status=(
            OfferStatus.OUT_OF_STOCK.value
            if data["offer_delivery"]
            in {DeliveryType.INVENTORY_ACCOUNT.value, DeliveryType.INVENTORY_CODE.value}
            else OfferStatus.ACTIVE.value
        ),
        is_active=(
            data["offer_delivery"]
            not in {DeliveryType.INVENTORY_ACCOUNT.value, DeliveryType.INVENTORY_CODE.value}
        ),
    )
    session.add(offer)
    await session.flush()
    service = await session.get(CatalogServiceItem, int(data["offer_service_id"]))
    if not service or service.provider_id != provider_id:
        await state.clear()
        return await message.answer("الخدمة المختارة لم تعد موجودة.")
    session.add(
        OfferCatalogPlacement(
            offer_id=offer.id,
            provider_id=provider_id,
            section_id=service.section_id,
            service_id=service.id,
        )
    )
    session.add(
        OfferValidityPolicy(
            offer_id=offer.id,
            validity_type=data["offer_validity_type"],
            duration_value=data.get("offer_validity_value"),
            fixed_end_at=data.get("offer_fixed_end_at"),
            start_trigger=data["offer_start_trigger"],
            warranty_hours=warranty_hours,
            objection_hours=warranty_hours,
        )
    )
    actor = await admin_actor(session, services, message)
    await services.audit.log(
        session, actor, "offer.created", "offer", str(offer.id), {"title": offer.title}
    )
    await services.offer_lifecycle.queue_launch_announcement(
        session, offer, actor.id if actor else None
    )
    await state.clear()
    await message.answer(
        f"تم إنشاء العرض ID <code>{offer.id}</code> داخل الخدمة {safe(service.name)} ✅",
        reply_markup=admin_back(),
    )


async def _render_admin_offer(message: Message, offer: Offer) -> None:
    active = offer.status == OfferStatus.ACTIVE.value and offer.is_active
    rows = [
        [InlineKeyboardButton(
            text="⏸ إيقاف العرض" if active else "▶️ تشغيل العرض",
            callback_data=f"admin:offer_toggle:{offer.id}",
            style="danger" if active else "success",
        )],
        [InlineKeyboardButton(text="🖼 تغيير صورة العرض", callback_data=f"admin:offer_image:{offer.id}", style="success")],
        [InlineKeyboardButton(text="🔑 إضافة مخزون", callback_data=f"admin:inventory_add:{offer.id}")],
        [InlineKeyboardButton(text="📧 إضافة إيميل", callback_data=f"admin:email_add:{offer.id}")],
        [InlineKeyboardButton(text="↩️ العروض", callback_data="admin:offers")],
    ]
    await edit_or_send(
        message,
        f"🛍 <b>{safe(offer.title)}</b>\n"
        f"ID: <code>{offer.id}</code>\n"
        f"السعر: {offer.price_iqd:,}\n"
        f"الرسوم: {offer.service_fee_iqd:,}\n"
        f"التسليم: {offer.delivery_type}\n"
        f"الحالة: {'فعال ✅' if active else 'متوقف ⏸'}\n"
        f"المباع اليوم: {offer.sold_today}/{offer.daily_limit or '∞'}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.regexp(r"^admin:offer:\d+$"))
async def offer_details(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    offer = await session.get(Offer, int((callback.data or "").split(":")[2]))
    if not offer:
        await edit_or_send(callback.message, "العرض غير موجود.")
        return
    await _render_admin_offer(callback.message, offer)


@router.callback_query(F.data.startswith("admin:offer_toggle:"))
async def offer_toggle(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    offer = await session.get(Offer, int((callback.data or "").split(":")[2]))
    if not offer:
        await edit_or_send(callback.message, "العرض غير موجود.")
        return
    offer.status = (
        OfferStatus.PAUSED.value
        if offer.status == OfferStatus.ACTIVE.value and offer.is_active
        else OfferStatus.ACTIVE.value
    )
    offer.is_active = offer.status == OfferStatus.ACTIVE.value
    if offer.is_active and callback.from_user:
        actor = await services.users.get(session, callback.from_user.id)
        await services.offer_lifecycle.queue_launch_announcement(
            session, offer, actor.id if actor else None
        )
    await session.flush()
    await _render_admin_offer(callback.message, offer)


@router.callback_query(F.data.startswith("admin:offer_image:"))
async def offer_image_start(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.update_data(offer_image_id=int(callback.data.split(":")[2]))
    await state.set_state(AdminOfferImageStates.image)
    await edit_or_send(callback.message, "أرسل صورة العرض:")


@router.message(AdminOfferImageStates.image, F.photo)
async def offer_image_save(
    message: Message, state: FSMContext, session: AsyncSession, settings: Settings
) -> None:
    if not await require_admin(message, settings):
        return
    data = await state.get_data()
    offer = await session.get(Offer, int(data["offer_image_id"]))
    if offer:
        offer.image_file_id = message.photo[-1].file_id
    await state.clear()
    await message.answer("تم تحديث صورة العرض ✅", reply_markup=admin_back())


# ---------------- Payment methods ----------------
async def _render_admin_payment_methods(message: Message, session: AsyncSession) -> None:
    methods = list((await session.scalars(
        select(PaymentMethod).order_by(PaymentMethod.provider_id, PaymentMethod.sort_order)
    )).all())
    rows: list[list[InlineKeyboardButton]] = [[
        InlineKeyboardButton(text="➕ إضافة طريقة دفع", callback_data="admin:payment_method_add", style="success")
    ]]
    for method in methods:
        icon = "✅" if method.is_active else "❌"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {method.icon} {method.name} — منصة {method.provider_id or 'عامة'}",
            callback_data=f"admin:payment_method_toggle:{method.id}",
            style="success" if method.is_active else "danger",
        )])
    rows.append([InlineKeyboardButton(text="↩️ العروض", callback_data="admin:offers")])
    await edit_or_send(message, "💳 <b>طرق الدفع</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "admin:payment_methods")
async def payment_methods(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await _render_admin_payment_methods(callback.message, session)


@router.callback_query(F.data == "admin:payment_method_add")
async def payment_method_start(
    callback: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.set_state(AdminPaymentMethodStates.provider_id)
    await edit_or_send(callback.message, "اكتب ID المنصة، أو 0 لتكون طريقة عامة:")


@router.message(AdminPaymentMethodStates.provider_id)
async def pm_provider(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        pid = int((message.text or "0").strip())
    except ValueError:
        return await message.answer("اكتب رقمًا.")
    if pid and not await session.get(Provider, pid):
        return await message.answer("المنصة غير موجودة.")
    await state.update_data(pm_provider_id=pid or None)
    await state.set_state(AdminPaymentMethodStates.name)
    await message.answer("اكتب اسم طريقة الدفع، مثال: زين كاش")


@router.message(AdminPaymentMethodStates.name)
async def pm_name(message: Message, state: FSMContext) -> None:
    await state.update_data(pm_name=(message.text or "").strip()[:120])
    await state.set_state(AdminPaymentMethodStates.method_type)
    await message.answer("اكتب النوع: manual أو mastercard")


@router.message(AdminPaymentMethodStates.method_type)
async def pm_type(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip().lower()
    if value not in {"manual", "mastercard"}:
        return await message.answer("اكتب manual أو mastercard")
    await state.update_data(pm_type=value)
    await state.set_state(AdminPaymentMethodStates.recipient)
    await message.answer("اكتب رقم أو حساب المستلم، أو - للبطاقة الإلكترونية:")


@router.message(AdminPaymentMethodStates.recipient)
async def pm_recipient(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    await state.update_data(pm_recipient="" if value == "-" else value[:255])
    await state.set_state(AdminPaymentMethodStates.instructions)
    await message.answer("اكتب تعليمات الدفع:")


@router.message(AdminPaymentMethodStates.instructions)
async def pm_finish(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    session.add(
        PaymentMethod(
            provider_id=data["pm_provider_id"],
            name=data["pm_name"],
            method_type=data["pm_type"],
            recipient=data["pm_recipient"],
            instructions=(message.text or "").strip()[:2000],
            icon="💳" if data["pm_type"] == "mastercard" else "💰",
        )
    )
    await state.clear()
    await message.answer("تمت إضافة طريقة الدفع ✅", reply_markup=admin_back())


@router.callback_query(F.data.startswith("admin:payment_method_toggle:"))
async def pm_toggle(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    row = await session.get(PaymentMethod, int((callback.data or "").split(":")[2]))
    if not row:
        await edit_or_send(callback.message, "طريقة الدفع غير موجودة.")
        return
    row.is_active = not row.is_active
    await session.flush()
    await _render_admin_payment_methods(callback.message, session)


# ---------------- Email accounts ----------------

@router.callback_query(F.data == "admin:emails")
async def emails_list(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    accounts = list(
        (
            await session.scalars(select(EmailAccount).order_by(EmailAccount.id.desc()).limit(50))
        ).all()
    )
    lines = ["📧 <b>الإيميلات</b>"]
    for a in accounts:
        lines.append(
            f"\n• ID {a.id} — {safe(a.label)} — {safe(a.username)} — {a.used_today}/{a.daily_limit} — {a.status}"
        )
    rows = [
        [
            InlineKeyboardButton(
                text="➕ إضافة إيميل", callback_data="admin:email_add:0", style="success"
            )
        ],
        [InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")],
    ]
    await edit_or_send(callback.message, 
        "".join(lines) if accounts else "لا توجد إيميلات.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("admin:email_add:"))
async def email_add_start(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    offer_id = int(callback.data.split(":")[2])
    await state.clear()
    await state.update_data(email_offer_id=offer_id or None)
    await state.set_state(AdminEmailStates.provider_id)
    await edit_or_send(callback.message, "اكتب ID المنصة:")


@router.message(AdminEmailStates.provider_id)
async def email_provider(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        pid = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب ID بالأرقام.")
    if not await session.get(Provider, pid):
        return await message.answer("المنصة غير موجودة.")
    await state.update_data(email_provider_id=pid)
    await state.set_state(AdminEmailStates.label)
    await message.answer("اكتب اسمًا داخليًا للإيميل:")


@router.message(AdminEmailStates.label)
async def email_label(message: Message, state: FSMContext) -> None:
    await state.update_data(email_label=(message.text or "").strip()[:120])
    await state.set_state(AdminEmailStates.host)
    await message.answer("اكتب IMAP Host، مثال: imap.gmail.com أو imap.mail.yahoo.com")


@router.message(AdminEmailStates.host)
async def email_host(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if "." not in value:
        return await message.answer("Host غير صحيح.")
    await state.update_data(email_host=value[:255])
    await state.set_state(AdminEmailStates.port)
    await message.answer("اكتب المنفذ، غالبًا 993")


@router.message(AdminEmailStates.port)
async def email_port(message: Message, state: FSMContext) -> None:
    try:
        port = int((message.text or "993").strip())
    except ValueError:
        return await message.answer("اكتب رقم المنفذ.")
    await state.update_data(email_port=port)
    await state.set_state(AdminEmailStates.username)
    await message.answer("اكتب عنوان الإيميل:")


@router.message(AdminEmailStates.username)
async def email_username(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip().lower()
    if "@" not in value:
        return await message.answer("الإيميل غير صحيح.")
    await state.update_data(email_username=value[:255])
    await state.set_state(AdminEmailStates.secret)
    await message.answer("أرسل App Password الخاص بالتطبيق. لا ترسل كلمة المرور الرئيسية.")


@router.message(AdminEmailStates.secret)
async def email_secret(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if len(value) < 6:
        return await message.answer("السر قصير جدًا.")
    await state.update_data(email_secret=value)
    await state.set_state(AdminEmailStates.sender_filter)
    await message.answer("اكتب مرسل الخدمة المطلوب، أو -")


@router.message(AdminEmailStates.sender_filter)
async def email_sender(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    await state.update_data(email_sender=None if value == "-" else value[:255])
    await state.set_state(AdminEmailStates.subject_regex)
    await message.answer("اكتب تعبير عنوان الرسالة Regex، أو -")


@router.message(AdminEmailStates.subject_regex)
async def email_subject(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    await state.update_data(email_subject=None if value == "-" else value[:500])
    await state.set_state(AdminEmailStates.code_regex)
    await message.answer(r"اكتب Regex الكود، أو - لاستخدام \b(\d{4,8})\b")


@router.message(AdminEmailStates.code_regex)
async def email_regex(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    await state.update_data(email_regex=r"\b(\d{4,8})\b" if value == "-" else value[:500])
    await state.set_state(AdminEmailStates.daily_limit)
    await message.answer("اكتب الحد اليومي:")


@router.message(AdminEmailStates.daily_limit)
async def email_limit(message: Message, state: FSMContext) -> None:
    try:
        limit = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب رقمًا.")
    if limit < 1:
        return await message.answer("الحد يجب أن يكون 1 أو أكثر.")
    await state.update_data(email_limit=limit)
    await state.set_state(AdminEmailStates.valid_until)
    await message.answer("اكتب تاريخ الانتهاء YYYY-MM-DD أو - بدون انتهاء:")


@router.message(AdminEmailStates.valid_until)
async def email_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    raw = (message.text or "").strip()
    valid_until = None
    if raw != "-":
        try:
            valid_until = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return await message.answer("صيغة التاريخ غير صحيحة.")
    data = await state.get_data()
    provider_id = int(data["email_provider_id"])
    if not await services.subscriptions.feature_enabled(session, provider_id, "emails.manage"):
        return await message.answer("إدارة الإيميلات غير متاحة في باقة هذه المنصة.")
    current_count = int(
        await session.scalar(
            select(func.count())
            .select_from(EmailAccount)
            .where(EmailAccount.provider_id == provider_id)
        )
        or 0
    )
    try:
        await services.subscriptions.assert_within_limit(
            session, provider_id, "emails.max", current_count
        )
    except ValueError as exc:
        return await message.answer(str(exc))
    account = EmailAccount(
        provider_id=data["email_provider_id"],
        offer_id=data.get("email_offer_id"),
        label=data["email_label"],
        imap_host=data["email_host"],
        imap_port=data["email_port"],
        username=data["email_username"],
        encrypted_secret=services.fulfillment.secrets.encrypt(data["email_secret"]),
        sender_filter=data["email_sender"],
        subject_regex=data["email_subject"],
        code_regex=data["email_regex"],
        daily_limit=data["email_limit"],
        valid_until=valid_until,
        status=EmailAccountStatus.AVAILABLE.value,
    )
    session.add(account)
    await state.clear()
    await message.answer("تمت إضافة الإيميل وتشفير App Password ✅", reply_markup=admin_back())


# ---------------- Inventory ----------------
@router.callback_query(F.data == "admin:inventory")
async def inventory_list(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    items = list(
        (
            await session.scalars(select(InventoryItem).order_by(InventoryItem.id.desc()).limit(30))
        ).all()
    )
    lines = ["🔑 <b>آخر عناصر المخزون</b>"]
    for item in items:
        lines.append(f"\n• ID {item.id} — عرض {item.offer_id} — {item.item_kind} — {item.status}")
    rows = [
        [
            InlineKeyboardButton(
                text="➕ إضافة عنصر", callback_data="admin:inventory_add:0", style="success"
            )
        ],
        [InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")],
    ]
    await edit_or_send(callback.message, 
        "".join(lines) if items else "المخزون فارغ.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("admin:inventory_add:"))
async def inventory_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    oid = int((callback.data or "").split(":")[2])
    await callback_notice(callback, "جاري التحقق من صلاحية المخزون...")
    await state.clear()
    if oid:
        offer = await session.get(Offer, oid)
        if not offer:
            await edit_or_send(callback.message, "العرض غير موجود.")
            return
        if not await services.subscriptions.feature_enabled(
            session, offer.provider_id, "inventory.manage"
        ):
            await edit_or_send(callback.message, 
                "إدارة المخزون غير متاحة في باقة هذه المنصة. لم يتم بدء عملية الإدخال."
            )
            return
    await state.update_data(inventory_offer_id=oid or None)
    if oid:
        await state.set_state(AdminInventoryStates.item_kind)
        await edit_or_send(callback.message, "اكتب النوع: code أو account")
    else:
        await state.set_state(AdminInventoryStates.offer_id)
        await edit_or_send(callback.message, "اكتب ID العرض:")


@router.message(AdminInventoryStates.offer_id)
async def inventory_offer(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    try:
        oid = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب ID بالأرقام.")
    offer = await session.get(Offer, oid)
    if not offer:
        return await message.answer("العرض غير موجود.")
    if not await services.subscriptions.feature_enabled(
        session, offer.provider_id, "inventory.manage"
    ):
        await state.clear()
        return await message.answer("إدارة المخزون غير متاحة في باقة هذه المنصة.")
    await state.update_data(inventory_offer_id=oid)
    await state.set_state(AdminInventoryStates.item_kind)
    await message.answer("اكتب النوع: code أو account")


@router.message(AdminInventoryStates.item_kind)
async def inventory_kind(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip().lower()
    if value not in {"code", "account"}:
        return await message.answer("اكتب code أو account")
    await state.update_data(inventory_kind=value)
    await state.set_state(AdminInventoryStates.label)
    await message.answer("اكتب عنوان البيانات، مثال: كود التفعيل أو حساب Gemini")


@router.message(AdminInventoryStates.label)
async def inventory_label(message: Message, state: FSMContext) -> None:
    label = (message.text or "").strip()[:120]
    if len(label) < 2:
        return await message.answer("اكتب عنوانًا واضحًا.")
    await state.update_data(inventory_label=label)
    await state.set_state(AdminInventoryStates.payload)
    await message.answer(
        "أرسل الكود أو بيانات الحساب. سيتم تشفيرها فورًا.\n"
        "للحساب المنظم يمكن إرسال JSON مثل:\n"
        '<code>{"login_email":"x@example.com","login_password":"...","instructions":"..."}</code>'
    )


@router.message(AdminInventoryStates.payload)
async def inventory_payload(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    payload = (message.text or "").strip()
    if len(payload) < 2:
        return await message.answer("البيانات فارغة.")
    data = await state.get_data()
    offer_id = int(data["inventory_offer_id"])
    normalized = " ".join(payload.split())
    fingerprint = services.fulfillment.secrets.hash_value(
        f"{offer_id}:{data['inventory_kind']}:{normalized}"
    )
    duplicate = await session.scalar(
        select(InventoryFingerprint.id).where(
            InventoryFingerprint.offer_id == offer_id,
            InventoryFingerprint.fingerprint == fingerprint,
        )
    )
    if duplicate:
        return await message.answer("هذا الكود أو الحساب مضاف مسبقًا لهذا العرض ⚠️")
    await state.update_data(
        inventory_payload=payload,
        inventory_fingerprint=fingerprint,
    )
    await state.set_state(AdminInventoryStates.expires_at)
    await message.answer("اكتب تاريخ انتهاء الحساب YYYY-MM-DD، أو اكتب - إذا لا يوجد تاريخ ثابت:")


@router.message(AdminInventoryStates.expires_at)
async def inventory_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    raw_date = (message.text or "").strip()
    expires_at = None
    if raw_date != "-":
        try:
            expires_at = datetime.strptime(raw_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=UTC
            )
        except ValueError:
            return await message.answer("صيغة التاريخ غير صحيحة. مثال: 2026-09-30")
        if expires_at <= datetime.now(UTC):
            return await message.answer("تاريخ الانتهاء يجب أن يكون في المستقبل.")
    data = await state.get_data()
    offer = await session.get(Offer, int(data["inventory_offer_id"]))
    if not offer:
        await state.clear()
        return await message.answer("العرض غير موجود.")
    if not await services.subscriptions.feature_enabled(
        session, offer.provider_id, "inventory.manage"
    ):
        await state.clear()
        return await message.answer("إدارة المخزون غير متاحة في باقة هذه المنصة.")
    duplicate = await session.scalar(
        select(InventoryFingerprint.id).where(
            InventoryFingerprint.offer_id == offer.id,
            InventoryFingerprint.fingerprint == data["inventory_fingerprint"],
        )
    )
    if duplicate:
        await state.clear()
        return await message.answer("هذا العنصر أضيف مسبقًا ولم تتم إضافته مرة ثانية.")
    actor = await admin_actor(session, services, message)
    item = InventoryItem(
        offer_id=offer.id,
        item_kind=data["inventory_kind"],
        label=data["inventory_label"],
        encrypted_payload=services.fulfillment.secrets.encrypt(data["inventory_payload"]),
        expires_at=expires_at,
        created_by_user_id=actor.id if actor else None,
    )
    session.add(item)
    await session.flush()
    session.add(
        InventoryFingerprint(
            offer_id=offer.id,
            inventory_item_id=item.id,
            fingerprint=data["inventory_fingerprint"],
        )
    )
    if offer.status in {OfferStatus.OUT_OF_STOCK.value, OfferStatus.EXPIRED.value} and (
        offer.end_at is None or offer.end_at > datetime.now(UTC)
    ):
        offer.status = OfferStatus.ACTIVE.value
        offer.is_active = True
    await session.flush()
    await services.offer_lifecycle.queue_launch_announcement(
        session, offer, actor.id if actor else None
    )
    await state.clear()
    expiry_text = expires_at.strftime("%d/%m/%Y") if expires_at else "بدون تاريخ ثابت"
    await message.answer(
        f"تم تشفير عنصر المخزون وحفظه ✅\nتاريخ الانتهاء: {expiry_text}",
        reply_markup=admin_back(),
    )


# ---------------- Staff ----------------
@router.callback_query(F.data == "admin:staff")
async def staff_home(callback: CallbackQuery, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await edit_or_send(callback.message, 
        "اختر منصة من قسم المنصات ثم اضغط تعيين موظف.", reply_markup=admin_back()
    )


@router.callback_query(F.data.startswith("admin:staff_add:"))
async def staff_add_start(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.update_data(staff_provider_id=int(callback.data.split(":")[2]))
    await state.set_state(AdminAssignStaffStates.telegram_id)
    await edit_or_send(callback.message, 
        "اكتب Telegram ID للموظف. يجب أن يكون قد استخدم /start مرة واحدة:"
    )


@router.message(AdminAssignStaffStates.telegram_id)
async def staff_add_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    try:
        tid = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب Telegram ID بالأرقام.")
    user = await services.users.get(session, tid)
    if not user:
        return await message.answer("المستخدم لم يشغل البوت بعد.")
    data = await state.get_data()
    pid = int(data["staff_provider_id"])
    if not await services.subscriptions.feature_enabled(session, pid, "staff.manage"):
        return await message.answer("إدارة الموظفين غير متاحة في باقة هذه المنصة.")
    current_count = int(
        await session.scalar(
            select(func.count())
            .select_from(ProviderStaff)
            .where(ProviderStaff.provider_id == pid, ProviderStaff.is_active.is_(True))
        )
        or 0
    )
    existing = await session.scalar(
        select(ProviderStaff).where(
            ProviderStaff.provider_id == pid, ProviderStaff.user_id == user.id
        )
    )
    if existing:
        existing.is_active = True
        existing.title = "manager"
        existing.role = "MANAGER"
        existing.can_review_payments = True
        existing.can_manage_offers = True
        existing.can_manage_inventory = True
        existing.can_manage_branding = True
        existing.can_support = True
        existing.can_view_reports = True
        existing.can_manage_disputes = True
        existing.can_approve_refunds = True
        existing.can_view_finance = True
        existing.can_view_pii = True
        existing.can_export_data = True
    else:
        try:
            await services.subscriptions.assert_within_limit(
                session, pid, "staff.max", current_count
            )
        except ValueError as exc:
            return await message.answer(str(exc))
        session.add(
            ProviderStaff(
                provider_id=pid,
                user_id=user.id,
                title="manager",
                role="MANAGER",
                can_review_payments=True,
                can_manage_offers=True,
                can_manage_inventory=True,
                can_manage_branding=True,
                can_support=True,
                can_view_reports=True,
                can_manage_disputes=True,
                can_approve_refunds=True,
                can_view_finance=True,
                can_view_pii=True,
                can_export_data=True,
            )
        )
    user.role = "provider"
    await session.flush()
    mark_platform_authorization_dirty(
        session, telegram_id=tid, provider_id=pid
    )
    await state.clear()
    await message.answer(
        "تم ربط الموظف بالمنصة بكامل صلاحيات مدير المنصة ✅", reply_markup=admin_back()
    )


# ---------------- Provider catalog hierarchy ----------------
@router.callback_query(F.data.startswith("admin:provider_catalog:"))
async def provider_catalog_manager(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await callback_notice(callback, "جاري تحميل الأقسام والخدمات...")
    provider_id = int((callback.data or "").split(":")[2])
    provider = await session.get(Provider, provider_id)
    if not provider:
        await edit_or_send(callback.message, "المنصة غير موجودة.")
        return
    sections = await services.catalog.create_default_provider_catalog(session, provider)
    rows = [
        [
            InlineKeyboardButton(
                text="➕ إضافة قسم مخصص",
                callback_data=f"admin:catalog_section_add:{provider.id}",
                style="success",
            )
        ]
    ]
    lines = [f"📂 <b>أقسام وخدمات {safe(provider.name_ar)}</b>"]
    for section in sections:
        service_items = list(
            (
                await session.scalars(
                    select(CatalogServiceItem)
                    .where(CatalogServiceItem.section_id == section.id)
                    .order_by(CatalogServiceItem.sort_order, CatalogServiceItem.id)
                )
            ).all()
        )
        lines.append(f"\n\n{section.emoji} <b>{safe(section.name)}</b> — ID {section.id}")
        if service_items:
            for item in service_items:
                lines.append(f"\n  • {item.emoji} {safe(item.name)} — ID {item.id}")
        else:
            lines.append("\n  • لا توجد خدمات بعد")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"➕ خدمة داخل {section.name}",
                    callback_data=f"a:csa:{section.id}",
                    style="primary",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="↩️ المنصة", callback_data=f"admin:provider:{provider.id}")]
    )
    await edit_or_send(callback.message, 
        "".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )


@router.callback_query(F.data.startswith("admin:catalog_section_add:"))
async def catalog_section_add_start(
    callback: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    provider_id = int((callback.data or "").split(":")[2])
    await state.clear()
    await state.update_data(catalog_provider_id=provider_id)
    await state.set_state(AdminCatalogSectionStates.name)
    await edit_or_send(callback.message, "اكتب اسم القسم، مثال: أدوات الذكاء الاصطناعي")


@router.message(AdminCatalogSectionStates.name)
async def catalog_section_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = " ".join((message.text or "").split())
    if len(value) < 2 or len(value) > 140:
        await message.answer("اكتب اسم قسم واضحًا.")
        return
    data = await state.get_data()
    provider_id = int(data["catalog_provider_id"])
    if await session.scalar(
        select(CatalogSection.id).where(
            CatalogSection.provider_id == provider_id,
            CatalogSection.name == value,
        )
    ):
        await message.answer("هذا القسم موجود مسبقًا داخل المنصة.")
        return
    section = CatalogSection(
        provider_id=provider_id,
        name=value,
        emoji=smart_emoji(value),
    )
    session.add(section)
    await session.flush()
    await state.clear()
    await message.answer(
        f"تمت إضافة القسم {section.emoji} <b>{safe(section.name)}</b> تلقائيًا ✅",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📂 العودة للأقسام",
                        callback_data=f"admin:provider_catalog:{section.provider_id}",
                        style="primary",
                    )
                ]
            ]
        ),
    )


@router.message(AdminCatalogSectionStates.emoji)
async def catalog_section_finish_legacy(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    """Finish FSM sessions that were already waiting for a manual emoji."""
    if not await require_admin(message, settings):
        return
    data = await state.get_data()
    provider_id = int(data.get("catalog_provider_id") or 0)
    name = str(data.get("catalog_section_name") or "قسم جديد")
    duplicate = await session.scalar(
        select(CatalogSection.id).where(
            CatalogSection.provider_id == provider_id,
            CatalogSection.name == name,
        )
    )
    if not duplicate:
        session.add(CatalogSection(provider_id=provider_id, name=name, emoji=smart_emoji(name)))
        await session.flush()
    await state.clear()
    await message.answer("تم إكمال الخطوة تلقائيًا ✅", reply_markup=admin_back())


@router.callback_query(F.data.startswith("a:csa:"))
@router.callback_query(F.data.startswith("admin:catalog_service_add:"))
async def catalog_service_add_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    parts = (callback.data or "").split(":")
    try:
        section_id = int(parts[2] if parts[0] == "a" else parts[3])
    except (ValueError, IndexError):
        await edit_or_send(callback.message, "بيانات القسم غير صحيحة.")
        return
    section = await session.get(CatalogSection, section_id)
    if not section:
        await edit_or_send(callback.message, "القسم غير موجود.")
        return
    provider_id = int(section.provider_id)
    await state.clear()
    await state.update_data(
        catalog_service_provider_id=provider_id,
        catalog_service_section_id=section_id,
    )
    await state.set_state(AdminCatalogServiceStates.name)
    await edit_or_send(callback.message, 
        f"اكتب اسم الخدمة داخل {section.emoji} {safe(section.name)}، مثال: Gemini"
    )


@router.message(AdminCatalogServiceStates.name)
async def catalog_service_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = " ".join((message.text or "").split())
    if len(value) < 2 or len(value) > 160:
        await message.answer("اكتب اسم خدمة واضحًا.")
        return
    data = await state.get_data()
    section_id = int(data["catalog_service_section_id"])
    if await session.scalar(
        select(CatalogServiceItem.id).where(
            CatalogServiceItem.section_id == section_id,
            CatalogServiceItem.name == value,
        )
    ):
        await message.answer("هذه الخدمة موجودة مسبقًا داخل القسم.")
        return
    item = CatalogServiceItem(
        provider_id=int(data["catalog_service_provider_id"]),
        section_id=section_id,
        name=value,
        emoji=smart_emoji(value),
    )
    session.add(item)
    await session.flush()
    await state.clear()
    await message.answer(
        f"تمت إضافة الخدمة {item.emoji} <b>{safe(item.name)}</b> تلقائيًا ✅\n"
        f"معرف الخدمة: <code>{item.id}</code>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📂 العودة للأقسام",
                        callback_data=f"admin:provider_catalog:{item.provider_id}",
                        style="primary",
                    )
                ]
            ]
        ),
    )


@router.message(AdminCatalogServiceStates.emoji)
async def catalog_service_finish_legacy(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    """Finish FSM sessions that were already waiting for a manual emoji."""
    if not await require_admin(message, settings):
        return
    data = await state.get_data()
    provider_id = int(data.get("catalog_service_provider_id") or 0)
    section_id = int(data.get("catalog_service_section_id") or 0)
    name = str(data.get("catalog_service_name") or "خدمة جديدة")
    duplicate = await session.scalar(
        select(CatalogServiceItem.id).where(
            CatalogServiceItem.section_id == section_id,
            CatalogServiceItem.name == name,
        )
    )
    if not duplicate:
        session.add(
            CatalogServiceItem(
                provider_id=provider_id,
                section_id=section_id,
                name=name,
                emoji=smart_emoji(name),
            )
        )
        await session.flush()
    await state.clear()
    await message.answer("تم إكمال الخطوة تلقائيًا ✅", reply_markup=admin_back())

