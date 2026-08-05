from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import (
    coupon_prompt_keyboard,
    offer_keyboard,
    offers_keyboard,
    payment_methods_keyboard,
    promotion_offers_keyboard,
    promotion_providers_keyboard,
    purchase_confirmation_keyboard,
    provider_sections_keyboard,
    profile_webapp_keyboard,
    favorites_v11_keyboard,
    providers_keyboard,
    service_items_keyboard,
    service_offers_keyboard,
)
from app.bot.processing import processing_message
from app.bot.states import OrderCouponStates, PurchaseStates, RegistrationStates
from app.bot.ui import edit_or_send, callback_notice
from app.core.presentation import delivery_estimate_label, provider_status_label
from app.core.utils import safe, validate_email
from app.db.models import DeliveryJob, DeliveryJobStatus, OfferStatus, OrderCouponType
from app.services.activation_guides import ACTIVATION_MODE_LABELS
from app.services.container import Services

router = Router(name="catalog")


@router.callback_query(F.data == "promo:root")
async def promotion_root(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.message:
        return
    providers = await services.catalog.promotion_providers(session)
    if not providers:
        from app.bot.keyboards.inline import back_keyboard

        await edit_or_send(
            callback.message,
            "لا توجد عروض متاحة حالياً",
            reply_markup=back_keyboard("nav:home"),
        )
        return
    await edit_or_send(
        callback.message,
        "🔥 <b>العروض الطلابية</b>\nاختر منصة لعرض التخفيضات المتاحة فقط:",
        reply_markup=promotion_providers_keyboard(providers),
    )


@router.callback_query(F.data.startswith("promo:provider:"))
async def promotion_provider_offers(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.message:
        return
    try:
        provider_id = int((callback.data or "").split(":")[2])
    except (ValueError, IndexError):
        await edit_or_send(callback.message, "بيانات المنصة غير صحيحة.")
        return
    provider = await services.catalog.get_provider(session, provider_id)
    offers = await services.catalog.promotion_offers(session, provider_id) if provider else []
    if not provider or not offers:
        from app.bot.keyboards.inline import back_keyboard

        await edit_or_send(
            callback.message,
            "لا توجد عروض متاحة حالياً",
            reply_markup=back_keyboard("promo:root"),
        )
        return
    await edit_or_send(
        callback.message,
        f"🔥 <b>عروض {safe(provider.name_ar)}</b>\nاختر العرض المناسب:",
        reply_markup=promotion_offers_keyboard(offers, provider.id),
    )


@router.callback_query(F.data.in_({"catalog:categories", "store:providers"}))
async def catalog_root(callback: CallbackQuery, session: AsyncSession, services: Services) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    user = await services.users.get_or_create(
        session,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name or "Telegram User",
    )
    profile_complete, _missing = await services.student_commerce.profile_status(user.profile)
    if not profile_complete:
        if services.settings.public_base_url:
            await edit_or_send(
                callback.message,
                "🪪 أكمل معلوماتك أولاً لفتح الاشتراكات والخدمات بصورة آمنة ومنظمة.",
                reply_markup=profile_webapp_keyboard(
                    services.settings.public_base_url.rstrip("/") + "/webapp/student/profile",
                    complete=False,
                ),
            )
        else:
            await edit_or_send(
                callback.message,
                "تعذر فتح ملف الطالب لأن PUBLIC_BASE_URL غير مضبوط. راجع إعدادات النشر.",
            )
        return
    providers = await services.catalog.providers(session)
    card_rows = await services.student_commerce.provider_cards(session, limit=100)
    card_map = {int(row["id"]): row for row in card_rows}
    summaries = await services.reviews.provider_summaries(
        session, [provider.id for provider in providers]
    )
    for provider in providers:
        average, count = summaries.get(provider.id, (0.0, 0))
        provider._rating_average = average
        provider._rating_count = count
        provider._rating_stars = services.reviews.stars(average)
        provider._subscriber_count = int(card_map.get(provider.id, {}).get("subscriber_count", 0))
    if not providers:
        await edit_or_send(callback.message, "لا توجد منصات لديها عروض فعالة حاليًا.")
        return
    await edit_or_send(callback.message, "🏢 اختر المنصة:", reply_markup=providers_keyboard(providers))


@router.callback_query(F.data.startswith("store:provider:"))
async def provider_sections(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.message:
        return
    provider_id = int((callback.data or "").split(":")[2])
    provider = await services.catalog.get_provider(session, provider_id)
    sections = await services.catalog.sections(session, provider_id) if provider else []
    if not provider:
        await edit_or_send(callback.message, "المنصة غير متاحة حاليًا.")
        return
    if not sections:
        await edit_or_send(callback.message, "لا توجد أقسام تحتوي على عروض فعالة في هذه المنصة.")
        return
    average, count = await services.reviews.provider_summary(session, provider.id)
    stars = services.reviews.stars(average)
    rating_line = (
        f"\nالتقييم: <b>{stars}</b> {average:.1f}/5 — من {count} طالب"
        if count else "\nالتقييم: ☆☆☆☆☆ — منصة جديدة بلا تقييمات"
    )
    work = await services.student_commerce.working_status(session, provider.id)
    if work["is_open"]:
        work_line = "\n🟢 متواجد الآن"
    elif work.get("next_open_at"):
        next_open = work["next_open_at"]
        work_line = f"\n🔴 خارج أوقات العمل — نعود {next_open.strftime('%d/%m %H:%M')}"
    else:
        work_line = "\n🔴 خارج أوقات العمل"
    await edit_or_send(callback.message, 
        f"🏢 <b>{safe(provider.name_ar)}</b>\n{safe(provider.description, '')}{rating_line}{work_line}\n\nاختر القسم:",
        reply_markup=provider_sections_keyboard(sections, provider.id),
    )


@router.callback_query(F.data.startswith("store:section:"))
async def section_services(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.message:
        return
    _, _, provider_id_text, section_id_text = (callback.data or "").split(":")
    provider_id = int(provider_id_text)
    section_id = int(section_id_text)
    section = await services.catalog.section(session, section_id)
    items = await services.catalog.services(session, provider_id, section_id)
    if not section or section.provider_id != provider_id:
        await edit_or_send(callback.message, "القسم غير موجود.")
        return
    if not items:
        await edit_or_send(callback.message, "لا توجد خدمات فعالة في هذا القسم.")
        return
    await edit_or_send(callback.message, 
        f"{section.emoji} <b>{safe(section.name)}</b>\nاختر الخدمة:",
        reply_markup=service_items_keyboard(items, provider_id, section_id),
    )


@router.callback_query(F.data.startswith("svc:"))
@router.callback_query(F.data.startswith("store:service:"))
async def service_offers(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.message:
        return
    parts = (callback.data or "").split(":")
    try:
        service_id = int(parts[1]) if parts[0] == "svc" else int(parts[4])
    except (ValueError, IndexError):
        await edit_or_send(callback.message, "بيانات الخدمة غير صحيحة.")
        return
    service = await services.catalog.service(session, service_id)
    if not service:
        await edit_or_send(callback.message, "الخدمة غير موجودة.")
        return
    provider_id = int(service.provider_id)
    section_id = int(service.section_id)
    offers = await services.catalog.offers_for_service(session, provider_id, service_id)
    if not offers:
        await edit_or_send(callback.message, "لا توجد عروض متاحة لهذه الخدمة حاليًا.")
        return
    await edit_or_send(callback.message, 
        f"🧩 <b>{safe(service.name)}</b>\nاختر العرض المناسب:",
        reply_markup=service_offers_keyboard(offers, provider_id, section_id),
    )


@router.callback_query(F.data.startswith("cat:"))
async def category_offers(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.message:
        return
    category_id = int((callback.data or "").split(":")[1])
    offers = await services.catalog.offers(session, category_id=category_id, featured_only=True)
    if not offers:
        await edit_or_send(callback.message, "لا توجد عروض متاحة في هذا القسم حاليًا.")
    else:
        await edit_or_send(callback.message, "العروض المتاحة:", reply_markup=offers_keyboard(offers))


@router.callback_query(F.data.startswith("guide:view:offer:"))
async def view_offer_guide(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.message:
        return
    offer_id = int((callback.data or "").split(":")[3])
    guide = await services.activation_guides.get_for_offer(session, offer_id)
    if not guide:
        await edit_or_send(callback.message, "لا توجد تعليمات مضافة لهذا العرض بعد.")
        return
    await services.activation_guides.send_to_message(callback.message, guide)


@router.callback_query(F.data.startswith("guide:view:order:"))
async def view_order_guide(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    order_id = int((callback.data or "").split(":")[3])
    order = await services.orders.get(session, order_id)
    if not order or order.user.telegram_id != callback.from_user.id:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    guide = await services.activation_guides.get_for_offer(session, order.offer_id)
    if not guide:
        await edit_or_send(callback.message, "لا توجد تعليمات مضافة لهذا العرض.")
        return
    await services.activation_guides.send_to_message(
        callback.message,
        guide,
        order_id=order.id,
        include_acknowledgement=guide.acknowledgement_required,
    )


@router.callback_query(F.data.startswith("guide:ack:"))
async def acknowledge_order_guide(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    order = await services.orders.get(session, int((callback.data or "").split(":")[2]))
    user = await services.users.get(session, callback.from_user.id)
    if not order or not user or order.user_id != user.id:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    await services.activation_guides.acknowledge(session, order=order, user=user)
    job = await session.scalar(
        select(DeliveryJob).where(
            DeliveryJob.order_id == order.id,
            DeliveryJob.status == DeliveryJobStatus.PENDING.value,
        )
    )
    if job:
        job.next_attempt_at = datetime.now(UTC)
        job.last_error = None
    await edit_or_send(callback.message, 
        "✅ تم تسجيل أنك قرأت التعليمات. تبقى التعليمات متاحة دائمًا من تفاصيل الطلب والاشتراك."
    )


@router.callback_query(F.data.in_({"favorites:list", "favorites:v11"}))
async def favorites_list(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get(session, callback.from_user.id)
    if not user:
        return
    grouped = await services.student_commerce.favorites(session, user=user)
    total = sum(len(items) for items in grouped.values())
    await edit_or_send(
        callback.message,
        f"❤️ <b>مفضلاتي</b> — {total} عنصر\n"
        "تضم المنصات والأقسام والعروض المحفوظة.",
        reply_markup=favorites_v11_keyboard(grouped),
    )


@router.callback_query(F.data.regexp(r"^favorite:(provider|section|offer):\d+$"))
@router.callback_query(F.data.regexp(r"^fav:\d+$"))
async def toggle_favorite(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user:
        return
    user = await services.users.get_or_create(
        session,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name or "Telegram User",
    )
    parts = (callback.data or "").split(":")
    if parts[0] == "fav":
        target_type, target_id = "offer", int(parts[1])
    else:
        target_type, target_id = parts[1], int(parts[2])
    try:
        added = await services.student_commerce.toggle_favorite(
            session, user=user, target_type=target_type, target_id=target_id
        )
    except ValueError as exc:
        await callback_notice(callback, str(exc), show_alert=True)
        return
    await callback_notice(
        callback,
        "تمت الإضافة إلى مفضلاتي ❤️" if added else "تمت الإزالة من مفضلاتي",
    )


@router.callback_query(F.data.startswith("offer:"))
async def offer_details(callback: CallbackQuery, session: AsyncSession, services: Services) -> None:
    await callback.answer()
    if not callback.message:
        return
    parts = (callback.data or "").split(":")
    offer_id = int(parts[1])
    back_callback = "catalog:categories"
    if len(parts) >= 4 and parts[2] == "promo":
        try:
            back_callback = f"promo:provider:{int(parts[3])}"
        except ValueError:
            back_callback = "promo:root"
    offer = await services.catalog.get_offer(session, offer_id)
    if offer:
        try:
            policy = await services.student_subscriptions.validate_sale(session, offer)
            validity = services.student_subscriptions.validity_label(policy)
        except (ValueError, PermissionError) as exc:
            policy = None
            validity = str(exc)
    else:
        policy = None
        validity = "غير متاح"
    if not offer or offer.status != OfferStatus.ACTIVE.value:
        await edit_or_send(callback.message, "العرض غير متاح.")
        return
    wallet_balance = 0
    if callback.from_user:
        student_user = await services.users.get(session, callback.from_user.id)
        if student_user:
            wallet_balance = await services.wallets.balance(session, "user", student_user.id)
    preview = await services.student_commerce.invoice_preview(
        service_price_iqd=offer.price_iqd,
        bot_fee_iqd=offer.service_fee_iqd,
        wallet_balance_iqd=wallet_balance,
    )
    total = preview.cash_due_iqd
    average, rating_count = await services.reviews.provider_summary(session, offer.provider_id)
    stars = services.reviews.stars(average)
    guide = await services.activation_guides.get_for_offer(session, offer.id)
    activation_label = ACTIVATION_MODE_LABELS.get(
        guide.activation_mode if guide else offer.delivery_type, offer.delivery_type
    )
    rating_line = (
        f"{stars} {average:.1f}/5 من {rating_count} طالب"
        if rating_count else "☆☆☆☆☆ منصة جديدة"
    )
    text = (
        f"🔥 <b>{safe(offer.title)}</b>\n\n"
        f"المنصة: {safe(offer.provider.name_ar)}\n"
        f"تقييم المنصة: <b>{rating_line}</b>\n"
        f"{safe(offer.description, '')}\n\n"
        f"السعر: {offer.price_iqd:,} د.ع\n"
        f"رسوم البوت: {offer.service_fee_iqd:,} د.ع\n"
        f"خصم المحفظة التلقائي لرسوم البوت: -{preview.wallet_fee_deduction_iqd:,} د.ع\n"
        f"الإجمالي المتوقع: <b>{total:,} د.ع</b>\n"
        f"الصلاحية: <b>{safe(validity)}</b>\n"
        f"الأجهزة: {offer.devices_count or 'حسب شروط العرض'}\n"
        f"طريقة التفعيل: {safe(activation_label)}\n"
        f"وقت التسليم المتوقع: {safe(delivery_estimate_label(offer.delivery_type))}\n"
        f"دليل التفعيل: {'✅ متوفر' if guide else '⚠️ غير متوفر'}\n\n"
        f"الشروط: {safe(offer.terms, 'لا توجد شروط إضافية')}\n\n"
        "⚠️ سيُثبت تاريخ البداية والنهاية في الوصل بعد التفعيل."
    )
    friends_enabled = bool(
        await services.friend_packages.config_for_offer(session, offer.id)
    )
    if offer.image_file_id:
        await callback.message.answer_photo(
            offer.image_file_id,
            caption=text,
            reply_markup=offer_keyboard(
                offer.id, back=back_callback, friends_enabled=friends_enabled
            ),
        )
    else:
        await edit_or_send(
            callback.message,
            text,
            reply_markup=offer_keyboard(
                offer.id, back=back_callback, friends_enabled=friends_enabled
            ),
        )


@router.callback_query(F.data.startswith("provider:info:"))
async def provider_info(callback: CallbackQuery, session: AsyncSession, services: Services) -> None:
    await callback.answer()
    offer = await services.catalog.get_offer(session, int((callback.data or "").split(":")[2]))
    if not offer or not callback.message:
        return
    provider = offer.provider
    average, count = await services.reviews.provider_summary(session, provider.id)
    stars = services.reviews.stars(average)
    rating_text = f"{stars} {average:.1f}/5 — قيّمه {count} طالب" if count else "☆☆☆☆☆ منصة جديدة"
    await edit_or_send(callback.message, 
        f"🏢 <b>{safe(provider.name_ar)}</b>\n"
        f"{safe(provider.description, '')}\n"
        f"التقييم: <b>{rating_text}</b>\n"
        f"الحالة: {provider_status_label(provider.status)}\n"
        f"التواصل: @{safe(provider.contact_username, 'غير محدد')}"
    )


@router.callback_query(F.data.startswith("buy:"))
async def buy_offer(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get_or_create(
        session,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name or "Telegram User",
    )
    offer_id = int((callback.data or "").split(":")[1])
    profile_complete, _missing = await services.student_commerce.profile_status(user.profile)
    if not profile_complete:
        await state.clear()
        if services.settings.public_base_url:
            await edit_or_send(
                callback.message,
                "🪪 أكمل معلوماتك أولاً ليتم ربط الطلب والدفع والضمان بحسابك بصورة صحيحة.",
                reply_markup=profile_webapp_keyboard(
                    services.settings.public_base_url.rstrip("/") + "/webapp/student/profile",
                    complete=False,
                ),
            )
        else:
            await state.update_data(quick_registration=True, pending_purchase_offer_id=offer_id)
            await state.set_state(RegistrationStates.full_name)
            await edit_or_send(callback.message, "اكتب اسمك الكامل لإكمال ملفك مؤقتاً.")
        return
    async with processing_message(callback.message, "⏳ جاري فحص العرض والمخزون..."):
        offer = await services.catalog.get_offer(session, offer_id)
        if offer:
            try:
                await services.orders.validate_offer(session, offer)
            except ValueError as exc:
                await edit_or_send(callback.message, str(exc))
                return
    if not offer or offer.status != OfferStatus.ACTIVE.value:
        await edit_or_send(callback.message, "العرض غير متاح.")
        return
    guide = await services.activation_guides.get_for_offer(session, offer.id)
    if guide and guide.show_before_delivery:
        await services.activation_guides.send_to_message(callback.message, guide)
        await edit_or_send(callback.message, 
            "✅ بعد قراءة التعليمات أكمل الشراء. ستبقى التعليمات متاحة من تفاصيل الطلب."
        )
    fields = offer.activation_fields or []
    await state.update_data(
        purchase_offer_id=offer.id,
        purchase_fields=fields,
        purchase_index=0,
        activation_data={"_offer_title": offer.title},
        purchase_intent_id=(
            f"purchase:{user.id}:{offer.id}:"
            f"{int(datetime.now(UTC).timestamp() // (services.orders.settings.purchase_reservation_minutes * 60))}"
        ),
    )
    if fields:
        await state.set_state(PurchaseStates.activation_field)
        field = fields[0]
        await edit_or_send(callback.message, 
            str(field.get("label") or field.get("key") or "أدخل البيانات المطلوبة:")
        )
        return
    await _show_purchase_confirmation(
        callback.message, state, session, services, offer, in_place=True
    )


@router.message(PurchaseStates.activation_field)
async def activation_field(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    fields = data.get("purchase_fields", [])
    index = int(data.get("purchase_index", 0))
    if index >= len(fields):
        return
    field = fields[index]
    value = (message.text or "").strip()
    if field.get("type") == "email":
        value = validate_email(value) or ""
    if len(value) < 2:
        await message.answer("القيمة غير صحيحة. أعد الإدخال.")
        return
    activation_data = dict(data.get("activation_data", {}))
    activation_data[str(field.get("key") or f"field_{index}")] = value
    index += 1
    await state.update_data(activation_data=activation_data, purchase_index=index)
    if index < len(fields):
        next_field = fields[index]
        await message.answer(
            str(next_field.get("label") or next_field.get("key") or "أدخل البيانات:")
        )
        return
    user = await services.users.get(session, message.from_user.id)
    offer = await services.catalog.get_offer(session, int(data["purchase_offer_id"]))
    if user and offer:
        await _show_purchase_confirmation(message, state, session, services, offer)


async def _show_purchase_confirmation(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
    offer,
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

    data = await state.get_data()
    try:
        policy = await services.student_subscriptions.validate_sale(session, offer)
        validity = services.student_subscriptions.validity_label(policy)
    except (ValueError, PermissionError) as exc:
        await state.clear()
        await render(str(exc))
        return
    methods = await services.orders.payment_methods(session, offer.provider_id)
    if not methods:
        await state.clear()
        await render("تعذر متابعة الطلب لأن المنصة لا تملك طريقة دفع مفعلة.")
        return
    activation_data = dict(data.get("activation_data") or {"_offer_title": offer.title})
    masked = services.data_protection.mask_mapping(activation_data)
    fields = offer.activation_fields or []
    labels = {str(item.get("key") or ""): str(item.get("label") or item.get("key") or "البيان") for item in fields}
    activation_lines = []
    for key, value in masked.items():
        if str(key).startswith("_"):
            continue
        activation_lines.append(f"• {safe(labels.get(str(key), str(key)))}: <code>{safe(value)}</code>")
    activation_text = "\n".join(activation_lines) or "• لا توجد بيانات تفعيل إضافية"
    if not message.from_user:
        await state.clear()
        await render("تعذر التحقق من هوية الطالب. افتح العرض من حسابك داخل Telegram.")
        return
    student_user = await services.users.get(session, message.from_user.id)
    wallet_balance = (
        await services.wallets.balance(session, "user", student_user.id) if student_user else 0
    )
    preview = await services.student_commerce.invoice_preview(
        service_price_iqd=int(offer.price_iqd or 0),
        bot_fee_iqd=int(offer.service_fee_iqd or 0),
        wallet_balance_iqd=wallet_balance,
    )
    total = preview.cash_due_iqd
    await state.set_state(PurchaseStates.confirmation)
    await render(
        "🧾 <b>مراجعة الطلب قبل الإنشاء</b>\n\n"
        f"العرض: <b>{safe(offer.title)}</b>\n"
        f"المنصة: {safe(offer.provider.name_ar)}\n"
        f"السعر: {int(offer.price_iqd or 0):,} د.ع\n"
        f"رسوم البوت: {int(offer.service_fee_iqd or 0):,} د.ع\n"
        f"خصم تلقائي متوقع من المحفظة: -{preview.wallet_fee_deduction_iqd:,} د.ع\n"
        f"الإجمالي المتوقع: <b>{total:,} د.ع</b>\n"
        f"الصلاحية: {safe(validity)}\n"
        f"مهلة الدفع بعد الإنشاء: {services.orders.settings.purchase_reservation_minutes} دقيقة\n"
        f"وقت التسليم المتوقع: {safe(delivery_estimate_label(offer.delivery_type))}\n\n"
        "<b>البيانات التي ستستخدم للتفعيل:</b>\n"
        f"{activation_text}\n\n"
        f"<b>الشروط:</b> {safe(offer.terms, 'لا توجد شروط إضافية')}\n\n"
        "بالضغط على «أوافق وأنشئ الطلب» سيتم حجز المورد وبدء مهلة الدفع.",
        reply_markup=purchase_confirmation_keyboard(offer.id),
    )


@router.callback_query(F.data.startswith("purchase:confirm:"))
async def confirm_purchase(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    offer_id = int((callback.data or "").split(":")[2])
    data = await state.get_data()
    if int(data.get("purchase_offer_id") or 0) != offer_id:
        await callback_notice(callback, "انتهت جلسة التأكيد. افتح العرض من جديد.", show_alert=True)
        await state.clear()
        return
    user = await services.users.get(session, callback.from_user.id)
    offer = await services.catalog.get_offer(session, offer_id)
    if not user or not user.profile or not offer:
        await callback_notice(callback, "تعذر متابعة الطلب", show_alert=True)
        await state.clear()
        return
    await callback_notice(callback, "جاري إنشاء الطلب وحجز المورد...")
    async with processing_message(callback.message, "⏳ جاري إنشاء الطلب وحجز الاشتراك مؤقتاً..."):
        try:
            order = await services.orders.create(
                session,
                user,
                offer,
                data.get("activation_data", {"_offer_title": offer.title}),
                idempotency_key=str(data.get("purchase_intent_id") or "") or None,
            )
        except (ValueError, PermissionError) as exc:
            await state.clear()
            await edit_or_send(callback.message, str(exc))
            return
        methods = await services.orders.payment_methods(session, offer.provider_id)
    await state.clear()
    if not methods:
        await edit_or_send(callback.message, "تعذر متابعة الطلب لأن المنصة لا تملك طريقة دفع مفعلة.")
        return
    wallet_balance = await services.wallets.balance(session, "user", user.id)
    wallet_fee_used = max(
        0, int((order.payment_snapshot or {}).get("wallet_fee_deduction_iqd", 0) or 0)
    )
    await services.student_commerce.sync_checkout_snapshot_from_order(
        session,
        order=order,
        user_id=user.id,
        service_discount_iqd=0,
        metadata={"public_id": order.public_id, "source": "telegram_checkout"},
    )
    await edit_or_send(
        callback.message,
        "🧾 <b>فاتورة الطلب الأولية</b>\n\n"
        f"رقم الطلب: <code>{order.public_id}</code>\n"
        f"سعر الخدمة: <b>{order.subtotal_iqd:,} د.ع</b>\n"
        f"رسوم البوت: <b>{order.service_fee_iqd:,} د.ع</b>\n"
        f"خصم تلقائي من المحفظة لرسوم البوت: <b>-{wallet_fee_used:,} د.ع</b>\n"
        f"الإجمالي المطلوب: <b>{order.total_iqd:,} د.ع</b>\n"
        f"رصيد المحفظة المتبقي: <b>{wallet_balance:,} د.ع</b>\n"
        f"مهلة رفع إثبات الدفع: {services.orders.settings.purchase_reservation_minutes} دقيقة\n\n"
        "🎟 <b>هل لديك كود خصم؟</b>",
        reply_markup=coupon_prompt_keyboard(order.id),
    )


@router.callback_query(F.data == "purchase:cancel")
async def cancel_purchase_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback_notice(callback, "تم إلغاء العملية")
    if callback.message:
        await edit_or_send(callback.message, "تم إلغاء إنشاء الطلب، ولم يُحجز أي مورد أو مبلغ.")


@router.callback_query(F.data.startswith("purchase:restart:"))
async def restart_purchase_confirmation(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    offer_id = int((callback.data or "").split(":")[2])
    await state.clear()
    offer = await services.catalog.get_offer(session, offer_id)
    await callback_notice(callback, "ابدأ إدخال البيانات من جديد")
    if callback.message and offer:
        await edit_or_send(callback.message, 
            "تم مسح بيانات التأكيد السابقة. اضغط شراء للبدء من جديد.",
            reply_markup=offer_keyboard(offer.id),
        )



@router.callback_query(F.data.regexp(r"^coupon:skip:\d+$"))
async def coupon_skip(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    order = await services.orders.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not order or order.user.telegram_id != callback.from_user.id:
        await callback_notice(callback, "غير مصرح.", show_alert=True)
        return
    methods = await services.orders.payment_methods(session, order.provider_id)
    if not methods:
        await edit_or_send(callback.message, "لا توجد طريقة دفع مفعلة لهذه المنصة.")
        return
    await edit_or_send(
        callback.message,
        f"اختر طريقة الدفع للطلب <code>{order.public_id}</code>\n"
        f"الإجمالي: <b>{order.total_iqd:,} د.ع</b>",
        reply_markup=payment_methods_keyboard(methods, order.id),
    )


@router.callback_query(F.data.regexp(r"^coupon:apply:\d+$"))
async def coupon_apply_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    order = await services.orders.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not order or order.user.telegram_id != callback.from_user.id:
        return await callback_notice(callback, "غير مصرح.", show_alert=True)
    await state.clear()
    await state.update_data(coupon_order_id=order.id)
    await state.set_state(OrderCouponStates.code)
    await edit_or_send(callback.message, 
        "🎟 أرسل كود الخصم. يمكن أن يكون عامًا أو مخصصًا لهذه المنصة."
    )


@router.message(OrderCouponStates.code)
async def coupon_apply_finish(
    message: Message, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    order = await services.orders.get(session, int(data.get("coupon_order_id", 0)))
    user = await services.users.get(session, message.from_user.id)
    if not order or not user or order.user_id != user.id:
        await state.clear()
        return await message.answer("الطلب غير موجود أو لا يخص حسابك.")
    try:
        coupon, discount = await services.order_coupons.apply(
            session, order, user, message.text or ""
        )
    except ValueError as exc:
        return await message.answer(str(exc))
    methods = await services.orders.payment_methods(session, order.provider_id)
    service_discount = (
        int(discount)
        if coupon.coupon_type in {
            OrderCouponType.FIXED.value,
            OrderCouponType.PERCENT.value,
        }
        else 0
    )
    await services.student_commerce.sync_checkout_snapshot_from_order(
        session,
        order=order,
        user_id=user.id,
        service_discount_iqd=service_discount,
        metadata={
            "coupon_code": coupon.code,
            "coupon_type": coupon.coupon_type,
            "coupon_effect_iqd": int(discount),
        },
    )
    await state.clear()
    if coupon.coupon_type == OrderCouponType.FEE_WAIVER.value:
        effect = "تم إسقاط رسوم CampusPass بالكامل عن هذا الطلب."
    elif coupon.coupon_type == OrderCouponType.FREE_REPORT.value:
        effect = "تمت إضافة تقرير مجاني إلى مزايا حسابك لهذه المنصة."
    else:
        effect = f"قيمة الخصم المباشر: <b>{discount:,} د.ع</b>"
    wallet_balance = await services.wallets.balance(session, "user", user.id)
    await message.answer(
        f"✅ تم تطبيق الكود <code>{coupon.code}</code>\n"
        f"{effect}\n"
        f"الإجمالي الجديد: <b>{order.total_iqd:,} د.ع</b>\n"
        f"رصيد المحفظة: <b>{wallet_balance:,} د.ع</b>",
        reply_markup=payment_methods_keyboard(methods, order.id),
    )
