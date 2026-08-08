from __future__ import annotations

import contextlib
from contextlib import asynccontextmanager

from aiogram.types import Message


@asynccontextmanager
async def processing_message(message: Message, text: str = "جاري المعالجة، يرجى الانتظار..."):
    """Show a visible progress message for operations that may touch DB/network.

    The message is removed after the operation. If Telegram refuses deletion,
    it is edited to a neutral completion message instead.
    """
    status = await message.answer(text)
    try:
        yield status
    finally:
        with contextlib.suppress(Exception):
            await status.delete()
