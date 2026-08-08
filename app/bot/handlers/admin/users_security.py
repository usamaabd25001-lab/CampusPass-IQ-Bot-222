from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.handlers.admin.common import admin_back, require_admin
from app.bot.ui import edit_or_send, callback_notice
from app.core.config import Settings
from app.core.utils import safe
from app.db.models import Order, StudentProfile, StudentSubscription, SystemSetting, User, Wallet, WalletOwnerType

router = Router(name="admin_users_security")

def _users_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔎 بحث عن مستخدم", callback_data="admin:users:search", style="primary")],
        [InlineKeyboardButton(text="📄 تصدير CSV كامل", callback_data="admin:users:export", style="success")],
        [InlineKeyboardButton(text="✏️ حد تعديل المعلومات", callback_data="admin:users:edit_limit", style="primary")],
        [InlineKeyboardButton(text="🚫 المحظورون", callback_data="admin:users:banned", style="danger")],
        [InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")],
    ])

@router.callback_query(F.data == "admin:users")
async def users_home(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message: return
    total = int(await session.scalar(select(func.count()).select_from(User)) or 0)
    banned = int(await session.scalar(select(func.count()).select_from(User).where(User.is_banned.is_(True))) or 0)
    raw = await session.scalar(select(SystemSetting.value).where(SystemSetting.key == "profile_edit_limit"))
    await edit_or_send(callback.message, 
        f"👥 <b>إدارة المستخدمين</b>\n\nالمجموع: <b>{total}</b>\nالمحظورون: <b>{banned}</b>\nحد تعديل المعلومات: <b>{safe(raw or '3')}</b>",
        reply_markup=_users_keyboard(),
    )

@router.callback_query(F.data == "admin:users:search")
async def ask_search(callback: CallbackQuery, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message: return
    await edit_or_send(callback.message, "أرسل الآن Telegram ID أو @username.\nمثال: <code>123456789</code> أو <code>@student</code>")

@router.message(Command("user"))
async def command_user(message: Message, session: AsyncSession, settings: Settings) -> None:
    if not await require_admin(message, settings): return
    value=(message.text or '').split(maxsplit=1)
    if len(value)<2:
        await message.answer("استخدم: <code>/user 123456789</code>")
        return
    await _show_user(message, session, value[1])

@router.message(F.text.regexp(r"^@?[A-Za-z0-9_]{4,64}$|^\d{5,20}$"))
async def search_text(message: Message, session: AsyncSession, settings: Settings) -> None:
    if not settings.is_admin(message.from_user.id if message.from_user else 0): return
    await _show_user(message, session, message.text or '')

async def _show_user(message: Message, session: AsyncSession, query: str) -> None:
    q=query.strip().lstrip('@')
    conditions=[]
    if q.isdigit(): conditions.append(User.telegram_id == int(q))
    conditions.append(func.lower(User.telegram_username) == q.lower())
    user=await session.scalar(select(User).options(selectinload(User.profile)).where(or_(*conditions)).limit(1))
    if not user:
        await message.answer("لم أجد مستخدمًا بهذه المعلومات.", reply_markup=admin_back()); return
    p=user.profile
    status="محظور 🚫" if user.is_banned else "فعال ✅"
    orders_count = int(await session.scalar(select(func.count()).select_from(Order).where(Order.user_id == user.id)) or 0)
    subs_count = int(await session.scalar(select(func.count()).select_from(StudentSubscription).where(StudentSubscription.user_id == user.id)) or 0)
    wallet_balance = int(await session.scalar(select(Wallet.balance_iqd).where(Wallet.owner_type == WalletOwnerType.USER.value, Wallet.owner_id == user.id)) or 0)
    text=(f"👤 <b>سجل المستخدم الإداري</b>\n\nTelegram ID: <code>{user.telegram_id}</code>\n"
          f"المعرف: @{safe(user.telegram_username or 'بدون')}\nالاسم: {safe(p.full_name if p else user.telegram_name)}\n"
          f"الهاتف: {safe(p.phone if p else 'غير مسجل')}\nالمحافظة: {safe(p.governorate if p else '-')}\n"
          f"الجامعة: {safe(p.university if p else '-')}\nالكلية: {safe(p.college if p else '-')}\n"
          f"القسم: {safe(p.department if p else '-')}\nالمرحلة: {safe(p.stage if p else '-')}\n"
          f"الحالة: <b>{status}</b>\nمرات تعديل المعلومات: {p.edit_count if p else 0}\n"
          f"سبب الحظر: {safe(user.ban_reason or '-')}\n"
          f"الطلبات: <b>{orders_count}</b> | الاشتراكات: <b>{subs_count}</b>\n"
          f"رصيد المحفظة: <b>{wallet_balance:,} د.ع</b>" )
    action=("فك الحظر ✅", f"admin:users:unban:{user.id}", "success") if user.is_banned else ("حظر المستخدم 🚫", f"admin:users:ban:{user.id}", "danger")
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 الطلبات", callback_data=f"admin:user_orders:{user.id}", style="primary"),
            InlineKeyboardButton(text="📅 الاشتراكات", callback_data=f"admin:user_subs:{user.id}", style="success"),
        ],
        [InlineKeyboardButton(text=action[0], callback_data=action[1], style=action[2])],
        [InlineKeyboardButton(text="↩️ المستخدمون", callback_data="admin:users")],
    ])
    await message.answer(text, reply_markup=kb)

