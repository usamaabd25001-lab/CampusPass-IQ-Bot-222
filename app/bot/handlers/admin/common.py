from __future__ import annotations

from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import admin_dashboard_keyboard, with_navigation
from app.bot.ui import edit_or_send
from app.core.config import Settings
from app.db.models import User
from app.services.container import Services


async def require_admin(event: Message | CallbackQuery, settings: Settings) -> bool:
    telegram_id = event.from_user.id if event.from_user else None
    allowed = bool(telegram_id and settings.is_admin(telegram_id))
    if not allowed:
        identity = str(telegram_id or "غير معروف")
        if isinstance(event, CallbackQuery):
            if event.message:
                await edit_or_send(
                    event.message,
                    "⛔ <b>غير مصرح.</b>\n\n"
                    f"رقم Telegram الخاص بك: <code>{identity}</code>\n"
                    "أضفه إلى <code>ADMIN_IDS</code> ثم أعد تشغيل البوت.",
                )
        else:
            await event.answer(
                "⛔ <b>حسابك غير مضاف كمالك للبوت.</b>\n\n"
                f"رقم Telegram الخاص بك: <code>{identity}</code>\n"
                "أضف الرقم داخل متغير <code>ADMIN_IDS</code> في السيرفر ثم أعد تشغيل البوت. "
                "لا ترسل Bot Token أو كلمات المرور لأي شخص."
            )
    return allowed


async def admin_actor(
    session: AsyncSession,
    services: Services,
    event: Message | CallbackQuery,
) -> User | None:
    if not event.from_user:
        return None
    return await services.users.get_or_create(
        session,
        event.from_user.id,
        event.from_user.username,
        event.from_user.full_name,
    )


def admin_back() -> InlineKeyboardMarkup:
    return with_navigation(
        InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")]]
        ),
        back_callback="admin:home",
    )


async def show_admin_home(event: Message | CallbackQuery) -> Message | None:
    text = (
        "🛡 <b>لوحة الإدارة المركزية</b>\n\n"
        "جميع التعديلات تُحفظ في قاعدة البيانات ولا تُشغّل كودًا عشوائيًا من تيليغرام."
    )
    if isinstance(event, CallbackQuery):
        if event.message:
            return await edit_or_send(
                event.message, text, reply_markup=admin_dashboard_keyboard()
            )
        return None
    return await event.answer(text, reply_markup=admin_dashboard_keyboard())
