from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.keyboards.inline import (
    payment_review_keyboard,
    platform_terms_keyboard,
    provider_contexts_keyboard,
    provider_dashboard_keyboard,
    provider_orders_keyboard,
)
from app.bot.states import (
    ProviderCouponStates,
    ProviderEmailStates,
    ProviderReportV5States,
    ProviderSettlementProofStates,
    WithdrawalStates,
)
from app.bot.ui import edit_or_send, callback_notice
from app.core.config import Settings
from app.core.utils import parse_money, safe
from app.db.models import (
    EmailAccount,
    EmailAccountStatus,
    FeatureBillingMode,
    Offer,
    OfferActivationGuide,
    Order,
    OrderStatus,
    Provider,
    ProviderSettlement,
    ProviderStaff,
    SupportTicket,
    SystemSetting,
)
from app.services.container import Services
from app.services.platform_access import (
    ProviderAccessFailure,
    access_failure_message,
    effective_staff_view,
    invalidate_provider_access_cache,
    resolve_provider_access,
    set_active_provider_selection,
)

logger = logging.getLogger(__name__)

router = Router(name="provider")


async def _show_platform_terms(
    message: Message,
    settings: Settings,
) -> None:
    await edit_or_send(
        message,
        f"{settings.provider_terms_text}\n\n"
        f"🔐 <b>الخصوصية</b>\n{settings.privacy_text}\n\n"
        f"نسخة الشروط: <code>{settings.provider_terms_version}</code>",
        reply_markup=platform_terms_keyboard(),
        ensure_navigation=False,
    )


async def _platform_entry_allowed(
    message: Message,
    session: AsyncSession,
    services: Services,
    settings: Settings,
    telegram_id: int | str,
) -> bool:
    user = await services.users.get(session, int(str(telegram_id)))
    if user is None:
        user = await services.users.get_or_create(
            session,
            int(str(telegram_id)),
            None,
            "Telegram User",
        )
    context = await resolve_provider_access(
        session,
        settings,
        telegram_id,
        require_terms=True,
        allow_paused_provider=False,
    )
    session.info["campuspass_provider_access_context"] = context
    if context.failure_reason is ProviderAccessFailure.TERMS_REQUIRED:
        await _show_platform_terms(message, settings)
        return False
    if context.failure_reason is ProviderAccessFailure.SELECTION_REQUIRED:
        return True
    if not context.allowed:
        await edit_or_send(message, access_failure_message(context))
        return False
    return True


def _format_exact_datetime(value: datetime | None, timezone: str = "Asia/Baghdad") -> str:
    if value is None:
        return "لم يبدأ بعد"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ZoneInfo(timezone)).strftime("%d/%m/%Y — %I:%M %p")


def _mask_phone(value: str) -> str:
    value = (value or "").strip()
    if len(value) <= 5:
        return value or "غير مسجل"
    return f"{value[:3]}••••{value[-3:]}"


async def _owner_staff(user, provider: Provider) -> ProviderStaff:
    """Legacy factory retained for old admin flows; effective OWNER rights are computed."""
    staff = ProviderStaff(
        provider_id=provider.id,
        user_id=user.id,
        title="owner",
        role="OWNER",
        can_review_payments=True,
        can_manage_offers=True,
        can_manage_inventory=True,
        can_manage_branding=True,
        can_support=True,
        can_view_reports=True,
        can_manage_disputes=True,
        can_approve_refunds=True,
        can_view_finance=True,
        can_request_withdrawal=True,
        can_manage_payout_accounts=True,
        can_view_pii=True,
        can_export_data=True,
        is_active=True,
    )
    staff.provider = provider
    return staff


async def _staff_for_provider(
    session: AsyncSession,
    services: Services,
    telegram_id: int,
    provider_id: int,
):
    user = await services.users.get(session, telegram_id)
    context = await resolve_provider_access(
        session,
        services.settings,
        telegram_id,
        provider_id=int(provider_id),
        require_terms=True,
        allow_paused_provider=False,
    )
    if not context.allowed:
        return user, None
    return user, await effective_staff_view(session, context)


async def _staff(session: AsyncSession, services: Services, telegram_id: int):
    user = await services.users.get(session, telegram_id)
    context = await resolve_provider_access(
        session,
        services.settings,
        telegram_id,
        require_terms=True,
        allow_paused_provider=False,
    )
    session.info["campuspass_provider_access_context"] = context
    if not context.allowed:
        return user, None
    return user, await effective_staff_view(session, context)


async def _staff_rows(session: AsyncSession, services: Services, telegram_id: int):
    user = await services.users.get(session, telegram_id)
    context = await resolve_provider_access(
        session,
        services.settings,
        telegram_id,
        require_terms=True,
        allow_paused_provider=True,
    )
    return user, list(context.memberships)


