from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin.common import admin_actor, admin_back, require_admin
from app.bot.keyboards.inline import (
    order_actions_keyboard,
    payment_review_keyboard,
)
from app.bot.permissions import can_access_order
from app.bot.states import AdminBroadcastStates
from app.bot.ui import edit_or_send, callback_notice
from app.core.config import Settings
from app.core.utils import safe
from app.db.models import (
    Order,
    OrderEvent,
    OrderStatus,
    SupportTicket,
    User,
)
from app.services.container import Services

router = Router(name="admin_operations")


@router.callback_query(F.data == "admin:orders")
async def orders_list(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    orders = list(
        (await session.scalars(select(Order).order_by(Order.created_at.desc()).limit(40))).all()
    )
    rows = [
        [
            InlineKeyboardButton(
                text=f"{o.public_id} — {o.status} — {o.total_iqd:,}",
                callback_data=f"admin:order:{o.id}",
                style="primary",
            )
        ]
        for o in orders
    ]
    rows.append([InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")])
    await edit_or_send(callback.message, 
        "📦 <b>آخر الطلبات</b>" if orders else "لا توجد طلبات.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.regexp(r"^admin:order:\d+$"))
async def order_details(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    order = await services.orders.get(session, int(callback.data.split(":")[2]))
    if not order or not await can_access_order(
        session, settings, services, callback.from_user.id, order
    ):
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    events = list(
        (
            await session.scalars(
                select(OrderEvent)
                .where(OrderEvent.order_id == order.id)
                .order_by(OrderEvent.created_at.desc())
                .limit(8)
            )
        ).all()
    )
    lines = [
        f"📦 <b>{order.public_id}</b>",
        f"\nالعرض: {safe(order.offer.title)}",
        f"\nالمنصة: {safe(order.provider.name_ar)}",
        f"\nالطالب: {safe(order.user.profile.full_name if order.user.profile else order.user.telegram_name)}",
        f"\nالحالة: <code>{order.status}</code>",
        f"\nالسعر: {order.subtotal_iqd:,} د.ع",
        f"\nرسوم البوت: {order.service_fee_iqd:,} د.ع",
        f"\nالإجمالي: <b>{order.total_iqd:,} د.ع</b>",
        f"\nمستحق المنصة: {order.provider_net_iqd:,} د.ع",
        f"\nمستحق الإدارة: {order.owner_net_iqd:,} د.ع",
        f"\nبيانات التفعيل: <code>{safe(order.activation_data)}</code> (مخفية)",
    ]
    if events:
        lines.append("\n\n<b>آخر التغييرات:</b>")
        for event in reversed(events):
            lines.append(
                f"\n• {event.old_status or '-'} → {event.new_status}: {safe(event.note, '')}"
            )
    rows = []
    if order.status == OrderStatus.PAYMENT_REVIEW.value:
        rows.extend(payment_review_keyboard(order.id).inline_keyboard)
    rows.extend(order_actions_keyboard(order).inline_keyboard)
    if await services.authorization.can_view_pii(session, callback.from_user.id, order.provider_id):
        rows.append([
            InlineKeyboardButton(
                text="🔐 عرض بيانات التفعيل الحساسة",
                callback_data=f"admin:order_secret:{order.id}",
                style="danger",
            )
        ])
    rows.append([InlineKeyboardButton(text="↩️ الطلبات", callback_data="admin:orders")])
    await edit_or_send(callback.message, 
        "".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )


@router.callback_query(F.data.regexp(r"^admin:order_secret:\d+$"))
async def order_secret_details(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    order = await services.orders.get(session, int((callback.data or "").split(":")[2]))
    if not order:
        await callback_notice(callback, "الطلب غير موجود", show_alert=True)
        return
    try:
        actor = await services.authorization.require_pii_access(
            session, callback.from_user.id, order.provider_id
        )
        data = await services.data_protection.reveal_order_activation(
            session,
            order,
            actor.user,
            purpose="manual_order_fulfillment_or_support",
            allowed=True,
        )
    except (PermissionError, Exception) as exc:
        await callback_notice(callback, str(exc), show_alert=True)
        return
    await callback_notice(callback, "تم تسجيل عملية المشاهدة")
    await edit_or_send(callback.message, 
        f"🔐 <b>بيانات التفعيل للطلب {order.public_id}</b>\n\n"
        f"<code>{safe(data)}</code>\n\n"
        "تم تسجيل من شاهد هذه البيانات ووقت المشاهدة."
    )



@router.callback_query(F.data == "admin:payments")
async def payments_list(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    orders = list(
        (
            await session.scalars(
                select(Order)
                .where(Order.status == OrderStatus.PAYMENT_REVIEW.value)
                .order_by(Order.created_at)
                .limit(40)
            )
        ).all()
    )
    rows = [
        [
            InlineKeyboardButton(
                text=f"💳 {o.public_id} — {o.total_iqd:,} د.ع",
                callback_data=f"admin:order:{o.id}",
                style="danger",
            )
        ]
        for o in orders
    ]
    rows.append([InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")])
    await edit_or_send(callback.message, 
        "💳 <b>مدفوعات تنتظر التدقيق</b>" if orders else "لا توجد مدفوعات تنتظر التدقيق.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data == "admin:tickets")
async def tickets_list(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    tickets = list(
        (
            await session.scalars(
                select(SupportTicket)
                .where(SupportTicket.status.not_in(["closed", "resolved"]))
                .order_by(SupportTicket.updated_at.desc())
                .limit(40)
            )
        ).all()
    )
    rows = [
        [
            InlineKeyboardButton(
                text=f"🎫 {t.public_id} — {t.status}",
                callback_data=f"ticket:view:{t.id}",
                style="primary",
            )
        ]
        for t in tickets
    ]
    rows.append([InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")])
    await edit_or_send(callback.message, 
        "🎫 <b>التذاكر المفتوحة</b>" if tickets else "لا توجد تذاكر مفتوحة.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data == "admin:broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.set_state(AdminBroadcastStates.message)
    await edit_or_send(callback.message, "أرسل نص الإشعار الجماعي. لن يتم الإرسال قبل شاشة التأكيد:")


@router.message(AdminBroadcastStates.message)
async def broadcast_preview(message: Message, state: FSMContext, settings: Settings) -> None:
    if not await require_admin(message, settings):
        return
    text = (message.text or message.caption or "").strip()
    if len(text) < 2 or len(text) > 3500:
        return await message.answer("النص يجب أن يكون بين 2 و3500 حرف.")
    await state.update_data(broadcast_text=text)
    await state.set_state(AdminBroadcastStates.confirm)
    await message.answer(
        f"<b>معاينة الإشعار:</b>\n\n{safe(text)}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ إرسال للجميع",
                        callback_data="admin:broadcast_confirm",
                        style="success",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ إلغاء", callback_data="admin:broadcast_cancel", style="danger"
                    )
                ],
            ]
        ),
    )


@router.callback_query(F.data == "admin:broadcast_cancel")
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings):
        return
    await state.clear()
    await callback_notice(callback, "تم الإلغاء", show_alert=True)


@router.callback_query(F.data == "admin:broadcast_confirm")
async def broadcast_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    data = await state.get_data()
    text = str(data.get("broadcast_text", ""))
    if not text:
        await state.clear()
        return await edit_or_send(callback.message, "انتهت جلسة الإرسال.")
    users = list((await session.scalars(select(User).where(User.is_active.is_(True)))).all())
    success = failed = 0
    for user in users:
        try:
            await services.notifications.bot.send_message(user.telegram_id, safe(text))
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.04)
    actor = await admin_actor(session, services, callback)
    await services.audit.log(
        session, actor, "broadcast.sent", "user", "all", {"success": success, "failed": failed}
    )
    await state.clear()
    await edit_or_send(callback.message, 
        f"تم الإرسال ✅\nنجح: {success}\nفشل: {failed}", reply_markup=admin_back()
    )