@router.callback_query(F.data.startswith("admin:users:ban:"))
async def ban_user(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message: return
    uid=int((callback.data or '').rsplit(':',1)[1]); user=await session.get(User,uid)
    if not user: await callback_notice(callback, "المستخدم غير موجود",show_alert=True); return
    if settings.is_admin(user.telegram_id): await callback_notice(callback, "لا يمكن حظر مالك البوت",show_alert=True); return
    user.is_banned=True; user.is_active=False; user.banned_at=datetime.now(timezone.utc); user.banned_by_telegram_id=callback.from_user.id; user.ban_reason="حظر يدوي بواسطة المالك"
    await callback_notice(callback, "تم الحظر",show_alert=True)
    await edit_or_send(callback.message, f"🚫 تم حظر المستخدم <code>{user.telegram_id}</code>.", reply_markup=_users_keyboard())

@router.callback_query(F.data.startswith("admin:users:unban:"))
async def unban_user(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message: return
    uid=int((callback.data or '').rsplit(':',1)[1]); user=await session.get(User,uid)
    if not user: await callback_notice(callback, "المستخدم غير موجود",show_alert=True); return
    user.is_banned=False; user.is_active=True; user.banned_at=None; user.banned_by_telegram_id=None; user.ban_reason=""
    await callback_notice(callback, "تم فك الحظر",show_alert=True)
    await edit_or_send(callback.message, f"✅ تم فك حظر المستخدم <code>{user.telegram_id}</code>.", reply_markup=_users_keyboard())

@router.callback_query(F.data == "admin:users:banned")
async def banned_list(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message: return
    rows=list((await session.scalars(select(User).where(User.is_banned.is_(True)).order_by(User.banned_at.desc()).limit(50))).all())
    text="🚫 <b>آخر المستخدمين المحظورين</b>\n\n" + ("\n".join(f"• <code>{u.telegram_id}</code> @{safe(u.telegram_username or 'بدون')}" for u in rows) if rows else "لا يوجد محظورون.")
    await edit_or_send(callback.message, text, reply_markup=_users_keyboard())

@router.callback_query(F.data == "admin:users:edit_limit")
async def edit_limit_help(callback: CallbackQuery, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message: return
    await edit_or_send(callback.message, "لتغيير الحد أرسل: <code>/editlimit 3</code>\nاكتب 0 لمنع التعديل بالكامل.")

@router.message(Command("editlimit"))
async def set_edit_limit(message: Message, session: AsyncSession, settings: Settings) -> None:
    if not await require_admin(message, settings): return
    parts=(message.text or '').split(maxsplit=1)
    if len(parts)<2 or not parts[1].isdigit() or not 0 <= int(parts[1]) <= 20:
        await message.answer("استخدم رقمًا من 0 إلى 20. مثال: <code>/editlimit 3</code>"); return
    value=str(int(parts[1])); row=await session.scalar(select(SystemSetting).where(SystemSetting.key == "profile_edit_limit"))
    if row: row.value=value
    else: session.add(SystemSetting(key="profile_edit_limit",value=value))
    await message.answer(f"✅ أصبح حد تعديل المعلومات <b>{value}</b> مرات.", reply_markup=_users_keyboard())

@router.callback_query(F.data == "admin:users:export")
async def export_users(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message: return
    await callback_notice(callback, "جاري تجهيز الملف...")
    users=list((await session.scalars(select(User).options(selectinload(User.profile)).order_by(User.id))).all())
    order_counts=dict((await session.execute(select(Order.user_id, func.count(Order.id)).group_by(Order.user_id))).all())
    out=io.StringIO(); writer=csv.writer(out)
    writer.writerow(["telegram_id","username","telegram_name","full_name","phone","governorate","university","college","department","stage","role","points","is_active","is_banned","ban_reason","profile_edit_count","orders_count","created_at","updated_at"])
    for u in users:
        p=u.profile
        writer.writerow([u.telegram_id,u.telegram_username or "",u.telegram_name,p.full_name if p else "",p.phone if p else "",p.governorate if p else "",p.university if p else "",p.college if p else "",p.department if p else "",p.stage if p else "",u.role,u.points,u.is_active,u.is_banned,u.ban_reason,p.edit_count if p else 0,order_counts.get(u.id,0),u.created_at.isoformat() if u.created_at else "",u.updated_at.isoformat() if u.updated_at else ""])
    data=("\ufeff"+out.getvalue()).encode("utf-8")
    await callback.message.answer_document(BufferedInputFile(data, filename="campuspass_users.csv"), caption="📄 ملف المستخدمين — يحتوي بيانات إدارية فقط ولا يحتوي كلمات مرور أو أسرار.", reply_markup=_users_keyboard())


@router.callback_query(F.data.regexp(r"^admin:user_orders:\d+$"))
async def admin_user_orders(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    user_id = int(callback.data.rsplit(":", 1)[1])
    user = await session.get(User, user_id)
    if not user:
        return await edit_or_send(callback.message, "المستخدم غير موجود.")
    rows = list((await session.scalars(
        select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(30)
    )).all())
    text = "📦 <b>آخر طلبات المستخدم</b>\n\n"
    text += "\n".join(
        f"• <code>{o.public_id}</code> — {o.total_iqd:,} د.ع — {safe(o.status)}"
        for o in rows
    ) if rows else "لا توجد طلبات."
    await edit_or_send(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ المستخدمون", callback_data="admin:users")
    ]]))


@router.callback_query(F.data.regexp(r"^admin:user_subs:\d+$"))
async def admin_user_subscriptions(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    user_id = int(callback.data.rsplit(":", 1)[1])
    rows = list((await session.scalars(
        select(StudentSubscription).where(StudentSubscription.user_id == user_id)
        .order_by(StudentSubscription.created_at.desc()).limit(30)
    )).all())
    text = "📅 <b>اشتراكات المستخدم</b>\n\n"
    text += "\n".join(
        f"• {safe(x.provider_name_snapshot)} — {safe(x.offer_name_snapshot)} — {safe(x.status)}"
        + (f" — ينتهي {x.ends_at:%Y-%m-%d}" if x.ends_at else "")
        for x in rows
    ) if rows else "لا توجد اشتراكات."
    await edit_or_send(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ المستخدمون", callback_data="admin:users")
    ]]))