@router.callback_query(F.data == "provider:dashboard")
async def provider_home(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    if not await _platform_entry_allowed(
        callback.message,
        session,
        services,
        settings,
        callback.from_user.id,
    ):
        return
    context = session.info.get("campuspass_provider_access_context")
    if context is None or not context.allowed:
        context = await resolve_provider_access(
            session, settings, callback.from_user.id, require_terms=True
        )
    if context.failure_reason is ProviderAccessFailure.SELECTION_REQUIRED:
        await edit_or_send(
            callback.message,
            "لديك أكثر من منصة. اختر المنصة التي تريد إدارتها:",
            reply_markup=provider_contexts_keyboard(context.selectable_memberships),
        )
        await state.clear()
        return
    if not context.allowed or context.active_provider is None:
        await edit_or_send(callback.message, access_failure_message(context))
        await state.clear()
        return
    await state.update_data(
        navigation_parent="platform",
        active_provider_id=context.active_provider.provider_id,
    )
    await edit_or_send(
        callback.message,
        f"🏢 <b>لوحة {safe(context.active_provider.provider_name)}</b>",
        reply_markup=provider_dashboard_keyboard(context),
        back_callback="back_to_main",
    )
    await state.clear()


@router.callback_query(F.data == "provider:choose")
async def provider_choose(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    if not await _platform_entry_allowed(
        callback.message,
        session,
        services,
        settings,
        callback.from_user.id,
    ):
        return
    _user, rows = await _staff_rows(session, services, callback.from_user.id)
    if not rows:
        await edit_or_send(callback.message, "لا توجد منصة مرتبطة بحسابك.")
        return
    await edit_or_send(callback.message, 
        "اختر المنصة التي تريد إدارتها:", reply_markup=provider_contexts_keyboard(rows)
    )


@router.callback_query(F.data.startswith("provider:select:"))
async def provider_select(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    if not await _platform_entry_allowed(
        callback.message,
        session,
        services,
        settings,
        callback.from_user.id,
    ):
        return
    user, rows = await _staff_rows(session, services, callback.from_user.id)
    try:
        provider_id = int((callback.data or "").split(":", 2)[2])
    except (TypeError, ValueError, IndexError):
        await callback_notice(callback, "زر منصة غير صالح أو قديم", show_alert=True)
        return
    selected = next((row for row in rows if row.provider_id == provider_id), None)
    if not user or not selected:
        await callback_notice(callback, "هذا الزر يعود إلى منصة غير مرتبطة بحسابك", show_alert=True)
        return
    await set_active_provider_selection(
        session,
        user_id=user.id,
        telegram_id=callback.from_user.id,
        provider_id=provider_id,
    )
    context = await resolve_provider_access(
        session,
        settings,
        callback.from_user.id,
        provider_id=provider_id,
        require_terms=True,
    )
    if context.failure_reason is ProviderAccessFailure.TERMS_REQUIRED:
        await _show_platform_terms(callback.message, settings)
        return
    if not context.allowed or context.active_provider is None:
        await edit_or_send(callback.message, access_failure_message(context))
        return
    await edit_or_send(
        callback.message,
        f"تم اختيار منصة <b>{safe(context.active_provider.provider_name)}</b> ✅",
        reply_markup=provider_dashboard_keyboard(context),
        back_callback="back_to_main",
    )


@router.callback_query(F.data == "provider:terms:accept")
async def provider_terms_accept(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    context = await resolve_provider_access(
        session,
        services.settings,
        callback.from_user.id,
        require_terms=False,
    )
    if context.failure_reason not in {
        ProviderAccessFailure.NONE,
        ProviderAccessFailure.SELECTION_REQUIRED,
    }:
        await edit_or_send(callback.message, access_failure_message(context))
        return
    user = await services.users.get_or_create(
        session,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name or "Telegram User",
    )
    user.has_platform_access = True  # compatibility marker; provider acceptance is authoritative.
    if context.active_provider is None:
        await edit_or_send(callback.message, "اختر المنصة أولاً ثم وافق على شروطها.")
        return
    await services.provider_operations.accept_terms(
        session,
        provider_id=context.active_provider.provider_id,
        user_id=user.id,
        version=services.settings.provider_terms_version,
        metadata={"telegram_id": callback.from_user.id},
    )
    await session.flush()
    invalidate_provider_access_cache(telegram_ids=(callback.from_user.id,))
    context = await resolve_provider_access(
        session,
        services.settings,
        callback.from_user.id,
        require_terms=True,
    )
    if context.failure_reason is ProviderAccessFailure.SELECTION_REQUIRED:
        await edit_or_send(
            callback.message,
            "تم قبول الشروط ✅\n\nاختر المنصة التي تريد إدارتها:",
            reply_markup=provider_contexts_keyboard(context.selectable_memberships),
        )
        await state.clear()
        return
    if not context.allowed or context.active_provider is None:
        await edit_or_send(callback.message, access_failure_message(context))
        await state.clear()
        return
    await edit_or_send(
        callback.message,
        f"تم قبول الشروط ✅\n\n🏢 <b>لوحة {safe(context.active_provider.provider_name)}</b>",
        reply_markup=provider_dashboard_keyboard(context),
        back_callback="back_to_main",
    )
    await state.clear()


@router.callback_query(F.data == "provider:terms:reject")
async def provider_terms_reject(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    await state.clear()
    if not callback.message or not callback.from_user:
        return
    user = await services.users.get(session, callback.from_user.id)
    if user is None:
        await edit_or_send(callback.message, "تم إلغاء العملية.")
        return
    from app.bot.handlers.start import send_home

    await send_home(callback.message, session, services, user, in_place=True)


async def _require_entitlement(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    staff: ProviderStaff | None,
    feature_key: str,
) -> bool:
    if not staff:
        return False
    result = await services.subscriptions.effective_entitlement(
        session, staff.provider_id, feature_key
    )
    if result.enabled:
        return True
    if callback.message:
        await edit_or_send(callback.message, 
            "هذه الخاصية غير متاحة في باقة المنصة الحالية أو انتهت صلاحيتها. "
            "يمكنكم استخدام كوبون أو التواصل مع الإدارة لترقية الباقة."
        )
    return False


@router.callback_query(F.data == "provider:orders")
async def provider_orders(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user, staff = await _staff(session, services, callback.from_user.id)
    if not await _require_entitlement(callback, session, services, staff, "orders.view"):
        return
    orders = list(
        (
            await session.scalars(
                select(Order)
                .where(Order.provider_id == staff.provider_id)
                .order_by(Order.created_at.desc())
                .limit(20)
            )
        ).all()
    )
    if not orders:
        await edit_or_send(callback.message, "لا توجد طلبات.")
        return
    await edit_or_send(callback.message, 
        "📦 <b>آخر طلبات المنصة</b>\nاختر طلبًا لعرض التفاصيل:",
        reply_markup=provider_orders_keyboard(orders),
    )


@router.callback_query(F.data.startswith("provider:order:"))
async def provider_order_details(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff:
        return
    order = await services.orders.get(session, int((callback.data or "").split(":")[2]))
    if not order or order.provider_id != staff.provider_id:
        await callback_notice(callback, "الطلب لا يخص هذه المنصة", show_alert=True)
        return

    dashboard = await services.student_subscriptions.provider_order_snapshot(session, order)
    profile = dashboard["profile"]
    subscription = dashboard["subscription"]
    timeline = await services.workflows.timeline(session, order)
    steps = "\n".join(
        ("🔵" if step["current"] else "✅" if step["done"] else "⚪") + " " + str(step["label"])
        for step in timeline
    )

    full_name = (profile.full_name if profile else order.user.telegram_name) or "غير مسجل"
    raw_phone = profile.phone if profile else ""
    phone = raw_phone if staff.can_view_pii else _mask_phone(raw_phone)
    cv_lines = [
        f"الاسم الكامل: <b>{safe(full_name)}</b>",
        f"الهاتف: <code>{safe(phone)}</code>",
        f"المحافظة: {safe(profile.governorate if profile else 'غير مسجلة')}",
        f"الجامعة: {safe(profile.university if profile else 'غير مسجلة')}",
        f"الكلية: {safe(profile.college if profile else 'غير مسجلة')}",
        f"القسم: {safe(profile.department if profile else 'غير مسجل')}",
        f"المرحلة: {safe(profile.stage if profile else 'غير مسجلة')}",
        f"التحقق: {'✅ موثّق' if profile and profile.is_verified else '⚪ غير موثّق'}",
    ]
    starts_at = _format_exact_datetime(dashboard["starts_at"], services.settings.timezone)
    ends_at = (
        _format_exact_datetime(dashboard["ends_at"], services.settings.timezone)
        if dashboard["ends_at"]
        else "غير محدد بعد"
    )
    subscription_id = f"#{subscription.id}" if subscription else "لم يُنشأ بعد"
    text = (
        f"📦 <b>تفاصيل الطلب</b>\n\n"
        f"الرقم: <code>{order.public_id}</code>\n"
        f"العرض: {safe(order.offer.title)}\n"
        f"حالة الطلب: <code>{order.status}</code>\n"
        f"الإجمالي: <b>{order.total_iqd:,} د.ع</b>\n"
        f"طريقة الدفع: {safe(order.payment_method.name if order.payment_method else 'غير محددة')}\n\n"
        f"👤 <b>ملف الطالب (CV)</b>\n" + "\n".join(cv_lines) +
        f"\n\n📅 <b>الاشتراك</b>\n"
        f"معرّف الاشتراك: <code>{subscription_id}</code>\n"
        f"الحالة: <code>{safe(str(dashboard['subscription_status']))}</code>\n"
        f"تاريخ ووقت البداية: <b>{safe(starts_at)}</b>\n"
        f"تاريخ ووقت النهاية: <b>{safe(ends_at)}</b>\n\n"
        f"<b>المراحل:</b>\n{steps}"
    )
    markup = (
        payment_review_keyboard(order.id)
        if order.status == OrderStatus.PAYMENT_REVIEW.value and staff.can_review_payments
        else InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎧 تذاكر دعم الطلب", callback_data="provider:tickets")],
                [InlineKeyboardButton(text="↩️ طلبات المنصة", callback_data="provider:orders")],
            ]
        )
    )
    await edit_or_send(callback.message, text, reply_markup=markup)


@router.callback_query(F.data == "provider:payments")
async def provider_payments(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_review_payments:
        return
    if not await _require_entitlement(callback, session, services, staff, "payments.review"):
        return
    orders = list(
        (
            await session.scalars(
                select(Order)
                .where(
                    Order.provider_id == staff.provider_id,
                    Order.status == OrderStatus.PAYMENT_REVIEW.value,
                )
                .order_by(Order.created_at)
            )
        ).all()
    )
    if not orders:
        await edit_or_send(callback.message, "لا توجد مدفوعات بانتظار التدقيق.")
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{o.public_id} — {o.total_iqd:,}",
                    callback_data=f"admin:order:{o.id}",
                    style="danger",
                )
            ]
            for o in orders[:20]
        ]
    )
    await edit_or_send(callback.message, "مدفوعات بانتظار التدقيق:", reply_markup=keyboard)


@router.callback_query(F.data == "provider:emails")
async def provider_emails(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not await _require_entitlement(callback, session, services, staff, "emails.manage"):
        return
    accounts = list(
        (
            await session.scalars(
                select(EmailAccount)
                .where(EmailAccount.provider_id == staff.provider_id)
                .order_by(EmailAccount.id.desc())
            )
        ).all()
    )
    lines = ["📧 <b>إيميلات المنصة المرتبطة بالعروض</b>"]
    for account in accounts:
        masked = services.reports._mask_email(account.username)
        lines.append(
            f"\n• {safe(account.label)} — {safe(masked)}\n"
            f"الاستخدام: {account.used_today}/{account.daily_limit} — {account.status}"
        )
    rows = [
        [
            InlineKeyboardButton(
                text="➕ ربط بريد بعرض", callback_data="provider:email_add", style="success"
            )
        ],
        [
            InlineKeyboardButton(
                text="↩️ لوحة المنصة", callback_data=f"provider:select:{staff.provider_id}"
            )
        ],
    ]
    await edit_or_send(callback.message, 
        "".join(lines) if accounts else "لا توجد إيميلات مربوطة بعد.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data == "provider:email_add")
async def provider_email_add(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not await _require_entitlement(callback, session, services, staff, "emails.manage"):
        return
    offers = list(
        (
            await session.scalars(
                select(Offer)
                .join(OfferActivationGuide, OfferActivationGuide.offer_id == Offer.id)
                .where(
                    Offer.provider_id == staff.provider_id,
                    OfferActivationGuide.activation_mode.in_(["email_code", "email_password_code"]),
                    OfferActivationGuide.is_active.is_(True),
                )
                .order_by(Offer.created_at.desc())
            )
        ).all()
    )
    if not offers:
        await edit_or_send(callback.message, 
            "لا يوجد عرض اختار طريقة تفعيل «دعوة أو رمز بالبريد» أو «حساب جاهز + رمز». "
            "أنشئ العرض أولًا ثم ارجع لربط البريد."
        )
        return
    await state.clear()
    await state.update_data(provider_id=staff.provider_id)
    await state.set_state(ProviderEmailStates.offer)
    await edit_or_send(callback.message, 
        "اختر العرض الذي يستقبل رموز البريد:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"📨 {offer.title}", callback_data=f"provider:email_offer:{offer.id}")]
                for offer in offers
            ]
            + [[InlineKeyboardButton(text="⬅️ رجوع", callback_data="provider:emails")]]
        ),
    )


@router.callback_query(F.data.startswith("provider:email_offer:"))
async def provider_email_offer(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    await state.update_data(email_offer_id=int((callback.data or "").split(":")[-1]))
    await state.set_state(ProviderEmailStates.provider_kind)
    await edit_or_send(callback.message, 
        "اختر نوع البريد. البوت سيملأ الخادم والمنفذ تلقائيًا:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔴 Gmail", callback_data="provider:email_kind:gmail")],
                [InlineKeyboardButton(text="🔵 Outlook / Hotmail", callback_data="provider:email_kind:outlook")],
                [InlineKeyboardButton(text="🟣 Yahoo", callback_data="provider:email_kind:yahoo")],
                [InlineKeyboardButton(text="⬅️ رجوع", callback_data="provider:email_add")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("provider:email_kind:"))
async def provider_email_kind(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    kind = (callback.data or "").split(":")[-1]
    presets = {
        "gmail": ("imap.gmail.com", 993),
        "outlook": ("outlook.office365.com", 993),
        "yahoo": ("imap.mail.yahoo.com", 993),
    }
    if kind not in presets:
        return
    host, port = presets[kind]
    await state.update_data(email_provider_kind=kind, email_host=host, email_port=port)
    await state.set_state(ProviderEmailStates.username)
    note = {
        "gmail": "استخدم App Password من Google، وليس كلمة المرور الرئيسية.",
        "outlook": "Microsoft قد يرفض كلمة المرور التقليدية؛ إذا فشل الاختبار فالحساب يحتاج OAuth أو إعدادات أمان مناسبة.",
        "yahoo": "استخدم App Password من Yahoo، وليس كلمة المرور الرئيسية.",
    }[kind]
    await edit_or_send(callback.message, f"اكتب عنوان البريد كاملًا.\n\n⚠️ {note}")


@router.message(ProviderEmailStates.username)
async def provider_email_username(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip().lower()
    if not validate_email_address(value):
        await message.answer("صيغة البريد غير صحيحة. مثال: name@gmail.com")
        return
    data = await state.get_data()
    kind = str(data.get("email_provider_kind") or "")
    domain = value.rsplit("@", 1)[-1]
    accepted = {
        "gmail": {"gmail.com", "googlemail.com"},
        "outlook": {"outlook.com", "hotmail.com", "live.com", "msn.com"},
        "yahoo": {"yahoo.com", "ymail.com", "rocketmail.com"},
    }
    if kind in accepted and domain not in accepted[kind]:
        await message.answer("الدومين لا يطابق نوع البريد الذي اخترته. ارجع واختر النوع الصحيح.")
        return
    await state.update_data(email_username=value)
    await state.set_state(ProviderEmailStates.secret)
    await message.answer(
        "أرسل App Password أو السر الخاص بالتطبيق. سيتم تشفيره ولن يظهر في لوحة الإدارة.\n"
        "لا ترسل كلمة مرورك الرئيسية إذا كان المزود يدعم App Password."
    )


def validate_email_address(value: str) -> bool:
    if len(value) > 255 or value.count("@") != 1:
        return False
    local, domain = value.split("@")
    return bool(local and "." in domain and " " not in value)


@router.message(ProviderEmailStates.secret, flags={"processing_immediate": True, "imap": True})
async def provider_email_secret(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    secret = (message.text or "").strip().replace(" ", "")
    if len(secret) < 6:
        await message.answer("السر قصير جدًا.")
        return
    data = await state.get_data()
    _user, staff = await _staff(session, services, message.from_user.id)
    if not staff or staff.provider_id != int(data.get("provider_id") or 0):
        await state.clear()
        return
    offer = await session.get(Offer, int(data.get("email_offer_id") or 0))
    if not offer or offer.provider_id != staff.provider_id:
        await state.clear()
        await message.answer("العرض غير موجود أو لا يخص منصتك.")
        return
    try:
        ok, result = await services.email_codes.test_connection(
            str(data["email_host"]),
            int(data["email_port"]),
            str(data["email_username"]),
            secret,
        )
    except Exception as exc:
        logger.warning("Provider IMAP test failed safely: %s", type(exc).__name__)
        ok, result = False, "تعذر اختبار البريد بسبب خطأ مؤقت"
    if not ok:
        # Reset the FSM completely so the provider is never trapped in the
        # password state after a timeout or authentication failure.
        await state.clear()
        await message.answer(
            f"❌ فشل ربط البريد:\n{safe(result)}\n\n"
            "تم إلغاء العملية بأمان. ابدأ إضافة البريد من جديد بعد التحقق من App Password وIMAP."
        )
        return
    duplicate = await session.scalar(
        select(EmailAccount.id).where(
            EmailAccount.provider_id == staff.provider_id,
            EmailAccount.offer_id == offer.id,
            EmailAccount.username == str(data["email_username"]),
        )
    )
    if duplicate:
        await state.clear()
        await message.answer("هذا البريد مربوط بالعرض مسبقًا.")
        return
    kind = str(data.get("email_provider_kind") or "imap")
    account = EmailAccount(
        provider_id=staff.provider_id,
        offer_id=offer.id,
        label=f"{offer.title[:60]} — {kind}",
        email_provider=kind,
        imap_host=str(data["email_host"]),
        imap_port=int(data["email_port"]),
        username=str(data["email_username"]),
        encrypted_secret=services.fulfillment.secrets.encrypt(secret),
        code_regex=r"\b(\d{4,8})\b",
        daily_limit=10,
        status=EmailAccountStatus.AVAILABLE.value,
    )
    session.add(account)
    if bool(data.get("activate_offer_after_email")):
        offer.status = "active"
        offer.is_active = True
        await services.offer_lifecycle.queue_launch_announcement(
            session, offer, staff.user_id
        )
    await state.clear()
    publish_note = "\n✅ تم نشر العرض وأصبح ظاهرًا للطلاب." if bool(data.get("activate_offer_after_email")) else ""
    await message.answer(
        f"✅ {safe(result)}\nتم تشفير البريد وربطه بالعرض <b>{safe(offer.title)}</b>.{publish_note}\n"
        "عند طلب الطالب رمزًا، البوت يبحث عن رسالة جديدة بعد وقت الطلب ولا يعيد استخدام الرمز.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📧 العودة للإيميلات", callback_data="provider:emails")]]
        ),
    )


@router.callback_query(F.data == "provider:report")
async def provider_report(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user, staff = await _staff(session, services, callback.from_user.id)
    if not await services.features.enabled(session, "reports", True):
        await edit_or_send(callback.message, "ميزة التقارير متوقفة حاليًا.")
        return
    if not user or not staff or not staff.can_view_reports:
        return
    if not await _require_entitlement(callback, session, services, staff, "reports.basic"):
        return
    await state.clear()
    await state.update_data(report_provider_id=staff.provider_id)
    await state.set_state(ProviderReportV5States.report_type)
    report_types = [
        ("📊 التقرير العام", "general"),
        ("🎓 تقرير الطلاب", "students"),
        ("💰 المبيعات والمشتريات", "sales"),
        ("🏫 الكليات والتخصصات", "academics"),
        ("📍 المحافظات", "governorates"),
        ("⭐ التقييمات ورضا الطلاب", "ratings"),
        ("🏦 السحوبات والمستحقات", "withdrawals"),
    ]
    await edit_or_send(callback.message, 
        "📊 اختر تقريرًا مستقلًا:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=label, callback_data=f"provider:report_type:{key}", style="primary")]
                for label, key in report_types
            ]
            + [[InlineKeyboardButton(text="⬅️ رجوع", callback_data=f"provider:select:{staff.provider_id}")]]
        ),
    )


@router.callback_query(F.data.startswith("provider:report_type:"))
async def provider_report_type(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    report_type = (callback.data or "").split(":")[-1]
    if report_type not in {"general", "students", "sales", "academics", "governorates", "ratings", "withdrawals"}:
        return
    await state.update_data(report_type=report_type)
    await state.set_state(ProviderReportV5States.period)
    await edit_or_send(callback.message, 
        "اختر فترة التقرير:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📅 يومي — آخر 24 ساعة", callback_data="provider:report_period:daily", style="primary")],
                [InlineKeyboardButton(text="📆 أسبوعي — آخر 7 أيام", callback_data="provider:report_period:weekly", style="primary")],
                [InlineKeyboardButton(text="🗓 شهري — آخر 30 يومًا", callback_data="provider:report_period:monthly", style="success")],
                [InlineKeyboardButton(text="🎯 مخصص", callback_data="provider:report_period:custom")],
                [InlineKeyboardButton(text="⬅️ رجوع", callback_data="provider:report")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("provider:report_period:"))
async def provider_report_period(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    period = (callback.data or "").split(":")[-1]
    data = await state.get_data()
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or staff.provider_id != int(data.get("report_provider_id") or 0):
        await state.clear()
        return
    if period == "custom":
        allowed = services.settings.is_admin(callback.from_user.id) or (
            await services.subscriptions.effective_entitlement(
                session, staff.provider_id, "reports.custom"
            )
        ).enabled
        if not allowed:
            await edit_or_send(callback.message, 
                "الفترة المخصصة يفتحها مالك البوت أو باقة تسمح بتقارير مخصصة."
            )
            return
        await state.update_data(report_period="custom")
        await state.set_state(ProviderReportV5States.custom_start)
        await edit_or_send(callback.message, "اكتب تاريخ البداية بصيغة <code>YYYY-MM-DD</code>:")
        return
    days = {"daily": 1, "weekly": 7, "monthly": 30}.get(period)
    if not days:
        return
    end = datetime.now(UTC)
    await state.update_data(
        report_period=period,
        report_start=(end - timedelta(days=days)).isoformat(),
        report_end=end.isoformat(),
    )
    await _ask_report_tier(callback.message, state, in_place=True)


@router.message(ProviderReportV5States.custom_start)
async def provider_report_custom_start(message: Message, state: FSMContext) -> None:
    try:
        start = datetime.strptime((message.text or "").strip(), "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        await message.answer("التاريخ غير صحيح. مثال: 2026-07-01")
        return
    if start > datetime.now(UTC):
        await message.answer("تاريخ البداية لا يكون في المستقبل.")
        return
    await state.update_data(report_start=start.isoformat())
    await state.set_state(ProviderReportV5States.custom_end)
    await message.answer("اكتب تاريخ النهاية بصيغة <code>YYYY-MM-DD</code>:")


@router.message(ProviderReportV5States.custom_end)
async def provider_report_custom_end(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    try:
        end = datetime.strptime((message.text or "").strip(), "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=UTC
        )
        start = datetime.fromisoformat(str(data["report_start"]))
    except (ValueError, KeyError):
        await message.answer("التاريخ غير صحيح.")
        return
    if end < start:
        await message.answer("تاريخ النهاية يجب أن يكون بعد البداية. استخدم ⬅️ رجوع للتصحيح.")
        return
    if (end - start).days > 366:
        await message.answer("الحد الأعلى للفترة المخصصة سنة واحدة.")
        return
    await state.update_data(report_end=end.isoformat())
    await _ask_report_tier(message, state)


async def _ask_report_tier(
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

    await state.set_state(ProviderReportV5States.tier)
    await render(
        "اختر مستوى التفاصيل:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🆓 Free — الملخص الأساسي", callback_data="provider:report_tier:free", style="primary")],
                [InlineKeyboardButton(text="➕ Plus — الأعلى مبيعًا ومقارنات", callback_data="provider:report_tier:plus", style="success")],
                [InlineKeyboardButton(text="💎 Pro — تحليل طلاب وكليات ومحافظات", callback_data="provider:report_tier:pro", style="success")],
                [InlineKeyboardButton(text="⬅️ رجوع للفترة", callback_data="provider:report_type_back")],
            ]
        ),
    )


@router.callback_query(F.data == "provider:report_type_back")
async def provider_report_type_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ProviderReportV5States.period)
    if callback.message:
        await edit_or_send(callback.message, "ارجع واضغط زر 📊 طلب تقرير لاختيار الفترة من جديد.")


