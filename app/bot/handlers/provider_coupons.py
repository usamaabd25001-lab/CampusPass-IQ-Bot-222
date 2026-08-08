from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.provider import _staff, _staff_for_provider
from app.bot.states import ProviderStudentCouponStates
from app.bot.ui import callback_notice, edit_or_send
from app.core.utils import parse_money, safe
from app.db.models import OrderCoupon, OrderCouponType, User
from app.services.container import Services

router = Router(name="provider_student_coupons")


_KIND_LABELS = {
    OrderCouponType.FIXED.value: "💵 خصم مبلغ ثابت",
    OrderCouponType.PERCENT.value: "📉 خصم نسبة مئوية",
    OrderCouponType.FEE_WAIVER.value: "🤝 إسقاط رسوم البوت",
    OrderCouponType.FREE_REPORT.value: "📄 تقرير مجاني",
}
_CALLBACK_KIND = {
    "fixed": OrderCouponType.FIXED.value,
    "percent": OrderCouponType.PERCENT.value,
    "fee": OrderCouponType.FEE_WAIVER.value,
    "report": OrderCouponType.FREE_REPORT.value,
}


def _home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤝 إسقاط رسوم البوت",
                    callback_data="psc:new:fee",
                    style="success",
                ),
                InlineKeyboardButton(
                    text="📄 تقرير مجاني",
                    callback_data="psc:new:report",
                    style="success",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💵 خصم ثابت",
                    callback_data="psc:new:fixed",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="📉 خصم نسبة",
                    callback_data="psc:new:percent",
                    style="primary",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="↩️ لوحة المنصة",
                    callback_data="back_to_platform",
                )
            ],
        ]
    )


