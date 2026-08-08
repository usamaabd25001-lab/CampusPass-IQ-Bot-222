from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.handlers.admin.common import admin_actor, admin_back, require_admin
from app.bot.states import AdminPlanEditStates, AdminPlanLimitStates, AdminPlanStates
from app.bot.ui import edit_or_send
from app.core.config import Settings
from app.core.utils import safe
from app.db.models import PlanEntitlement, SubscriptionPlan
from app.services.container import Services
from app.services.subscriptions import (
    FEATURES,
    LIMITS,
    feature_key_from_token,
    feature_token,
    limit_key_from_token,
    limit_token,
)

router = Router(name="admin_plans")


def _price_confirmation_keyboard(prefix: str, *, can_suggest: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="✅ اعتماد السعر المكتوب",
                callback_data=f"{prefix}:keep",
                style="success",
            )
        ]
    ]
    if can_suggest:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💡 اعتماد الاقتراح ×1000",
                    callback_data=f"{prefix}:suggest",
                    style="primary",
                )
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text="✏️ كتابة السعر من جديد", callback_data=f"{prefix}:retry")],
            [InlineKeyboardButton(text="❌ إلغاء العملية", callback_data="nav:cancel", style="danger")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _price_confirmation_text(value: int, words: str, suggested: int | None) -> str:
    warning = ""
    if suggested is not None:
        warning = (
            "\n\n⚠️ <b>تنبيه مهم:</b> الرقم منخفض جدًا. "
            f"إذا كنت تقصد {suggested:,} د.ع اختر زر الاقتراح، "
            "ولا تعتمد الرقم الصغير بالخطأ."
        )
    return (
        "💰 <b>راجع السعر قبل الحفظ</b>\n\n"
        f"الرقم: <b>{value:,} د.ع</b>\n"
        f"بالكتابة: <b>{safe(words)}</b>"
        f"{warning}"
    )


@router.callback_query(F.data == "admin:plans")
async def plans_list(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    plans = await services.subscriptions.list_plans(session)
    rows = [
        [
            InlineKeyboardButton(
                text="➕ إنشاء باقة مخصصة", callback_data="admin:plan_add", style="success"
            )
        ]
    ]
    for plan in plans:
        icon = "✅" if plan.is_active else "❌"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{icon} {plan.name_ar} — {plan.price_iqd:,} د.ع",
                    callback_data=f"admin:plan:{plan.id}",
                    style="primary",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")])
    await edit_or_send(callback.message, 
        "📦 <b>باقات المنصات</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def _render_plan_details(message: Message, plan: SubscriptionPlan) -> None:
    rows = [
        [
            InlineKeyboardButton(
                text="💰 تعديل السعر",
                callback_data=f"admin:plan_edit:{plan.id}:price",
                style="success",
            ),
            InlineKeyboardButton(
                text="📅 مدة الاشتراك",
                callback_data=f"admin:plan_edit:{plan.id}:billing",
                style="primary",
            ),
        ],
        [
            InlineKeyboardButton(
                text="⏳ فترة السماح",
                callback_data=f"admin:plan_edit:{plan.id}:grace",
                style="primary",
            ),
            InlineKeyboardButton(text="✏️ الاسم", callback_data=f"admin:plan_edit:{plan.id}:name"),
        ],
        [
            InlineKeyboardButton(
                text="🔓 خصائص الباقة",
                callback_data=f"admin:plan_features:{plan.id}",
                style="success",
            ),
            InlineKeyboardButton(
                text="📊 حدود الباقة", callback_data=f"admin:plan_limits:{plan.id}", style="primary"
            ),
        ],
        [
            InlineKeyboardButton(
                text="⏸ إيقاف" if plan.is_active else "▶️ تشغيل",
                callback_data=f"admin:plan_toggle:{plan.id}",
                style="danger" if plan.is_active else "success",
            )
        ],
        [InlineKeyboardButton(text="↩️ الباقات", callback_data="admin:plans")],
    ]
    await edit_or_send(
        message,
        f"📦 <b>{safe(plan.name_ar)}</b>\n\n"
        f"الرمز: <code>{safe(plan.code)}</code>\n"
        f"السعر: {plan.price_iqd:,} د.ع\n"
        f"المدة: {plan.billing_days} يومًا\n"
        f"فترة السماح: {plan.grace_days} يومًا\n"
        f"النوع: {'نظامية' if plan.is_system else 'مخصصة'}\n"
        f"الحالة: {'نشطة' if plan.is_active else 'متوقفة'}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.regexp(r"^admin:plan:\d+$"))
async def plan_details(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    plan = await session.scalar(
        select(SubscriptionPlan)
        .options(selectinload(SubscriptionPlan.features))
        .where(SubscriptionPlan.id == int(callback.data.split(":")[2]))
    )
    if not plan:
        return await edit_or_send(callback.message, "الباقة غير موجودة.")
    await _render_plan_details(callback.message, plan)


@router.callback_query(F.data == "admin:plan_add")
async def plan_add_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.set_state(AdminPlanStates.code)
    await edit_or_send(callback.message, "اكتب رمز الباقة بالإنجليزي، مثال: custom-plus")


@router.message(AdminPlanStates.code)
async def plan_add_code(message: Message, state: FSMContext) -> None:
    code = (message.text or "").strip().lower().replace(" ", "-")
    if not code or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in code):
        return await message.answer("استخدم حروفًا إنجليزية وأرقامًا و - أو _ فقط.")
    await state.update_data(code=code)
    await state.set_state(AdminPlanStates.name_ar)
    await message.answer("اكتب اسم الباقة بالعربي:")


@router.message(AdminPlanStates.name_ar)
async def plan_add_name(message: Message, state: FSMContext) -> None:
    name = " ".join((message.text or "").split())
    if len(name) < 2:
        return await message.answer("اكتب اسمًا واضحًا.")
    await state.update_data(name_ar=name[:120])
    await state.set_state(AdminPlanStates.price)
    await message.answer("اكتب السعر الشهري بالدينار:")


@router.message(AdminPlanStates.price)
async def plan_add_price(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    try:
        value = services.pricing.parse_iqd(message.text or "", allow_zero=True)
    except ValueError as exc:
        return await message.answer(str(exc))
    suggested = value * 1000 if 1 <= value <= 999 else None
    await state.update_data(pending_plan_price=value, pending_plan_price_suggested=suggested)
    await state.set_state(AdminPlanStates.price_confirm)
    await message.answer(
        _price_confirmation_text(value, services.pricing.iqd_words(value), suggested),
        reply_markup=_price_confirmation_keyboard(
            "admin:plan_add_price", can_suggest=suggested is not None
        ),
    )


@router.callback_query(
    AdminPlanStates.price_confirm, F.data.regexp(r"^admin:plan_add_price:(keep|suggest|retry)$")
)
async def plan_add_price_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    action = (callback.data or "").rsplit(":", 1)[-1]
    if action == "retry":
        await state.set_state(AdminPlanStates.price)
        await edit_or_send(callback.message, 
            "اكتب السعر كاملًا بالدينار. مثال: 10000 يعني عشرة آلاف، أما 10 فتعني عشرة فقط."
        )
        return
    data = await state.get_data()
    value = int(data["pending_plan_price"])
    if action == "suggest":
        value = int(data.get("pending_plan_price_suggested") or value)
    await state.update_data(price=value)
    await state.set_state(AdminPlanStates.billing_days)
    await edit_or_send(callback.message, 
        f"تم اعتماد السعر: <b>{value:,} د.ع</b> ✅\n\nاكتب مدة الباقة بالأيام، مثال 30:"
    )


@router.message(AdminPlanStates.billing_days)
async def plan_add_billing(message: Message, state: FSMContext) -> None:
    try:
        days = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب الأيام بالأرقام.")
    if not 1 <= days <= 1095:
        return await message.answer("المدة بين يوم و3 سنوات.")
    await state.update_data(billing_days=days)
    await state.set_state(AdminPlanStates.grace_days)
    await message.answer("اكتب فترة السماح بالأيام من 0 إلى 90:")


@router.message(AdminPlanStates.grace_days)
async def plan_add_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    try:
        grace = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب الأيام بالأرقام.")
    if not 0 <= grace <= 90:
        return await message.answer("فترة السماح من 0 إلى 90 يومًا.")
    data = await state.get_data()
    try:
        plan = await services.subscriptions.create_plan(
            session,
            code=str(data["code"]),
            name_ar=str(data["name_ar"]),
            price_iqd=int(data["price"]),
            billing_days=int(data["billing_days"]),
            grace_days=grace,
            inherit_from="free",
        )
    except ValueError as exc:
        return await message.answer(str(exc))
    actor = await admin_actor(session, services, message)
    await services.pricing.log_price_change(
        session,
        key=f"plan.{plan.code}.price_iqd",
        old_value=None,
        new_value=plan.price_iqd,
        actor=actor,
        reason="إنشاء باقة منصة من لوحة المالك",
    )
    await state.clear()
    await message.answer(
        f"تم إنشاء باقة <b>{safe(plan.name_ar)}</b> ونسخ خصائص المجانية إليها ✅",
        reply_markup=admin_back(),
    )


@router.callback_query(F.data.regexp(r"^admin:plan_edit:\d+:(price|billing|grace|name)$"))
async def plan_edit_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    _, _, plan_id, field = callback.data.split(":")
    await state.clear()
    await state.update_data(plan_id=int(plan_id), field=field)
    await state.set_state(AdminPlanEditStates.value)
    prompts = {
        "price": "اكتب السعر الجديد بالدينار:",
        "billing": "اكتب مدة الاشتراك الجديدة بالأيام:",
        "grace": "اكتب فترة السماح الجديدة بالأيام:",
        "name": "اكتب الاسم العربي الجديد:",
    }
    await edit_or_send(callback.message, prompts[field])


@router.message(AdminPlanEditStates.value)
async def plan_edit_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    data = await state.get_data()
    plan = await session.get(SubscriptionPlan, int(data["plan_id"]))
    if not plan:
        await state.clear()
        return await message.answer("الباقة غير موجودة.")
    field = str(data["field"])
    raw = (message.text or "").strip()
    if field == "price":
        try:
            value = services.pricing.parse_iqd(raw, allow_zero=True)
        except ValueError as exc:
            return await message.answer(str(exc))
        suggested = value * 1000 if 1 <= value <= 999 else None
        await state.update_data(
            pending_plan_price=value,
            pending_plan_price_suggested=suggested,
            old_plan_price=plan.price_iqd,
        )
        await state.set_state(AdminPlanEditStates.price_confirm)
        await message.answer(
            _price_confirmation_text(value, services.pricing.iqd_words(value), suggested),
            reply_markup=_price_confirmation_keyboard(
                "admin:plan_edit_price", can_suggest=suggested is not None
            ),
        )
        return
    try:
        if field == "billing":
            value = int(raw)
            if not 1 <= value <= 1095:
                raise ValueError
            plan.billing_days = value
        elif field == "grace":
            value = int(raw)
            if not 0 <= value <= 90:
                raise ValueError
            plan.grace_days = value
        else:
            if len(raw) < 2:
                raise ValueError
            plan.name_ar = raw[:120]
    except ValueError:
        return await message.answer("القيمة غير صحيحة.")
    await state.clear()
    await message.answer("تم تحديث الباقة ✅", reply_markup=admin_back())


@router.callback_query(
    AdminPlanEditStates.price_confirm,
    F.data.regexp(r"^admin:plan_edit_price:(keep|suggest|retry)$"),
)
async def plan_edit_price_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    action = (callback.data or "").rsplit(":", 1)[-1]
    if action == "retry":
        await state.set_state(AdminPlanEditStates.value)
        await edit_or_send(callback.message, 
            "اكتب السعر كاملًا بالدينار. مثال: 10000 يعني عشرة آلاف، أما 10 فتعني عشرة فقط."
        )
        return
    data = await state.get_data()
    plan = await session.get(SubscriptionPlan, int(data["plan_id"]))
    if not plan:
        await state.clear()
        return await edit_or_send(callback.message, "الباقة غير موجودة.")
    value = int(data["pending_plan_price"])
    if action == "suggest":
        value = int(data.get("pending_plan_price_suggested") or value)
    old_value = int(data.get("old_plan_price", plan.price_iqd))
    plan.price_iqd = value
    actor = await admin_actor(session, services, callback)
    await services.pricing.log_price_change(
        session,
        key=f"plan.{plan.code}.price_iqd",
        old_value=old_value,
        new_value=value,
        actor=actor,
        reason="تعديل سعر باقة منصة من لوحة المالك",
    )
    await state.clear()
    await edit_or_send(callback.message, 
        f"تم تحديث سعر الباقة إلى <b>{value:,} د.ع</b> ✅",
        reply_markup=admin_back(),
    )


@router.callback_query(F.data.regexp(r"^admin:plan_toggle:\d+$"))
async def plan_toggle(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    plan = await session.get(SubscriptionPlan, int(callback.data.split(":")[2]))
    if not plan:
        return await edit_or_send(callback.message, "الباقة غير موجودة.")
    plan.is_active = not plan.is_active
    await session.flush()
    await _render_plan_details(callback.message, plan)


async def _render_plan_features(
    message: Message,
    session: AsyncSession,
    plan_id: int,
) -> None:
    entitlements = {
        row.feature_key: row
        for row in (
            await session.scalars(select(PlanEntitlement).where(PlanEntitlement.plan_id == plan_id))
        ).all()
    }
    rows: list[list[InlineKeyboardButton]] = []
    for feature in FEATURES:
        enabled = bool(entitlements.get(feature.key) and entitlements[feature.key].is_enabled)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{'✅' if enabled else '❌'} {feature.label}",
                    callback_data=f"admin:plan_feature:{plan_id}:{feature_token(feature.key)}",
                    style="success" if enabled else "danger",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="↩️ الباقة", callback_data=f"admin:plan:{plan_id}")])
    await edit_or_send(
        message,
        "اضغط على الخاصية لتشغيلها أو إيقافها داخل هذه الباقة:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.regexp(r"^admin:plan_features:\d+$"))
async def plan_features(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await _render_plan_features(callback.message, session, int(callback.data.split(":")[2]))


@router.callback_query(F.data.startswith("admin:plan_feature:"))
async def plan_feature_toggle(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    _, _, plan_id_text, feature_token_value = (callback.data or "").split(":", 3)
    feature_key = feature_key_from_token(feature_token_value)
    plan = await session.get(SubscriptionPlan, int(plan_id_text))
    if not plan or not feature_key:
        return await edit_or_send(callback.message, "الباقة أو الخاصية غير موجودة.")
    current = await session.scalar(
        select(PlanEntitlement).where(
            PlanEntitlement.plan_id == plan.id,
            PlanEntitlement.feature_key == feature_key,
        )
    )
    await services.subscriptions.set_plan_feature(
        session, plan, feature_key, not bool(current and current.is_enabled)
    )
    await session.flush()
    await _render_plan_features(callback.message, session, plan.id)


async def _render_plan_limits(
    message: Message,
    session: AsyncSession,
    plan_id: int,
) -> None:
    entitlements = {
        row.feature_key: row
        for row in (
            await session.scalars(select(PlanEntitlement).where(PlanEntitlement.plan_id == plan_id))
        ).all()
    }
    rows: list[list[InlineKeyboardButton]] = []
    for limit in LIMITS:
        entitlement = entitlements.get(limit.key)
        value = entitlement.limit_value if entitlement else None
        text = "غير محدود" if value == -1 else (str(value) if value is not None else "غير محدد")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{limit.label}: {text}",
                    callback_data=f"admin:plan_limit:{plan_id}:{limit_token(limit.key)}",
                    style="primary",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="↩️ الباقة", callback_data=f"admin:plan:{plan_id}")])
    await edit_or_send(
        message,
        "اختر الحد لتعديله. اكتب -1 لغير محدود:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.regexp(r"^admin:plan_limits:\d+$"))
async def plan_limits(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await _render_plan_limits(callback.message, session, int(callback.data.split(":")[2]))


@router.callback_query(F.data.startswith("admin:plan_limit:"))
async def plan_limit_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    _, _, plan_id_text, limit_token_value = (callback.data or "").split(":", 3)
    limit_key = limit_key_from_token(limit_token_value)
    if not limit_key:
        return await edit_or_send(callback.message, "الحد غير معروف.")
    await state.clear()
    await state.update_data(plan_id=int(plan_id_text), limit_key=limit_key)
    await state.set_state(AdminPlanLimitStates.value)
    await edit_or_send(callback.message, "اكتب القيمة الجديدة، أو -1 لغير محدود:")


@router.message(AdminPlanLimitStates.value)
async def plan_limit_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    try:
        value = int((message.text or "").strip())
    except ValueError:
        return await message.answer("اكتب رقمًا صحيحًا.")
    if value < -1:
        return await message.answer("أقل قيمة هي -1.")
    data = await state.get_data()
    plan = await session.get(SubscriptionPlan, int(data["plan_id"]))
    if not plan:
        await state.clear()
        return await message.answer("الباقة غير موجودة.")
    try:
        await services.subscriptions.set_plan_limit(session, plan, str(data["limit_key"]), value)
    except ValueError as exc:
        return await message.answer(str(exc))
    await state.clear()
    await message.answer("تم تحديث حد الباقة ✅", reply_markup=admin_back())