@router.callback_query(F.data.startswith("provider:report_tier:"), flags={"processing_immediate": True, "report": True})
async def provider_report_generate(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    tier = (callback.data or "").split(":")[-1]
    if tier not in {"free", "plus", "pro"}:
        return
    data = await state.get_data()
    user, staff = await _staff(session, services, callback.from_user.id)
    if not user or not staff or staff.provider_id != int(data.get("report_provider_id") or 0):
        await state.clear()
        return
    feature = await services.pricing.feature_price(
        session,
        "reports.standard" if tier == "free" else f"reports.{tier}",
        {"free": "تقارير Free", "plus": "تقارير Plus", "pro": "تقارير Pro"}[tier],
    )
    is_bot_admin = settings.is_admin(callback.from_user.id)
    if feature.billing_mode == FeatureBillingMode.HIDDEN.value and not is_bot_admin:
        await edit_or_send(callback.message, "هذا المستوى مخفي بواسطة مالك البوت.")
        return
    if feature.billing_mode not in {
        FeatureBillingMode.FREE.value,
        FeatureBillingMode.TRIAL.value,
    } and not is_bot_admin:
        entitlement = await services.subscriptions.effective_entitlement(
            session, staff.provider_id, "reports.standard" if tier == "free" else f"reports.{tier}"
        )
        if not entitlement.enabled:
            price_key = "report_standard_monthly" if tier == "free" else f"report_{tier}_monthly"
            price = await services.pricing.get_system_price(session, price_key, 0)
            await edit_or_send(callback.message, 
                f"💎 هذا المستوى مدفوع. السعر الذي حدده المالك: <b>{price:,} د.ع شهريًا</b>. "
                "يجب تفعيله ضمن اشتراك المنصة."
            )
            return
    provider = await session.get(Provider, staff.provider_id)
    if not provider:
        return
    try:
        start = datetime.fromisoformat(str(data["report_start"]))
        end = datetime.fromisoformat(str(data["report_end"]))
    except (KeyError, ValueError):
        await edit_or_send(callback.message, "انتهت بيانات الفترة. ابدأ التقرير من جديد.")
        await state.clear()
        return
    report_type = str(data.get("report_type") or "general")
    try:
        report, token = await services.reports.create_provider_report(
            session,
            provider,
            start,
            end,
            user.id,
            report_type=report_type,
            tier=tier,
        )
    except ValueError as exc:
        await edit_or_send(callback.message, str(exc))
        return
    verification_url = services.reports.report_url(token) if settings.public_base_url else ""
    title = safe(report.snapshot["report_meta"]["title"])
    if tier == "free":
        await callback.message.answer(services.reports.free_message(report))
    elif tier == "plus":
        artifact = await asyncio.to_thread(
            services.reports.render_artifact, report, verification_url=verification_url, format="html"
        )
        await services.reports.record_artifact(session, report, artifact)
        await callback.message.answer_document(
            BufferedInputFile(artifact.content, filename=artifact.filename),
            caption=f"📊 <b>{title}</b>\nالمستوى: Plus\nتقرير HTML منسق بهوية المنصة.",
        )
    else:
        try:
            artifact = await asyncio.to_thread(
                services.reports.render_artifact, report, verification_url=verification_url, format="pdf"
            )
        except Exception:
            await edit_or_send(callback.message, "تعذر توليد PDF الآن. احتفظنا بالتقرير الآمن ويمكن إعادة المحاولة.")
        else:
            await services.reports.record_artifact(session, report, artifact)
            await callback.message.answer_document(
                BufferedInputFile(artifact.content, filename=artifact.filename),
                caption=f"📊 <b>{title}</b>\nالمستوى: Pro\nتقرير PDF رسمي A4 بهوية CampusPass IQ والمنصة.",
            )
    await state.clear()
    if settings.public_base_url and tier in {"plus", "pro"}:
        label = "🌐 فتح لوحة التقرير" if tier == "pro" else "🌐 فتح التقرير"
        url = f"{verification_url}/dashboard" if tier == "pro" else verification_url
        await edit_or_send(callback.message, "الرابط الآمن للتقرير:", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=label, url=url, style="primary")]]
        ))


