from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import (
    activation_problem_keyboard,
    rating_keyboard,
    subscription_details_keyboard,
    user_order_details_keyboard,
    user_orders_keyboard,
)
from app.bot.states import ReviewStates
from app.bot.ui import edit_or_send, callback_notice
from app.core.config import Settings
from app.core.presentation import order_status_label, subscription_status_label
from app.core.time import format_datetime
from app.core.utils import safe
from app.db.models import (
    Offer,
    OrderStatus,
    StudentSubscription,
    StudentSubscriptionStatus,
)
from app.services.container import Services

router = Router(name="orders")



@router.callback_query(F.data.startswith("orders:list"))
async def list_user_orders(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get(session, callback.from_user.id)
    if not user:
        return
    parts = (callback.data or "orders:list:0").split(":")
    try:
        page = max(0, int(parts[2])) if len(parts) > 2 else 0
    except ValueError:
        page = 0
    orders, total = await services.orders.user_orders_page(
        session, user, page=page, page_size=8
    )
    if not orders:
        if page > 0:
            await edit_or_send(callback.message, "لا توجد طلبات أخرى في هذه الصفحة.")
        else:
            await edit_or_send(callback.message, "لا توجد طلبات حتى الآن.")
        return
    await edit_or_send(callback.message, 
        f"📦 <b>طلباتي</b> — {total} طلب\nاختر طلبًا لعرض التفاصيل:",
        reply_markup=user_orders_keyboard(orders, page=page, total=total),
    )


@router.message(Command("order"))
async def find_order_by_public_id(
    message: Message, session: AsyncSession, services: Services, settings: Settings
) -> None:
    if not message.from_user:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("اكتب رقم الطلب بعد الأمر، مثال: <code>/order ORD-XXXX</code>")
        return
    public_id = parts[1].strip().upper()
    user = await services.users.get(session, message.from_user.id)
    order = await services.orders.get_by_public_id(session, public_id)
    if not user or not order or order.user_id != user.id:
        await message.answer("لم أجد طلباً بهذا الرقم ضمن حسابك.")
        return
    subscription = await session.scalar(
        select(StudentSubscription).where(StudentSubscription.order_id == order.id)
    )
    await message.answer(
        f"📦 <b>{safe(order.offer.title)}</b>\n"
        f"رقم الطلب: <code>{order.public_id}</code>\n"
        f"الحالة: <b>{safe(order_status_label(order.status))}</b>\n"
        f"التاريخ: {format_datetime(order.created_at, settings.timezone)}",
        reply_markup=user_order_details_keyboard(order, has_subscription=bool(subscription)),
    )


@router.callback_query(F.data.startswith("order:view:"))
async def view_user_order(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    order = await services.orders.get(session, int((callback.data or "").split(":")[2]))
    if not order or order.user.telegram_id != callback.from_user.id:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    timeline = await services.workflows.timeline(session, order)
    timeline_lines = []
    for step in timeline:
        icon = "🔵" if step["current"] else "✅" if step["done"] else "⚪"
        timeline_lines.append(f"{icon} {safe(step['label'])}")
    subscription = await session.scalar(
        select(StudentSubscription).where(StudentSubscription.order_id == order.id)
    )
    method = order.payment_method.name if order.payment_method else "لم تُحدد بعد"
    text = (
        f"📦 <b>{safe(order.offer.title)}</b>\n\n"
        f"رقم الطلب: <code>{order.public_id}</code>\n"
        f"المنصة: {safe(order.provider.name_ar)}\n"
        f"الحالة: <b>{safe(order_status_label(order.status))}</b>\n"
        f"طريقة الدفع: {safe(method)}\n"
        f"السعر: {order.subtotal_iqd:,} د.ع\n"
        f"رسوم الخدمة: {order.service_fee_iqd:,} د.ع\n"
        f"الإجمالي: <b>{order.total_iqd:,} د.ع</b>\n"
        f"تاريخ الطلب: {format_datetime(order.created_at, settings.timezone)}\n"
        f"استلام البيانات: {'مؤكد ✅' if order.delivery_acknowledged_at else 'لم يؤكد بعد'}\n"
        f"نجاح التفعيل: {'مؤكد ✅' if order.activation_confirmed_at else 'لم يؤكد بعد'}\n\n"
        "<b>مراحل الطلب:</b>\n" + "\n".join(timeline_lines)
    )
    await edit_or_send(callback.message, 
        text,
        reply_markup=user_order_details_keyboard(order, has_subscription=bool(subscription)),
    )


@router.callback_query(F.data.startswith("order:subscription:"))
async def order_subscription_details(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    order = await services.orders.get(session, int((callback.data or "").split(":")[2]))
    if not order or order.user.telegram_id != callback.from_user.id:
        return
    subscription = await session.scalar(
        select(StudentSubscription).where(StudentSubscription.order_id == order.id)
    )
    if not subscription:
        await edit_or_send(callback.message, "لم يُنشأ اشتراك لهذا الطلب بعد.")
        return
    start = format_datetime(subscription.starts_at, settings.timezone, "لم يبدأ")
    end = format_datetime(subscription.ends_at, settings.timezone)
    await edit_or_send(callback.message, 
        f"📅 <b>{safe(subscription.offer_name_snapshot)}</b>\n\n"
        f"المنصة: {safe(subscription.provider_name_snapshot)}\n"
        f"الحالة: {safe(subscription_status_label(subscription.status))}\n"
        f"البداية: {start}\n"
        f"النهاية: {end}",
        reply_markup=subscription_details_keyboard(subscription, allow_code=True),
    )


@router.callback_query(F.data.startswith("order:ack_delivery:"))
async def acknowledge_order_delivery(
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
    try:
        await services.orders.acknowledge_delivery(session, order, user)
    except (ValueError, PermissionError) as exc:
        await callback_notice(callback, str(exc), show_alert=True)
        return
    await callback_notice(callback, "تم تثبيت استلام البيانات ✅")
    refreshed = await services.orders.get(session, order.id)
    await edit_or_send(callback.message, 
        "📥 تم تسجيل أنك استلمت بيانات الخدمة.\n"
        "جرّب التفعيل الآن، وبعدها اختر نجاح التفعيل أو ارفع المشكلة.",
        reply_markup=user_order_details_keyboard(
            refreshed or order,
            has_subscription=bool(
                await session.scalar(
                    select(StudentSubscription.id).where(StudentSubscription.order_id == order.id)
                )
            ),
        ),
    )


@router.callback_query(F.data.startswith("order:complete:"))
async def complete_order(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    order = await services.orders.get(session, int((callback.data or "").split(":")[2]))
    if not order or order.user.telegram_id != callback.from_user.id:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    if order.status == OrderStatus.COMPLETED.value:
        await edit_or_send(callback.message, "الطلب مكتمل سابقًا.")
        return
    if order.status != OrderStatus.DELIVERED.value:
        await edit_or_send(callback.message, "لا يمكن إكمال الطلب قبل تسليم الاشتراك.")
        return
    user = await services.users.get(session, callback.from_user.id)
    if not user:
        return
    try:
        order = await services.orders.confirm_activation(session, order, user)
    except (ValueError, PermissionError) as exc:
        await edit_or_send(callback.message, str(exc))
        return
    await services.student_subscriptions.activate(session, order)
    await services.finance.finalize_order(session, order, order.user_id)
    subscription = await session.scalar(
        select(StudentSubscription).where(StudentSubscription.order_id == order.id)
    )
    end_text = (
        subscription.ends_at.strftime("%d/%m/%Y")
        if subscription and subscription.ends_at
        else "غير محدد"
    )
    await edit_or_send(callback.message, 
        "تم إكمال الاشتراك بنجاح ✅\n"
        f"تاريخ الانتهاء: <b>{end_text}</b>\n"
        "يمكنك متابعة التفاصيل والوصل من زر «📅 اشتراكاتي».\n\n"
        "شلون كانت تجربتك؟ تقييمك يساعدنا نحسن الخدمة.",
        reply_markup=rating_keyboard(order.id),
    )


@router.callback_query(F.data.startswith("review:open:"))
async def open_review(callback: CallbackQuery, session: AsyncSession, services: Services) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    order = await services.orders.get(session, int((callback.data or "").split(":")[2]))
    if not order or order.user.telegram_id != callback.from_user.id:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    if order.status != OrderStatus.COMPLETED.value:
        await edit_or_send(callback.message, "يمكن تقييم الطلب بعد اكتماله فقط.")
        return
    await edit_or_send(callback.message, "اختر تقييمك من 1 إلى 5:", reply_markup=rating_keyboard(order.id))


@router.callback_query(F.data.startswith("review:rate:"))
async def rate_order(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    parts = (callback.data or "").split(":")
    order_id = int(parts[2])
    rating = int(parts[3])
    order = await services.orders.get(session, order_id)
    user = await services.users.get(session, callback.from_user.id)
    if not order or not user or order.user_id != user.id:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    try:
        await services.reviews.submit_rating(session, user, order, rating)
    except (ValueError, PermissionError) as exc:
        await edit_or_send(callback.message, str(exc))
        return
    await state.clear()
    await state.update_data(review_order_id=order.id)
    await state.set_state(ReviewStates.comment)
    await edit_or_send(callback.message, 
        f"شكرًا! سجلنا تقييمك: <b>{rating}/5</b> ⭐\n"
        "اكتب ملاحظة قصيرة عن تجربتك، أو أرسل علامة - للتخطي."
    )


@router.message(ReviewStates.comment)
async def review_comment(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    user = await services.users.get(session, message.from_user.id)
    if not user:
        await state.clear()
        return
    text = (message.text or "").strip()
    if text not in {"-", "تخطي", "skip"}:
        if len(text) < 3:
            await message.answer("اكتب ملاحظة أو أرسل - للتخطي.")
            return
        await services.reviews.set_comment(session, user, int(data["review_order_id"]), text)
    await state.clear()
    await message.answer("شكرًا لتقييمك 🌟")


@router.callback_query(F.data.startswith("order:problem:"))
async def order_problem(callback: CallbackQuery, session: AsyncSession, services: Services) -> None:
    await callback.answer()
    order = await services.orders.get(session, int((callback.data or "").split(":")[2]))
    if not order or not callback.from_user or order.user.telegram_id != callback.from_user.id:
        return
    if callback.message:
        await edit_or_send(callback.message, 
            f"ما سبب عدم تفعيل الطلب <code>{order.public_id}</code>؟",
            reply_markup=activation_problem_keyboard(order.id),
        )


@router.callback_query(F.data.startswith("opr:"))
@router.callback_query(F.data.startswith("order:problem_reason:"))
async def order_problem_reason(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    parts = (callback.data or "").split(":")
    try:
        if parts[0] == "opr":
            order_id = int(parts[1])
            reason = {
                "1": "invalid_code",
                "2": "expired_code",
                "3": "no_code",
                "4": "credentials",
                "5": "devices",
                "6": "blocked",
                "7": "other",
            }.get(parts[2], "other")
        else:
            order_id = int(parts[2])
            reason = parts[3]
    except (ValueError, IndexError):
        await edit_or_send(callback.message, "بيانات المشكلة غير صحيحة.")
        return
    order = await services.orders.get(session, order_id)
    if not order or order.user.telegram_id != callback.from_user.id:
        return
    labels = {
        "invalid_code": "الرمز غير صحيح",
        "expired_code": "انتهت صلاحية الرمز",
        "no_code": "لم يصل رمز جديد",
        "credentials": "البريد أو كلمة المرور لا يعملان",
        "devices": "تجاوز عدد الأجهزة",
        "blocked": "الحساب موقوف",
        "other": "سبب آخر",
    }
    label = labels.get(reason, "مشكلة تفعيل")
    if reason in {"invalid_code", "expired_code", "no_code"}:
        offer = await session.get(Offer, order.offer_id)
        if offer:
            try:
                await services.email_codes.request_new_code(session, order, offer)
                await edit_or_send(callback.message, 
                    "⏳ بدأ انتظار رمز جديد مطابق للطلب. إذا لم يصل، ستتحول الحالة للدعم."
                )
                return
            except ValueError:
                pass
    ticket = await services.support.create_ticket(
        session,
        order.user,
        f"مشكلة تفعيل — {order.public_id}",
        label,
        category="activation",
        provider_id=order.provider_id,
        order_id=order.id,
    )
    await services.orders.change_status(
        session,
        order,
        OrderStatus.NEEDS_SUPPORT.value,
        actor_user_id=order.user_id,
        note=label,
    )
    subscription = await session.scalar(
        select(StudentSubscription).where(StudentSubscription.order_id == order.id)
    )
    if subscription:
        subscription.status = StudentSubscriptionStatus.NEEDS_SUPPORT.value
    await edit_or_send(callback.message, 
        f"تم فتح تذكرة <code>{ticket.public_id}</code> وإرسالها إلى المنصة ✅"
    )


@router.callback_query(F.data.startswith("code:new:"))
async def request_new_code(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    order = await services.orders.get(session, int((callback.data or "").split(":")[2]))
    if not order or order.user.telegram_id != callback.from_user.id:
        return
    offer = await session.get(Offer, order.offer_id)
    if not offer:
        return
    try:
        await services.email_codes.request_new_code(session, order, offer)
    except ValueError as exc:
        await edit_or_send(callback.message, str(exc))
        return
    await edit_or_send(callback.message, 
        "بدأ انتظار رسالة جديدة مطابقة للطلب. لن يعيد النظام استخدام الرسالة أو الكود السابق."
    )


@router.callback_query(F.data.startswith("order:cancel:"))
async def cancel_order(callback: CallbackQuery, session: AsyncSession, services: Services) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    order = await services.orders.get(session, int((callback.data or "").split(":")[2]))
    if not order or order.user.telegram_id != callback.from_user.id:
        return
    if order.status not in {
        OrderStatus.WAITING_PAYMENT.value,
        OrderStatus.PAYMENT_REJECTED.value,
    }:
        await edit_or_send(callback.message, "لا يمكن إلغاء الطلب في حالته الحالية.")
        return
    await services.orders.release_reservation(session, order, "ألغاه المستخدم")
    await services.orders.change_status(
        session,
        order,
        OrderStatus.CANCELLED.value,
        actor_user_id=order.user_id,
        note="ألغاه المستخدم وتم تحرير المورد",
    )
    await edit_or_send(callback.message, "تم إلغاء الطلب وتحرير المورد المحجوز.")
