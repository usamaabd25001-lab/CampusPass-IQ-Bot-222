from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import (
    offer_keyboard,
    subscription_details_keyboard,
    subscriptions_keyboard,
    subscription_categories_keyboard,
)
from app.bot.ui import edit_or_send
from app.core.config import Settings
from app.core.presentation import subscription_status_label
from app.core.time import as_utc, format_datetime, format_iso_datetime
from app.core.utils import safe
from app.db.models import EmailAccount, Offer, WarrantyClaim
from app.services.container import Services

router = Router(name="student_subscriptions")


@router.callback_query(F.data == "subscriptions:categories")
async def subscription_categories(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get(session, callback.from_user.id)
    if not user:
        return
    counts = await services.student_subscriptions.user_subscription_counts(session, user)
    if not counts.get("all"):
        await edit_or_send(callback.message, "لا توجد اشتراكات محفوظة حتى الآن.")
        return
    await edit_or_send(callback.message, 
        "📅 <b>اشتراكاتي</b>\nاختر القسم:",
        reply_markup=subscription_categories_keyboard(counts),
    )


@router.callback_query(F.data.startswith("subscriptions:list"))
async def list_subscriptions(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get(session, callback.from_user.id)
    if not user:
        return
    parts = (callback.data or "subscriptions:list:all:0").split(":")
    filter_key = parts[2] if len(parts) > 2 else "all"
    try:
        page = max(0, int(parts[3])) if len(parts) > 3 else 0
    except ValueError:
        page = 0
    items, total = await services.student_subscriptions.user_subscriptions_page(
        session, user, filter_key=filter_key, page=page, page_size=8
    )
    if not items:
        await edit_or_send(callback.message, "لا توجد اشتراكات ضمن هذا القسم.")
        return
    await edit_or_send(callback.message, 
        f"📅 <b>اشتراكاتي</b> — {total} اشتراك\nاختر الاشتراك:",
        reply_markup=subscriptions_keyboard(
            items, filter_key=filter_key, page=page, total=total
        ),
    )


@router.callback_query(F.data.startswith("subscription:view:"))
async def view_subscription(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get(session, callback.from_user.id)
    if not user:
        return
    subscription = await services.student_subscriptions.get_for_user(
        session, int((callback.data or "").split(":")[2]), user
    )
    if not subscription:
        await edit_or_send(callback.message, "الاشتراك غير موجود.")
        return
    now = datetime.now(UTC)
    remaining = "غير محدد"
    if subscription.ends_at:
        ends_at_utc = as_utc(subscription.ends_at)
        seconds = (ends_at_utc - now).total_seconds() if ends_at_utc else 0
        remaining = "منتهي" if seconds <= 0 else f"{max(1, int((seconds + 86399) // 86400))} يوم"
    allow_code = bool(
        await session.scalar(
            select(EmailAccount.id).where(
                EmailAccount.provider_id == subscription.provider_id,
                (EmailAccount.offer_id == subscription.offer_id)
                | (EmailAccount.offer_id.is_(None)),
            )
        )
    )
    start_text = format_datetime(subscription.starts_at, settings.timezone, "لم يبدأ")
    end_text = format_datetime(subscription.ends_at, settings.timezone)
    warranty_text = format_datetime(subscription.warranty_ends_at, settings.timezone)
    status_ar = subscription_status_label(subscription.status)

    warranty_eligibility = await services.warranties.eligibility(
        session, subscription=subscription, user=user
    )
    text = (
        f"📅 <b>{safe(subscription.offer_name_snapshot)}</b>\n\n"
        f"المنصة: {safe(subscription.provider_name_snapshot)}\n"
        f"الحالة: {safe(status_ar)}\n"
        f"بدأ: {start_text}\n"
        f"ينتهي: {end_text}\n"
        f"المتبقي: {remaining}\n"
        f"ضمان التفعيل حتى: {warranty_text}"
    )
    await edit_or_send(callback.message, 
        text,
        reply_markup=subscription_details_keyboard(
            subscription,
            allow_code=allow_code,
            warranty_enabled=warranty_eligibility.allowed,
        ),
    )


@router.callback_query(F.data.startswith("subscription:receipt:"))
async def subscription_receipt(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get(session, callback.from_user.id)
    if not user:
        return
    subscription = await services.student_subscriptions.get_for_user(
        session, int((callback.data or "").split(":")[2]), user
    )
    if not subscription:
        return
    receipt = await services.student_subscriptions.receipt(session, subscription.order_id)
    if not receipt:
        order = await services.orders.get(session, subscription.order_id)
        if order:
            receipt = await services.student_subscriptions.ensure_receipt(
                session, order, subscription
            )
    if not receipt:
        await edit_or_send(callback.message, "الوصل غير متاح حاليًا.")
        return
    data = receipt.snapshot
    start = format_iso_datetime(data.get("starts_at"), settings.timezone)
    end = format_iso_datetime(data.get("ends_at"), settings.timezone)
    await edit_or_send(callback.message, 
        "🧾 <b>وصل الاشتراك</b>\n\n"
        f"رقم الطلب: <code>{safe(data.get('order_public_id'))}</code>\n"
        f"المنصة: {safe(data.get('provider'))}\n"
        f"الخدمة: {safe(data.get('service'))}\n"
        f"العرض: {safe(data.get('offer'))}\n"
        f"البداية: {safe(start)}\n"
        f"النهاية: {safe(end)}\n"
        f"السعر: {int(data.get('subtotal_iqd') or 0):,} د.ع\n"
        f"رسوم الخدمة: {int(data.get('service_fee_iqd') or 0):,} د.ع\n"
        f"الإجمالي: <b>{int(data.get('total_iqd') or 0):,} د.ع</b>\n"
        f"طريقة الدفع: {safe(data.get('payment_method'))}"
    )


@router.callback_query(F.data.startswith("subscription:code:"))
async def subscription_code(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get(session, callback.from_user.id)
    if not user:
        return
    subscription = await services.student_subscriptions.get_for_user(
        session, int((callback.data or "").split(":")[2]), user
    )
    if not subscription:
        return
    order = await services.orders.get(session, subscription.order_id)
    offer = await session.get(Offer, subscription.offer_id)
    if not order or not offer:
        return
    try:
        await services.email_codes.request_new_code(session, order, offer)
    except ValueError as exc:
        await edit_or_send(callback.message, str(exc))
        return
    await edit_or_send(callback.message, 
        "⏳ تم بدء انتظار رسالة مطابقة لهذا الاشتراك. سيصلك الرمز عند وصولها."
    )


@router.callback_query(F.data.startswith("subscription:code_claim:"))
async def subscription_code_from_warranty(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get(session, callback.from_user.id)
    if not user:
        return
    claim = await session.scalar(
        select(WarrantyClaim).where(
            WarrantyClaim.id == int((callback.data or "").split(":")[3]),
            WarrantyClaim.user_id == user.id,
            WarrantyClaim.status == "waiting_student_action",
        )
    )
    if not claim:
        await edit_or_send(callback.message, "لا توجد موافقة ضمان نشطة لسحب الرمز.")
        return
    subscription = await services.student_subscriptions.get_for_user(
        session, claim.subscription_id, user
    )
    if not subscription:
        return
    order = await services.orders.get(session, subscription.order_id)
    offer = await session.get(Offer, subscription.offer_id)
    if not order or not offer:
        return
    try:
        await services.email_codes.request_new_code(session, order, offer)
    except ValueError as exc:
        await edit_or_send(callback.message, str(exc))
        return
    await edit_or_send(
        callback.message,
        "⏳ تم بدء سحب رمز جديد ضمن الضمان. سيصلك فور وصول رسالة مطابقة.",
    )


@router.callback_query(F.data.startswith("subscription:renew:"))
async def subscription_renew(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get(session, callback.from_user.id)
    if not user:
        return
    subscription = await services.student_subscriptions.get_for_user(
        session, int((callback.data or "").split(":")[2]), user
    )
    if not subscription:
        return
    offer = await services.catalog.get_offer(session, subscription.offer_id)
    if not offer:
        await edit_or_send(callback.message, "العرض الأصلي لم يعد متاحًا؛ راجع عروض المنصة.")
        return
    await edit_or_send(callback.message, 
        "🔄 يمكنك إنشاء طلب تجديد جديد من العرض الحالي. "
        "سيبين لك البوت هل التجديد على نفس الحساب أم بحساب جديد.",
        reply_markup=offer_keyboard(offer.id),
    )


@router.callback_query(F.data.startswith("subscription:problem:"))
async def subscription_problem(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        subscription_id = int((callback.data or "").split(":")[2])
        await edit_or_send(callback.message, 
            "اختر زر «لم يتم التفعيل» من رسالة التسليم، أو افتح مركز المساعدة "
            f"مع ذكر رقم الاشتراك الداخلي {subscription_id}."
        )