@router.callback_query(F.data == "provider:finance")
async def provider_finance(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff:
        await edit_or_send(callback.message, "لا توجد منصة مرتبطة بحسابك.")
        return
    if not staff.can_view_finance and not settings.is_admin(callback.from_user.id):
        await edit_or_send(callback.message, "ليس لديك صلاحية عرض المعلومات المالية.")
        return
    if not settings.provider_withdrawals_ready:
        await edit_or_send(callback.message,
            "💳 <b>طلبات السحب مفعلة وتنتظر الإعداد</b>\n\n"
            "أكمل ربط بوابة الدفع المركزية واضبط MONEY_FLOW_MODEL=gateway_marketplace "
            "حتى يصبح الرصيد قابلاً للسحب بأمان."
        )
        return
    if not await _require_entitlement(
        callback, session, services, staff, "withdrawals.request"
    ):
        return
    balance = await services.finance.provider_balance(session, staff.provider_id)
    await edit_or_send(callback.message, 
        f"💰 الرصيد المتاح: <b>{balance:,} د.ع</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="طلب سحب",
                        callback_data=f"withdraw:start:{staff.provider_id}",
                        style="success",
                    )
                ]
            ]
        ),
    )


@router.callback_query(F.data.startswith("withdraw:start:"))
async def withdrawal_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user:
        return
    provider_id = int((callback.data or "").split(":")[2])
    try:
        await services.authorization.require_withdrawal_permission(
            session, callback.from_user.id, provider_id
        )
    except Exception as exc:
        await callback_notice(callback, str(exc), show_alert=True)
        return
    await state.clear()
    await state.update_data(withdraw_provider_id=provider_id)
    await state.set_state(WithdrawalStates.amount)
    if callback.message:
        await edit_or_send(callback.message, "اكتب مبلغ السحب بالدينار:")


