from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin.common import admin_actor, admin_back, require_admin
from app.bot.states import (
    AdminCommissionOverrideStates,
    AdminCouponStates,
    AdminFeatureTemporaryStates,
    AdminSubscriptionExtendStates,
    AdminSubscriptionLimitStates,
    AdminSubscriptionPriceStates,
    AdminSubscriptionTrialStates,
)
from app.bot.ui import edit_or_send, callback_notice
from app.core.config import Settings
from app.core.utils import safe
from app.db.models import (
    CouponKind,
    Provider,
    ProviderCoupon,
    ProviderFeatureOverride,
    ProviderSubscriptionStatus,
    SubscriptionChangeLog,
    SubscriptionPlan,
)
from app.services.container import Services
from app.services.subscriptions import (
    FEATURE_LABELS,
    FEATURES,
    LIMIT_LABELS,
    LIMITS,
    feature_key_from_token,
    feature_token,
    limit_key_from_token,
    limit_token,
)

router = Router(name="admin_subscriptions")


def _dt(value: datetime | None) -> str:
    if not value:
        return "غير محدد"
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _subscription_keyboard(provider_id: int, paused: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎁 تجربة 7 أيام",
                    callback_data=f"admin:subtrial:{provider_id}:7",
                    style="success",
                ),
                InlineKeyboardButton(
                    text="🎁 مدة مخصصة",
                    callback_data=f"admin:subtrial_custom:{provider_id}",
                    style="success",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📦 تغيير الباقة",
                    callback_data=f"admin:subplans:{provider_id}",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="📅 تمديد",
                    callback_data=f"admin:subextend_menu:{provider_id}",
                    style="primary",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔓 الخصائص",
                    callback_data=f"admin:subfeatures:{provider_id}",
                    style="success",
                ),
                InlineKeyboardButton(
                    text="📊 الحدود",
                    callback_data=f"admin:sublimits:{provider_id}",
                    style="primary",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⏱ خاصية مؤقتة",
                    callback_data=f"admin:subfeature_temp:{provider_id}",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="💰 سعر مخصص",
                    callback_data=f"admin:subprice:{provider_id}",
                    style="success",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💸 عمولة مؤقتة",
                    callback_data=f"admin:subcommission:{provider_id}",
                    style="danger",
                ),
                InlineKeyboardButton(
                    text="🧾 سجل التغييرات",
                    callback_data=f"admin:sublogs:{provider_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="▶️ استئناف" if paused else "⏸ تعليق",
                    callback_data=f"admin:subpause:{provider_id}",
                    style="success" if paused else "danger",
                )
            ],
            [InlineKeyboardButton(text="↩️ المنصة", callback_data=f"admin:provider:{provider_id}")],
        ]
    )


async def _render_subscription_details(
    message: Message,
    provider: Provider,
    subscription,
    management_percent: int,
) -> None:
    plan = subscription.plan
    price = subscription.custom_price_iqd
    if price is None:
        price = plan.price_iqd if plan else 0
    text = (
        f"💼 <b>اشتراك {safe(provider.name_ar)}</b>\n\n"
        f"الباقة: <b>{safe(plan.name_ar if plan else 'غير محددة')}</b>\n"
        f"الحالة: <code>{subscription.status}</code>\n"
        f"تجربة مجانية: {'نعم' if subscription.is_trial else 'لا'}\n"
        f"السعر المعتمد: {price:,} د.ع\n"
        f"البداية: {_dt(subscription.starts_at)}\n"
        f"النهاية: {_dt(subscription.ends_at)}\n"
        f"فترة السماح حتى: {_dt(subscription.grace_until)}\n"
        f"عمولة الإدارة الفعلية: {management_percent}%\n"
        f"التجديد التلقائي: {'مفعل' if subscription.auto_renew else 'متوقف'}"
    )
    await edit_or_send(
        message,
        text,
        reply_markup=_subscription_keyboard(
            provider.id, subscription.status == ProviderSubscriptionStatus.PAUSED.value
        ),
    )


