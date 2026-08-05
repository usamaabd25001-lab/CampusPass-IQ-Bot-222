import asyncio
from types import SimpleNamespace

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from app.bot.handlers import admin, catalog, menu, orders, payments, provider, start, support
from app.bot.handlers.start import send_home
from app.bot.keyboards.inline import (
    admin_dashboard_keyboard,
    back_keyboard,
    manual_payment_keyboard,
    offer_keyboard,
    payment_methods_keyboard,
    provider_dashboard_keyboard,
    style_keyboard,
    terms_keyboard,
)


def _all_callback_data(markup: InlineKeyboardMarkup) -> list[str]:
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


def _assert_valid_markup(markup: InlineKeyboardMarkup) -> None:
    callbacks = _all_callback_data(markup)
    assert all(len(value.encode("utf-8")) <= 64 for value in callbacks)
    for row in markup.inline_keyboard:
        assert row
        for button in row:
            assert button.text.strip()
            if button.style is not None:
                assert button.style in {"primary", "success", "danger"}


def test_all_main_routers_import_and_have_handlers():
    routers = [
        start.router,
        menu.router,
        catalog.router,
        orders.router,
        payments.router,
        support.router,
    ]
    assert all(router is not None for router in routers)
    assert provider.router is not None
    assert admin.router is not None


def test_static_keyboards_are_valid_for_telegram():
    markups = [
        terms_keyboard(),
        back_keyboard(),
        offer_keyboard(1),
        manual_payment_keyboard(1),
        admin_dashboard_keyboard(),
        provider_dashboard_keyboard(),
        style_keyboard("services"),
    ]
    methods = [SimpleNamespace(id=1, icon="💳", name="بطاقة")]
    markups.append(payment_methods_keyboard(methods, 1))
    for markup in markups:
        _assert_valid_markup(markup)


class FakeMessage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup=None):
        self.calls.append((text, reply_markup))


class FakeMenuService:
    def __init__(self, reply=None, inline=None) -> None:
        self.reply = reply
        self.inline = inline

    async def reply_keyboard(self, session, user):
        return self.reply

    async def inline_keyboard(self, session, user):
        return self.inline


def run(coro):
    return asyncio.run(coro)


async def _send_home_scenarios() -> None:
    reply = ReplyKeyboardMarkup(keyboard=[], resize_keyboard=True)
    inline = InlineKeyboardMarkup(inline_keyboard=[])

    message = FakeMessage()
    await send_home(
        message,
        None,
        SimpleNamespace(menus=FakeMenuService(reply=reply, inline=None)),
        object(),
    )
    assert len(message.calls) == 1
    assert message.calls[0][1] is reply

    message = FakeMessage()
    await send_home(
        message,
        None,
        SimpleNamespace(menus=FakeMenuService(reply=None, inline=inline)),
        object(),
    )
    assert len(message.calls) == 2
    assert message.calls[1][1] is inline

    message = FakeMessage()
    await send_home(
        message,
        None,
        SimpleNamespace(menus=FakeMenuService(reply=reply, inline=inline)),
        object(),
    )
    assert len(message.calls) == 2
    assert message.calls[0][1] is reply
    assert message.calls[1][1] is inline


def test_home_rendering_reply_inline_and_hybrid():
    run(_send_home_scenarios())