@router.message(WithdrawalStates.amount)
async def withdrawal_amount(message: Message, state: FSMContext) -> None:
    amount = parse_money(message.text or "")
    if not amount:
        await message.answer("اكتب مبلغًا صحيحًا.")
        return
    await state.update_data(withdraw_amount=amount)
    await state.set_state(WithdrawalStates.method)
    await message.answer("اكتب طريقة الاستلام، مثال: زين كاش أو بطاقة:")


@router.message(WithdrawalStates.method)
async def withdrawal_method(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if len(value) < 2:
        return
    await state.update_data(withdraw_method=value)
    await state.set_state(WithdrawalStates.destination)
    await message.answer("اكتب رقم الحساب أو البطاقة المستلمة:")


@router.message(WithdrawalStates.destination)
async def withdrawal_destination(
    message: Message, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    user, staff = await _staff(session, services, message.from_user.id)
    provider_id = int(data["withdraw_provider_id"])
    if not user or not staff or staff.provider_id != provider_id:
        await state.clear()
        return
    try:
        await services.authorization.require_withdrawal_permission(
            session, message.from_user.id, provider_id
        )
        request = await services.finance.request_withdrawal(
            session,
            staff.provider_id,
            user,
            int(data["withdraw_amount"]),
            str(data["withdraw_method"]),
            (message.text or "").strip(),
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(f"تم إرسال طلب السحب <code>{request.public_id}</code> ✅")
    await services.notifications.send_admins(
        f"💰 طلب سحب جديد\n{request.public_id}\nالمبلغ: {request.amount_iqd:,} د.ع"
    )


@router.callback_query(F.data == "provider:tickets")
async def provider_tickets(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not await _require_entitlement(callback, session, services, staff, "support.manage"):
        return
    tickets = list(
        (
            await session.scalars(
                select(SupportTicket)
                .where(
                    SupportTicket.provider_id == staff.provider_id,
                    SupportTicket.status.not_in(["closed", "resolved"]),
                )
                .order_by(SupportTicket.updated_at.desc())
                .limit(30)
            )
        ).all()
    )
    if not tickets:
        await edit_or_send(callback.message, "لا توجد تذاكر مفتوحة.")
        return
    rows = [
        [
            InlineKeyboardButton(
                text=f"🎫 {ticket.public_id} — {ticket.subject[:35]}",
                callback_data=f"provider:ticket:{ticket.id}",
                style="primary",
            )
        ]
        for ticket in tickets
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="↩️ لوحة المنصة", callback_data=f"provider:select:{staff.provider_id}"
            )
        ]
    )
    await edit_or_send(callback.message, 
        f"🎫 التذاكر المفتوحة: {len(tickets)}\nاختر تذكرة لعرضها والرد عليها:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data == "provider:subscription")
async def provider_subscription(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _user, staff = await _staff(session, services, callback.from_user.id)
    if not staff:
        return
    provider = await session.get(Provider, staff.provider_id)
    if not provider:
        return
    subscription = await services.subscriptions.ensure_subscription(session, provider)
    percent = await services.subscriptions.effective_management_percent(session, provider)
    plan = subscription.plan
    ends = (
        subscription.ends_at.astimezone().strftime("%Y-%m-%d %H:%M")
        if subscription.ends_at
        else "غير محدد"
    )
    grace = (
        subscription.grace_until.astimezone().strftime("%Y-%m-%d %H:%M")
        if subscription.grace_until
        else "غير محدد"
    )
    feature_lines = []
    for key in (
        "reports.basic",
        "reports.advanced",
        "emails.manage",
        "inventory.manage",
        "staff.manage",
        "broadcasts.send",
    ):
        result = await services.subscriptions.effective_entitlement(session, provider.id, key)
        feature_lines.append(f"{'✅' if result.enabled else '❌'} {key}")
    await edit_or_send(callback.message, 
        f"💼 <b>اشتراك {safe(provider.name_ar)}</b>\n\n"
        f"الباقة: <b>{safe(plan.name_ar if plan else 'غير محددة')}</b>\n"
        f"الحالة: <code>{subscription.status}</code>\n"
        f"تجربة: {'نعم' if subscription.is_trial else 'لا'}\n"
        f"ينتهي: {ends}\n"
        f"فترة السماح: {grace}\n"
        f"عمولة الإدارة الحالية: {percent}%\n\n"
        "<b>أهم الخصائص:</b>\n" + "\n".join(feature_lines)
    )


@router.callback_query(F.data == "provider:coupon")
async def provider_coupon_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if not callback.message:
        return
    await state.clear()
    await state.set_state(ProviderCouponStates.code)
    await edit_or_send(callback.message, "اكتب رمز الكوبون:")


@router.message(ProviderCouponStates.code)
async def provider_coupon_redeem(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    user, staff = await _staff(session, services, message.from_user.id)
    if not user or not staff:
        await state.clear()
        return
    provider = await session.get(Provider, staff.provider_id)
    if not provider:
        await state.clear()
        return
    try:
        result = await services.subscriptions.redeem_coupon(
            session, provider, message.text or "", user
        )
    except ValueError as exc:
        return await message.answer(str(exc))
    await state.clear()
    await message.answer(f"{safe(result)} ✅")


# ---------------------------------------------------------------------------
# V8.1 provider payment of CampusPass fees (MasterCard proof only)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.regexp(r"^provider:settlement:\d+$"))
async def provider_settlement_details(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.message:
        return
    user, staff = await _staff(session, services, callback.from_user.id)
    settlement = await session.get(ProviderSettlement, int(callback.data.rsplit(":", 1)[1]))
    if not user or not staff or not settlement or staff.provider_id != settlement.provider_id:
        return await callback_notice(callback, "غير مصرح لهذا الطلب.", show_alert=True)
    if not staff.can_view_finance:
        return await callback_notice(callback, "لا تملك صلاحية المالية.", show_alert=True)
    provider = await session.get(Provider, settlement.provider_id)
    await edit_or_send(callback.message, 
        f"💳 <b>رسوم CampusPass المطلوبة</b>\n\n"
        f"المنصة: {safe(provider.name_ar if provider else settlement.provider_id)}\n"
        f"رقم الطلب: <code>{settlement.public_id}</code>\n"
        f"المبلغ: <b>{settlement.remaining_due_iqd:,} د.ع</b>\n"
        f"الحالة: <code>{settlement.status}</code>\n\n"
        "طريقة الإثبات المعتمدة هنا: <b>MasterCard فقط</b>. بعد التحويل أرسل صورة الوصل.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📸 إرسال وصل MasterCard",
                callback_data=f"provider:settlement_proof:{settlement.id}",
                style="primary",
            )],
            [InlineKeyboardButton(text="↩️ لوحة المنصة", callback_data="back_to_platform")],
        ]),
    )


@router.callback_query(F.data.regexp(r"^provider:settlement_proof:\d+$"))
async def provider_settlement_proof_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.message:
        return
    user, staff = await _staff(session, services, callback.from_user.id)
    settlement = await session.get(ProviderSettlement, int(callback.data.rsplit(":", 1)[1]))
    if not user or not staff or not settlement or staff.provider_id != settlement.provider_id or not staff.can_view_finance:
        return await callback_notice(callback, "غير مصرح.", show_alert=True)
    await state.clear()
    await state.update_data(provider_settlement_id=settlement.id)
    await state.set_state(ProviderSettlementProofStates.proof)
    await edit_or_send(callback.message, 
        "أرسل الآن <b>صورة وصل MasterCard فقط</b>. لا ترسل رقم البطاقة أو CVV أو رمز تحقق."
    )


@router.message(ProviderSettlementProofStates.proof)
async def provider_settlement_proof_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    user, staff = await _staff(session, services, message.from_user.id)
    data = await state.get_data()
    settlement = await session.get(ProviderSettlement, int(data.get("provider_settlement_id", 0)))
    if not user or not staff or not settlement or staff.provider_id != settlement.provider_id or not staff.can_view_finance:
        await state.clear()
        return await message.answer("تعذر التحقق من صلاحيتك لهذا الطلب.")
    if not message.photo:
        return await message.answer("أرسل صورة وصل MasterCard فقط.")
    file_id = message.photo[-1].file_id
    await services.settlements.submit_proof(
        session, settlement, user.id, file_id, "mastercard"
    )
    await state.clear()
    provider = await session.get(Provider, settlement.provider_id)
    review_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تأكيد", callback_data=f"admin:collection_approve:{settlement.id}", style="success")],
        [InlineKeyboardButton(text="❌ رفض", callback_data=f"admin:collection_reject:{settlement.id}", style="danger")],
        [InlineKeyboardButton(text="🚫 حظر المنصة", callback_data=f"admin:collection_ban:{settlement.id}", style="danger")],
    ])
    for admin_id in services.settings.admin_ids:
        try:
            await message.bot.send_photo(
                admin_id,
                file_id,
                caption=(
                    f"💳 <b>وصل رسوم CampusPass</b>\n"
                    f"المنصة: {safe(provider.name_ar if provider else settlement.provider_id)}\n"
                    f"Provider ID: <code>{settlement.provider_id}</code>\n"
                    f"الطلب: <code>{settlement.public_id}</code>\n"
                    f"المبلغ المطلوب: <b>{settlement.remaining_due_iqd:,} د.ع</b>"
                ),
                reply_markup=review_markup,
            )
        except Exception:
            pass
    await message.answer(
        "✅ تم إرسال الوصل إلى مالك البوت للمراجعة. ستصلك نتيجة التأكيد أو الرفض هنا."
    )