@router.callback_query(F.data.regexp(r"^admin:provider_sub:\d+$"))
async def subscription_details(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    provider_id = int(callback.data.split(":")[2])
    provider = await session.get(Provider, provider_id)
    if not provider:
        return await edit_or_send(callback.message, "المنصة غير موجودة.")
    actor = await admin_actor(session, services, callback)
    subscription = await services.subscriptions.ensure_subscription(session, provider, actor)
    percent = await services.subscriptions.effective_management_percent(session, provider)
    await _render_subscription_details(callback.message, provider, subscription, percent)


@router.callback_query(F.data.regexp(r"^admin:subplans:\d+$"))
async def choose_plan(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    provider_id = int(callback.data.split(":")[2])
    plans = await services.subscriptions.list_plans(session)
    rows = [
        [
            InlineKeyboardButton(
                text=f"{plan.name_ar} — {plan.price_iqd:,} د.ع / {plan.billing_days} يوم",
                callback_data=f"admin:subplan:{provider_id}:{plan.id}",
                style="success" if plan.code == "pro" else "primary",
            )
        ]
        for plan in plans
    ]
    rows.append(
        [InlineKeyboardButton(text="↩️ الاشتراك", callback_data=f"admin:provider_sub:{provider_id}")]
    )
    await edit_or_send(callback.message, 
        "اختر الباقة. يبدأ الاشتراك من لحظة التفعيل وتطبق فترة السماح التابعة للباقة:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("admin:subplan:"))
async def assign_plan(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings):
        return
    _, _, provider_id_text, plan_token = (callback.data or "").split(":", 3)
    provider = await session.get(Provider, int(provider_id_text))
    if plan_token.isdecimal():
        plan = await session.get(SubscriptionPlan, int(plan_token))
        code = plan.code if plan else ""
    else:
        code = plan_token  # legacy callback compatibility
    actor = await admin_actor(session, services, callback)
    if not provider or not code:
        if callback.message:
            await edit_or_send(callback.message, "المنصة أو الباقة غير موجودة.")
        return
    try:
        subscription = await services.subscriptions.assign_plan(
            session, provider, code, actor, reason="تغيير الباقة من لوحة الإدارة"
        )
    except ValueError as exc:
        if callback.message:
            await edit_or_send(callback.message, str(exc))
        return
    if callback.message:
        await edit_or_send(
            callback.message,
            f"تم تفعيل باقة <b>{safe(subscription.plan.name_ar)}</b> للمنصة ✅",
            reply_markup=_subscription_keyboard(provider.id, False),
        )


@router.callback_query(F.data.regexp(r"^admin:subtrial:\d+:\d+$"))
async def grant_trial_preset(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings):
        return
    _, _, provider_id_text, days_text = callback.data.split(":")
    provider = await session.get(Provider, int(provider_id_text))
    actor = await admin_actor(session, services, callback)
    if not provider:
        return await callback_notice(callback, "المنصة غير موجودة", show_alert=True)
    try:
        await services.subscriptions.grant_trial(
            session,
            provider,
            int(days_text),
            actor,
            plan_code=settings.default_trial_plan,
        )
    except ValueError as exc:
        return await callback_notice(callback, str(exc), show_alert=True)
    await callback_notice(callback, f"تم منح {days_text} أيام مجانية", show_alert=True)


@router.callback_query(F.data.regexp(r"^admin:subtrial_custom:\d+$"))
async def trial_custom_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.update_data(provider_id=int(callback.data.split(":")[2]))
    await state.set_state(AdminSubscriptionTrialStates.days)
    await edit_or_send(callback.message, "اكتب عدد أيام التجربة المجانية من 1 إلى 365:")


@router.message(AdminSubscriptionTrialStates.days)
async def trial_custom_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    try:
        days = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب عدد الأيام بالأرقام.")
    data = await state.get_data()
    provider = await session.get(Provider, int(data["provider_id"]))
    actor = await admin_actor(session, services, message)
    if not provider:
        await state.clear()
        return await message.answer("المنصة غير موجودة.")
    try:
        await services.subscriptions.grant_trial(
            session,
            provider,
            days,
            actor,
            plan_code=settings.default_trial_plan,
        )
    except ValueError as exc:
        return await message.answer(str(exc))
    await state.clear()
    await message.answer(
        f"تم منح {days} يومًا مجانًا لمنصة {safe(provider.name_ar)} ✅",
        reply_markup=admin_back(),
    )


@router.callback_query(F.data.regexp(r"^admin:subextend_menu:\d+$"))
async def extend_menu(callback: CallbackQuery, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    provider_id = int(callback.data.split(":")[2])
    await edit_or_send(callback.message, 
        "اختر مدة التمديد:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="7 أيام", callback_data=f"admin:subextend:{provider_id}:7"
                    ),
                    InlineKeyboardButton(
                        text="30 يومًا",
                        callback_data=f"admin:subextend:{provider_id}:30",
                        style="success",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="90 يومًا",
                        callback_data=f"admin:subextend:{provider_id}:90",
                        style="primary",
                    ),
                    InlineKeyboardButton(
                        text="مدة مخصصة",
                        callback_data=f"admin:subextend_custom:{provider_id}",
                    ),
                ],
            ]
        ),
    )


