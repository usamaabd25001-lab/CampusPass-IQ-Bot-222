from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import CallbackQuery, Message

from app.bot.ui import edit_or_send

logger = logging.getLogger(__name__)
router = Router(name="callback-fallback")


@router.callback_query()
async def stale_or_unknown_callback(callback: CallbackQuery) -> None:
    """Handle legacy/unknown inline buttons after every real router and plugin.

    The callback is acknowledged before any logging or rendering so Telegram
    never leaves the spinner active.  The current FSM state is intentionally
    preserved: an old message must not cancel a newer operation.
    """

    await callback.answer()
    logger.info(
        "Ignored stale or unknown callback user=%s payload=%r",
        getattr(callback.from_user, "id", None),
        callback.data,
    )
    if isinstance(callback.message, Message):
        await edit_or_send(
            callback.message,
            "⚠️ هذا الزر قديم أو لم يعد متاحاً. اختر الرجوع أو القائمة الرئيسية.",
            reply_markup=None,
        )