@router.callback_query(F.data == "provider:student_coupons")
async def provider_student_coupons_home(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    await state.clear()
    _actor, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_offers:
        await callback_notice(callback, "لا تملك صلاحية إدارة كوبونات الطلاب", show_alert=True)
        return
    coupons = list(
        (
            await session.scalars(
                select(OrderCoupon)
                .where(OrderCoupon.provider_id == staff.provider_id)
                .order_by(OrderCoupon.created_at.desc(), OrderCoupon.id.desc())
                .limit(12)
            )
        ).all()
    )
    lines = []
    for coupon in coupons:
        target = f"طالب #{coupon.target_user_id}" if coupon.target_user_id else "جميع الطلاب"
        value = ""
        if coupon.coupon_type == OrderCouponType.FIXED.value:
            value = f" — {coupon.value_int:,} د.ع"
        elif coupon.coupon_type == OrderCouponType.PERCENT.value:
            value = f" — {coupon.value_int}%"
        lines.append(
            f"• <code>{safe(coupon.code)}</code> — "
            f"{safe(_KIND_LABELS.get(coupon.coupon_type, coupon.coupon_type))}{value} — "
            f"{safe(target)} — {'فعال ✅' if coupon.is_active else 'متوقف ❌'}"
        )
    await edit_or_send(
        callback.message,
        "🎟 <b>كوبونات طلاب المنصة</b>\n\n"
        "كل كود جديد هنا يكون سريًا، مخصصًا لطالب واحد، واستخدامه مرة واحدة.\n\n"
        + ("\n".join(lines) if lines else "لا توجد كوبونات طلاب حتى الآن."),
        reply_markup=_home_keyboard(),
    )


@router.callback_query(F.data.regexp(r"^psc:new:(fixed|percent|fee|report)$"))
async def provider_student_coupon_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    _actor, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not staff.can_manage_offers:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    token = (callback.data or "").rsplit(":", 1)[-1]
    coupon_type = _CALLBACK_KIND[token]
    await state.clear()
    await state.update_data(
        psc_provider_id=staff.provider_id,
        psc_coupon_type=coupon_type,
    )
    await state.set_state(ProviderStudentCouponStates.target)
    await edit_or_send(
        callback.message,
        f"{_KIND_LABELS[coupon_type]}\n\n"
        "أرسل أحد الآتي لتحديد الطالب بدقة:\n"
        "• Telegram ID الرقمي\n"
        "• @username\n"
        "• كود الإحالة الخاص بالطالب",
    )


@router.message(ProviderStudentCouponStates.target)
async def provider_student_coupon_target(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    provider_id = int(data.get("psc_provider_id") or 0)
    _actor, staff = await _staff_for_provider(
        session, services, message.from_user.id, provider_id
    )
    if not staff or not staff.can_manage_offers:
        await state.clear()
        await message.answer("انتهت جلسة المنصة أو لا تملك الصلاحية.")
        return
    raw = (message.text or "").strip()
    target = None
    if raw.isdigit():
        target = await session.scalar(select(User).where(User.telegram_id == int(raw)))
    elif raw.startswith("@") and len(raw) > 1:
        target = await session.scalar(
            select(User).where(func.lower(User.telegram_username) == raw[1:].lower())
        )
    else:
        normalized = services.users.normalize_referral_payload(raw)
        target = await session.scalar(
            select(User).where(
                or_(
                    User.referral_code == normalized,
                    func.lower(User.telegram_username) == raw.lower().lstrip("@"),
                )
            )
        )
    if not target:
        await message.answer("لم أجد طالبًا مطابقًا. تحقق من الـID أو اسم المستخدم أو كود الإحالة.")
        return
    await state.update_data(
        psc_target_user_id=target.id,
        psc_target_telegram_id=target.telegram_id,
        psc_target_name=target.telegram_name,
    )
    coupon_type = str(data.get("psc_coupon_type") or "")
    if coupon_type in {OrderCouponType.FIXED.value, OrderCouponType.PERCENT.value}:
        await state.set_state(ProviderStudentCouponStates.value)
        prompt = (
            "اكتب مبلغ الخصم بالدينار، مثال: <code>1000</code>"
            if coupon_type == OrderCouponType.FIXED.value
            else "اكتب نسبة الخصم من 1 إلى 100، مثال: <code>20</code>"
        )
        await message.answer(
            f"تم اختيار الطالب: <b>{safe(target.telegram_name)}</b>\n\n{prompt}"
        )
        return
    await state.update_data(psc_value=0)
    await state.set_state(ProviderStudentCouponStates.code)
    await message.answer(
        f"تم اختيار الطالب: <b>{safe(target.telegram_name)}</b>\n\n"
        "اكتب الكود السري بالإنجليزي، مثال: <code>HUSSAIN-FREE</code>"
    )


@router.message(ProviderStudentCouponStates.value)
async def provider_student_coupon_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    coupon_type = str(data.get("psc_coupon_type") or "")
    value = parse_money(message.text or "")
    if value is None or value <= 0:
        await message.answer("اكتب قيمة صحيحة أكبر من صفر.")
        return
    if coupon_type == OrderCouponType.PERCENT.value and value > 100:
        await message.answer("النسبة يجب ألا تتجاوز 100.")
        return
    await state.update_data(psc_value=int(value))
    await state.set_state(ProviderStudentCouponStates.code)
    await message.answer("اكتب الكود السري بالإنجليزي، مثال: <code>STUDENT500</code>")


@router.message(ProviderStudentCouponStates.code)
async def provider_student_coupon_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    provider_id = int(data.get("psc_provider_id") or 0)
    actor, staff = await _staff_for_provider(
        session, services, message.from_user.id, provider_id
    )
    if not actor or not staff or not staff.can_manage_offers:
        await state.clear()
        await message.answer("انتهت جلسة المنصة أو لا تملك الصلاحية.")
        return
    target = await session.get(User, int(data.get("psc_target_user_id") or 0))
    if not target:
        await state.clear()
        await message.answer("الطالب المحدد لم يعد موجودًا.")
        return
    try:
        coupon = await services.order_coupons.create(
            session,
            code=message.text or "",
            coupon_type=str(data.get("psc_coupon_type") or ""),
            value_int=int(data.get("psc_value") or 0),
            provider_id=staff.provider_id,
            target_user_id=target.id,
            created_by_user_id=actor.id,
            max_uses=1,
            per_user_limit=1,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return
    label = _KIND_LABELS.get(coupon.coupon_type, coupon.coupon_type)
    await services.notifications.send_user(
        session,
        target,
        "🎟 لديك كود خاص من المنصة",
        f"الكود: <code>{safe(coupon.code)}</code>\n"
        f"الميزة: <b>{safe(label)}</b>\n\n"
        "استخدمه عند ظهور سؤال «هل لديك كود خصم؟» قبل الدفع.",
        idempotency_key=f"student-coupon:{coupon.id}:target:{target.id}",
    )
    await state.clear()
    await message.answer(
        f"✅ تم إنشاء الكود <code>{safe(coupon.code)}</code> للطالب "
        f"<b>{safe(target.telegram_name)}</b> وإرسال تنبيه إليه.",
        reply_markup=_home_keyboard(),
    )