@router.callback_query(F.data.regexp(r"^admin:subextend:\d+:\d+$"))
async def extend_preset(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings):
        return
    _, _, provider_id_text, days_text = callback.data.split(":")
    provider = await session.get(Provider, int(provider_id_text))
    actor = await admin_actor(session, services, callback)
    if not provider:
        return await callback_notice(callback, "المنصة غير موجودة", show_alert=True)
    await services.subscriptions.extend(session, provider, int(days_text), actor)
    await callback_notice(callback, f"تم التمديد {days_text} يومًا", show_alert=True)


@router.callback_query(F.data.regexp(r"^admin:subextend_custom:\d+$"))
async def extend_custom_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.update_data(provider_id=int(callback.data.split(":")[2]))
    await state.set_state(AdminSubscriptionExtendStates.days)
    await edit_or_send(callback.message, "اكتب عدد أيام التمديد من 1 إلى 1095:")


@router.message(AdminSubscriptionExtendStates.days)
async def extend_custom_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    try:
        days = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب عدد الأيام بالأرقام.")
    data = await state.get_data()
    provider = await session.get(Provider, int(data["provider_id"]))
    actor = await admin_actor(session, services, message)
    if not provider:
        await state.clear()
        return await message.answer("المنصة غير موجودة.")
    try:
        await services.subscriptions.extend(session, provider, days, actor)
    except ValueError as exc:
        return await message.answer(str(exc))
    await state.clear()
    await message.answer(f"تم تمديد الاشتراك {days} يومًا ✅", reply_markup=admin_back())


