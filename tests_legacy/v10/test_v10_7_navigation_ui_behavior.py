from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

aiogram = pytest.importorskip("aiogram")

from aiogram.types import (  # noqa: E402
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
)

from app.bot.ui import send_inline_menu, send_reply_menu  # noqa: E402


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.next_message_id = 100

    def _message(self, chat_id: int, text: str, markup: object = None) -> Message:
        self.next_message_id += 1
        return Message(
            message_id=self.next_message_id,
            date=datetime.now(UTC),
            chat=Chat(id=chat_id, type="private"),
            text=text,
            reply_markup=markup if isinstance(markup, InlineKeyboardMarkup) else None,
        ).as_(self)

    async def send_message(self, chat_id: int, text: str, reply_markup: object = None, **_kwargs: object) -> Message:
        self.calls.append(("send", reply_markup))
        return self._message(chat_id, text, reply_markup)

    async def edit_message_reply_markup(self, *, chat_id: int, message_id: int, reply_markup: object) -> Message:
        self.calls.append(("edit_markup", message_id))
        return Message(
            message_id=message_id,
            date=datetime.now(UTC),
            chat=Chat(id=chat_id, type="private"),
            text="inline",
            reply_markup=reply_markup,
        ).as_(self)

    async def edit_message_text(self, *_args: object, **_kwargs: object) -> Message:
        raise RuntimeError("no source message in this test")

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.calls.append(("delete", (chat_id, message_id)))


@pytest.mark.asyncio
async def test_reply_to_inline_uses_visible_final_message_not_deleted_carrier() -> None:
    bot = FakeBot()
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="فتح", callback_data="open")]]
    )
    rendered = await send_inline_menu(1, "لوحة", markup, bot=bot, actor_id=7)
    assert rendered.reply_markup == markup
    assert isinstance(bot.calls[0][1], ReplyKeyboardRemove)
    assert bot.calls[1][0] == "edit_markup"
    assert all(call[0] != "delete" for call in bot.calls)


@pytest.mark.asyncio
async def test_home_message_itself_owns_reply_keyboard() -> None:
    bot = FakeBot()
    anchor = bot._message(1, "anchor")
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="الرئيسية")]], resize_keyboard=True, is_persistent=True
    )
    rendered = await send_reply_menu(anchor, "الرئيسية", keyboard, actor_id=7)
    assert rendered.message_id > anchor.message_id
    assert bot.calls[-1][0] == "send"
    assert bot.calls[-1][1] == keyboard