@router.callback_query(F.data.regexp(r"^admin:subpause:\d+$"))
async def pause_subscription(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    provider = await session.get(Provider, int(callback.data.split(":")[2]))
    actor = await admin_actor(session, services, callback)
    if not provider:
        return await edit_or_send(callback.message, "المنصة غير موجودة.")
    subscription = await services.subscriptions.ensure_subscription(session, provider, actor)
    paused = subscription.status != ProviderSubscriptionStatus.PAUSED.value
    subscription = await services.subscriptions.set_paused(
        session, provider, paused, actor, "تغيير من لوحة الإدارة"
    )
    percent = await services.subscriptions.effective_management_percent(session, provider)
    await _render_subscription_details(callback.message, provider, subscription, percent)


async def _active_override(
    session: AsyncSession, provider_id: int, feature_key: str
) -> ProviderFeatureOverride | None:
    now = datetime.now(UTC)
    return await session.scalar(
        select(ProviderFeatureOverride)
        .where(
            ProviderFeatureOverride.provider_id == provider_id,
            ProviderFeatureOverride.feature_key == feature_key,
            ProviderFeatureOverride.valid_from <= now,
            or_(
                ProviderFeatureOverride.valid_until.is_(None),
                ProviderFeatureOverride.valid_until >= now,
            ),
        )
        .order_by(ProviderFeatureOverride.created_at.desc())
        .limit(1)
    )


async def _render_feature_overrides(
    message: Message,
    session: AsyncSession,
    services: Services,
    provider_id: int,
) -> None:
    rows: list[list[InlineKeyboardButton]] = []
    for definition in FEATURES:
        result = await services.subscriptions.effective_entitlement(
            session, provider_id, definition.key
        )
        override = await _active_override(session, provider_id, definition.key)
        if override and override.enabled_override is True:
            marker = "🟢 خاص"
        elif override and override.enabled_override is False:
            marker = "🔴 مغلق"
        else:
            marker = "✅ باقة" if result.enabled else "❌ باقة"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{marker} — {definition.label}",
                    callback_data=f"admin:subfeature_cycle:{provider_id}:{feature_token(definition.key)}",
                    style="success" if result.enabled else "danger",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="↩️ الاشتراك", callback_data=f"admin:provider_sub:{provider_id}")]
    )
    await edit_or_send(
        message,
        "🔓 <b>خصائص المنصة</b>\n\n"
        "الضغط على الخاصية يبدلها بهذا الترتيب: فتح خاص ← إغلاق خاص ← وراثة من الباقة.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.regexp(r"^admin:subfeatures:\d+$"))
async def feature_overrides(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await _render_feature_overrides(
        callback.message, session, services, int(callback.data.split(":")[2])
    )


@router.callback_query(F.data.startswith("admin:subfeature_cycle:"))
async def cycle_feature(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    _, _, provider_id_text, feature_token_value = (callback.data or "").split(":", 3)
    feature_key = feature_key_from_token(feature_token_value)
    provider = await session.get(Provider, int(provider_id_text))
    actor = await admin_actor(session, services, callback)
    if not provider or feature_key not in FEATURE_LABELS:
        return await edit_or_send(callback.message, "بيانات الخاصية غير صحيحة.")
    override = await _active_override(session, provider.id, feature_key)
    if not override or override.enabled_override is None:
        next_value: bool | None = True
    elif override.enabled_override is True:
        next_value = False
    else:
        next_value = None
    await services.subscriptions.set_feature_override(
        session,
        provider,
        feature_key,
        next_value,
        actor,
        reason="تعديل يدوي من لوحة الإدارة",
    )
    await session.flush()
    await _render_feature_overrides(callback.message, session, services, provider.id)


@router.callback_query(F.data.regexp(r"^admin:sublimits:\d+$"))
async def limits_list(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    provider_id = int(callback.data.split(":")[2])
    rows: list[list[InlineKeyboardButton]] = []
    for definition in LIMITS:
        result = await services.subscriptions.effective_entitlement(
            session, provider_id, definition.key
        )
        value = (
            "غير محدود"
            if result.limit == -1
            else (str(result.limit) if result.limit is not None else "غير محدد")
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{definition.label}: {value}",
                    callback_data=f"admin:sublimit_set:{provider_id}:{limit_token(definition.key)}",
                    style="primary",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="↩️ الاشتراك", callback_data=f"admin:provider_sub:{provider_id}")]
    )
    await edit_or_send(callback.message, 
        "📊 <b>حدود المنصة</b>\nاكتب -1 لغير محدود، أو كلمة inherit لإلغاء الاستثناء.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("admin:sublimit_set:"))
async def limit_set_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    _, _, provider_id_text, limit_token_value = (callback.data or "").split(":", 3)
    limit_key = limit_key_from_token(limit_token_value)
    if not limit_key:
        return await callback_notice(callback, "الحد غير معروف", show_alert=True)
    await state.clear()
    await state.update_data(provider_id=int(provider_id_text), limit_key=limit_key)
    await state.set_state(AdminSubscriptionLimitStates.value)
    await edit_or_send(callback.message, 
        f"اكتب القيمة الجديدة لـ <b>{safe(LIMIT_LABELS[limit_key])}</b>.\n"
        "-1 = غير محدود\ninherit = العودة إلى حد الباقة"
    )


@router.message(AdminSubscriptionLimitStates.value)
async def limit_set_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    raw = (message.text or "").strip().lower()
    value: int | None
    if raw in {"inherit", "وراثة", "الغاء", "إلغاء"}:
        value = None
    else:
        try:
            value = int(raw)
        except ValueError:
            return await message.answer("اكتب رقمًا، أو inherit.")
        if value < -1:
            return await message.answer("أقل قيمة مسموحة هي -1.")
    data = await state.get_data()
    provider = await session.get(Provider, int(data["provider_id"]))
    actor = await admin_actor(session, services, message)
    if not provider:
        await state.clear()
        return await message.answer("المنصة غير موجودة.")
    if value is None:
        await services.subscriptions.set_limit_override(
            session,
            provider,
            str(data["limit_key"]),
            None,
            actor,
            reason="العودة إلى حد الباقة",
        )
        await state.clear()
        return await message.answer("تمت العودة إلى حد الباقة ✅", reply_markup=admin_back())
    await state.update_data(limit_value=value)
    await state.set_state(AdminSubscriptionLimitStates.days)
    await message.answer("اكتب مدة الاستثناء بالأيام، أو 0 ليكون دائمًا:")


@router.message(AdminSubscriptionLimitStates.days)
async def limit_set_days(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    try:
        days = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب عدد الأيام بالأرقام.")
    if not 0 <= days <= 1095:
        return await message.answer("المدة من 0 إلى 1095 يومًا.")
    data = await state.get_data()
    provider = await session.get(Provider, int(data["provider_id"]))
    actor = await admin_actor(session, services, message)
    if not provider:
        await state.clear()
        return await message.answer("المنصة غير موجودة.")
    await services.subscriptions.set_limit_override(
        session,
        provider,
        str(data["limit_key"]),
        int(data["limit_value"]),
        actor,
        days=days or None,
        reason="حد مخصص من لوحة الإدارة",
    )
    await state.clear()
    await message.answer("تم تحديث الحد ✅", reply_markup=admin_back())


@router.callback_query(F.data.regexp(r"^admin:subfeature_temp:\d+$"))
async def temporary_feature_list(
    callback: CallbackQuery,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    provider_id = int(callback.data.split(":")[2])
    rows = [
        [
            InlineKeyboardButton(
                text=definition.label,
                callback_data=f"admin:subtemp_pick:{provider_id}:{feature_token(definition.key)}",
                style="primary",
            )
        ]
        for definition in FEATURES
    ]
    rows.append(
        [InlineKeyboardButton(text="↩️ الاشتراك", callback_data=f"admin:provider_sub:{provider_id}")]
    )
    await edit_or_send(callback.message, 
        "اختر الخاصية التي تريد فتحها أو إغلاقها لمدة محددة:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("admin:subtemp_pick:"))
async def temporary_feature_mode(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    _, _, provider_id_text, feature_token_value = (callback.data or "").split(":", 3)
    feature_key = feature_key_from_token(feature_token_value)
    if not feature_key:
        return await callback_notice(callback, "الميزة غير معروفة", show_alert=True)
    await state.clear()
    await state.update_data(provider_id=int(provider_id_text), feature_key=feature_key)
    await state.set_state(AdminFeatureTemporaryStates.enabled)
    await edit_or_send(callback.message, 
        f"اختر الإجراء المؤقت لـ <b>{safe(FEATURE_LABELS[feature_key])}</b>:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔓 فتح مؤقت",
                        callback_data="admin:subtemp_mode:1",
                        style="success",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔒 إغلاق مؤقت",
                        callback_data="admin:subtemp_mode:0",
                        style="danger",
                    )
                ],
            ]
        ),
    )


@router.callback_query(
    AdminFeatureTemporaryStates.enabled, F.data.startswith("admin:subtemp_mode:")
)
async def temporary_feature_days_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if not callback.message:
        return
    enabled = callback.data.endswith(":1")
    await state.update_data(enabled=enabled)
    await state.set_state(AdminFeatureTemporaryStates.days)
    await edit_or_send(callback.message, "اكتب عدد الأيام من 1 إلى 1095:")


@router.message(AdminFeatureTemporaryStates.days)
async def temporary_feature_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    try:
        days = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب عدد الأيام بالأرقام.")
    if not 1 <= days <= 1095:
        return await message.answer("المدة بين يوم و3 سنوات.")
    data = await state.get_data()
    provider = await session.get(Provider, int(data["provider_id"]))
    actor = await admin_actor(session, services, message)
    if not provider:
        await state.clear()
        return await message.answer("المنصة غير موجودة.")
    await services.subscriptions.set_feature_override(
        session,
        provider,
        str(data["feature_key"]),
        bool(data["enabled"]),
        actor,
        days=days,
        reason="استثناء مؤقت من لوحة الإدارة",
    )
    await state.clear()
    action = "فتح" if data["enabled"] else "إغلاق"
    await message.answer(f"تم {action} الخاصية لمدة {days} يومًا ✅", reply_markup=admin_back())


@router.callback_query(F.data.regexp(r"^admin:subprice:\d+$"))
async def custom_price_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.update_data(provider_id=int(callback.data.split(":")[2]))
    await state.set_state(AdminSubscriptionPriceStates.value)
    await edit_or_send(callback.message, "اكتب السعر الخاص بالدينار، أو inherit للعودة إلى سعر الباقة.")


@router.message(AdminSubscriptionPriceStates.value)
async def custom_price_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    raw = (message.text or "").strip().lower()
    if raw in {"inherit", "وراثة", "الغاء", "إلغاء"}:
        value = None
    else:
        try:
            value = int(raw.replace(",", ""))
        except ValueError:
            return await message.answer("اكتب السعر بالأرقام أو inherit.")
        if value < 0:
            return await message.answer("السعر لا يمكن أن يكون سالبًا.")
    data = await state.get_data()
    provider = await session.get(Provider, int(data["provider_id"]))
    actor = await admin_actor(session, services, message)
    if not provider:
        await state.clear()
        return await message.answer("المنصة غير موجودة.")
    await services.subscriptions.set_custom_price(
        session, provider, value, actor, reason="تعديل السعر من لوحة الإدارة"
    )
    await state.clear()
    text = "تمت العودة إلى سعر الباقة" if value is None else f"تم اعتماد سعر {value:,} د.ع"
    await message.answer(f"{text} ✅", reply_markup=admin_back())


@router.callback_query(F.data.regexp(r"^admin:subcommission:\d+$"))
async def commission_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.update_data(provider_id=int(callback.data.split(":")[2]))
    await state.set_state(AdminCommissionOverrideStates.percent)
    await edit_or_send(callback.message, 
        "اكتب نسبة الإدارة المؤقتة من 0 إلى 100.\nمثال: 0 لإعفاء المنصة مؤقتًا."
    )


@router.message(AdminCommissionOverrideStates.percent)
async def commission_percent(message: Message, state: FSMContext) -> None:
    try:
        percent = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب النسبة بالأرقام.")
    if not 0 <= percent <= 100:
        return await message.answer("النسبة بين 0 و100.")
    await state.update_data(percent=percent)
    await state.set_state(AdminCommissionOverrideStates.days)
    await message.answer("اكتب عدد الأيام التي تستمر بها النسبة المؤقتة:")


@router.message(AdminCommissionOverrideStates.days)
async def commission_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    try:
        days = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب عدد الأيام بالأرقام.")
    data = await state.get_data()
    provider = await session.get(Provider, int(data["provider_id"]))
    actor = await admin_actor(session, services, message)
    if not provider:
        await state.clear()
        return await message.answer("المنصة غير موجودة.")
    try:
        await services.subscriptions.set_commission_override(
            session,
            provider,
            int(data["percent"]),
            days,
            actor,
        )
    except ValueError as exc:
        return await message.answer(str(exc))
    await state.clear()
    await message.answer(
        f"تم اعتماد نسبة {data['percent']}% لمدة {days} يومًا ✅",
        reply_markup=admin_back(),
    )


@router.callback_query(F.data.regexp(r"^admin:sublogs:\d+$"))
async def subscription_logs(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    provider_id = int(callback.data.split(":")[2])
    logs = list(
        (
            await session.scalars(
                select(SubscriptionChangeLog)
                .where(SubscriptionChangeLog.provider_id == provider_id)
                .order_by(SubscriptionChangeLog.created_at.desc())
                .limit(20)
            )
        ).all()
    )
    lines = ["🧾 <b>آخر تغييرات الاشتراك</b>"]
    for log in logs:
        lines.append(
            f"\n\n• <code>{safe(log.action)}</code>\n"
            f"{_dt(log.created_at)}\n"
            f"السبب: {safe(log.reason or '-')}"
        )
    await edit_or_send(callback.message, 
        "".join(lines) if logs else "لا توجد تغييرات مسجلة.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="↩️ الاشتراك", callback_data=f"admin:provider_sub:{provider_id}"
                    )
                ]
            ]
        ),
    )


# ---------------- Provider coupons ----------------
@router.callback_query(F.data == "admin:coupons")
async def coupons_list(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    coupons = list(
        (
            await session.scalars(
                select(ProviderCoupon).order_by(ProviderCoupon.created_at.desc()).limit(30)
            )
        ).all()
    )
    rows = [
        [
            InlineKeyboardButton(
                text="➕ إنشاء كوبون", callback_data="admin:coupon_add", style="success"
            )
        ]
    ]
    for coupon in coupons:
        icon = "✅" if coupon.is_active else "❌"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{icon} {coupon.code} — {coupon.kind} ({coupon.used_count})",
                    callback_data=f"admin:coupon_toggle:{coupon.id}",
                    style="primary",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")])
    await edit_or_send(callback.message, 
        "🎟 <b>كوبونات المنصات</b>\nالضغط على كوبون موجود يشغله أو يوقفه.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data == "admin:coupon_add")
async def coupon_add_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.set_state(AdminCouponStates.code)
    await edit_or_send(callback.message, "اكتب رمز الكوبون بالإنجليزي، مثال: FREE7")


@router.message(AdminCouponStates.code)
async def coupon_code(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    if not await require_admin(message, settings):
        return
    code = (message.text or "").strip().upper().replace(" ", "")
    if not 3 <= len(code) <= 40 or not code.replace("-", "").replace("_", "").isalnum():
        return await message.answer("استخدم 3 إلى 40 حرفًا أو رقمًا إنجليزيًا.")
    if await session.scalar(select(ProviderCoupon.id).where(ProviderCoupon.code == code)):
        return await message.answer("الكوبون موجود مسبقًا.")
    await state.update_data(code=code)
    await state.set_state(AdminCouponStates.kind)
    await message.answer(
        "اختر نوع الكوبون:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🎁 أيام تجريبية",
                        callback_data="admin:coupon_kind:trial",
                        style="success",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📦 باقة مجانية لمدة",
                        callback_data="admin:coupon_kind:plan",
                        style="primary",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔓 فتح خاصية مؤقتًا",
                        callback_data="admin:coupon_kind:feature",
                        style="success",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="٪ خصم نسبة",
                        callback_data="admin:coupon_kind:percent_discount",
                    ),
                    InlineKeyboardButton(
                        text="💵 خصم مبلغ",
                        callback_data="admin:coupon_kind:fixed_discount",
                    ),
                ],
            ]
        ),
    )


@router.callback_query(AdminCouponStates.kind, F.data.startswith("admin:coupon_kind:"))
async def coupon_kind(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.message:
        return
    kind = callback.data.split(":")[2]
    allowed = {
        "trial",
        "plan",
        "feature",
        "percent_discount",
        "fixed_discount",
    }
    if kind not in allowed:
        return await callback_notice(callback, "نوع غير صحيح", show_alert=True)
    await state.update_data(kind=kind)
    if kind == "plan":
        await state.set_state(AdminCouponStates.plan_code)
        plans = await services.subscriptions.list_plans(session)
        rows = [
            [
                InlineKeyboardButton(
                    text=f"{plan.name_ar} — {plan.price_iqd:,} د.ع",
                    callback_data=f"admin:coupon_plan:{plan.id}",
                    style="primary",
                )
            ]
            for plan in plans
        ]
        await edit_or_send(callback.message, 
            "اختر الباقة التي يمنحها الكوبون:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        return
    if kind == "feature":
        await state.set_state(AdminCouponStates.feature_key)
        rows = [
            [
                InlineKeyboardButton(
                    text=definition.label,
                    callback_data=f"admin:coupon_feature:{feature_token(definition.key)}",
                    style="primary",
                )
            ]
            for definition in FEATURES
        ]
        await edit_or_send(callback.message, 
            "اختر الخاصية التي يفتحها الكوبون:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        return
    await state.set_state(AdminCouponStates.value)
    prompts = {
        "trial": "اكتب عدد أيام التجربة:",
        "percent_discount": "اكتب نسبة الخصم من 1 إلى 100:",
        "fixed_discount": "اكتب مبلغ الخصم بالدينار:",
    }
    await edit_or_send(callback.message, prompts[kind])


@router.callback_query(AdminCouponStates.plan_code, F.data.startswith("admin:coupon_plan:"))
async def coupon_plan(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await callback.answer()
    if not callback.message:
        return
    token = (callback.data or "").split(":", 2)[2]
    if token.isdecimal():
        plan = await session.get(SubscriptionPlan, int(token))
        plan_code = plan.code if plan else ""
    else:
        plan_code = token  # legacy callback compatibility
    if not plan_code:
        await edit_or_send(callback.message, "الباقة غير موجودة.")
        return
    await state.update_data(plan_code=plan_code)
    await state.set_state(AdminCouponStates.value)
    await edit_or_send(callback.message, "اكتب عدد الأيام التي يمنحها الكوبون لهذه الباقة:")


@router.callback_query(AdminCouponStates.feature_key, F.data.startswith("admin:coupon_feature:"))
async def coupon_feature(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    feature_key = feature_key_from_token((callback.data or "").split(":", 2)[2])
    if not feature_key:
        return await callback_notice(callback, "الميزة غير معروفة", show_alert=True)
    await state.update_data(feature_key=feature_key)
    await state.set_state(AdminCouponStates.feature_days)
    await edit_or_send(callback.message, "اكتب عدد الأيام التي تبقى فيها الخاصية مفتوحة:")


@router.message(AdminCouponStates.feature_days)
async def coupon_feature_days(message: Message, state: FSMContext) -> None:
    try:
        days = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب عدد الأيام بالأرقام.")
    if not 1 <= days <= 1095:
        return await message.answer("المدة بين يوم و3 سنوات.")
    await state.update_data(feature_days=days, value=days)
    await state.set_state(AdminCouponStates.valid_days)
    await message.answer("اكتب صلاحية الكوبون نفسه بالأيام، مثال 30:")


@router.message(AdminCouponStates.value)
async def coupon_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    kind = str(data["kind"])
    try:
        value = int((message.text or "").strip().replace(",", ""))
    except ValueError:
        return await message.answer("اكتب القيمة بالأرقام.")
    if kind == "percent_discount" and not 1 <= value <= 100:
        return await message.answer("نسبة الخصم من 1 إلى 100.")
    if kind in {"trial", "plan"} and not 1 <= value <= 1095:
        return await message.answer("عدد الأيام بين يوم و3 سنوات.")
    if kind == "fixed_discount" and value < 1:
        return await message.answer("مبلغ الخصم يجب أن يكون أكبر من صفر.")
    await state.update_data(value=value)
    await state.set_state(AdminCouponStates.valid_days)
    await message.answer("اكتب صلاحية الكوبون نفسه بالأيام، مثال 30:")


@router.message(AdminCouponStates.valid_days)
async def coupon_valid_days(message: Message, state: FSMContext) -> None:
    try:
        days = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب عدد الأيام بالأرقام.")
    if not 1 <= days <= 1095:
        return await message.answer("صلاحية الكوبون من يوم إلى 3 سنوات.")
    await state.update_data(valid_days=days)
    await state.set_state(AdminCouponStates.max_uses)
    await message.answer("اكتب أقصى عدد استخدامات، أو -1 لغير محدود:")


@router.message(AdminCouponStates.max_uses)
async def coupon_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    try:
        max_uses_value = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب عدد الاستخدامات بالأرقام.")
    if max_uses_value == 0 or max_uses_value < -1:
        return await message.answer("اكتب -1 أو عددًا موجبًا.")
    data = await state.get_data()
    actor = await admin_actor(session, services, message)
    kind_map = {
        "trial": CouponKind.TRIAL.value,
        "plan": CouponKind.PLAN.value,
        "feature": CouponKind.FEATURE.value,
        "percent_discount": CouponKind.PERCENT_DISCOUNT.value,
        "fixed_discount": CouponKind.FIXED_DISCOUNT.value,
    }
    plan_id = None
    if data["kind"] == "plan":
        plan = await services.subscriptions.get_plan(session, str(data["plan_code"]))
        if not plan:
            return await message.answer("الباقة غير موجودة.")
        plan_id = plan.id
    coupon = ProviderCoupon(
        code=str(data["code"]),
        kind=kind_map[str(data["kind"])],
        value_int=int(data["value"]),
        plan_id=plan_id,
        feature_key=data.get("feature_key"),
        feature_days=data.get("feature_days"),
        max_uses=None if max_uses_value == -1 else max_uses_value,
        valid_from=datetime.now(UTC),
        valid_until=datetime.now(UTC) + timedelta(days=int(data["valid_days"])),
        created_by_user_id=actor.id if actor else None,
    )
    session.add(coupon)
    await session.flush()
    await services.audit.log(
        session,
        actor,
        "provider_coupon.created",
        "provider_coupon",
        str(coupon.id),
        {"code": coupon.code, "kind": coupon.kind},
    )
    await state.clear()
    await message.answer(
        f"تم إنشاء الكوبون <code>{safe(coupon.code)}</code> ✅",
        reply_markup=admin_back(),
    )


@router.callback_query(F.data.regexp(r"^admin:coupon_toggle:\d+$"))
async def coupon_toggle(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings):
        return
    coupon = await session.get(ProviderCoupon, int(callback.data.split(":")[2]))
    if not coupon:
        return await callback_notice(callback, "الكوبون غير موجود", show_alert=True)
    coupon.is_active = not coupon.is_active
    await callback_notice(callback, 
        "تم تشغيل الكوبون" if coupon.is_active else "تم إيقاف الكوبون", show_alert=True
    )
