import asyncio
from datetime import UTC, datetime

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot.middleware import ActivityIndicatorMiddleware, RateLimitMiddleware
from tests.v4_helpers import FakeBot


def run(coro):
    return asyncio.run(coro)


def message_event() -> Message:
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=7700, type="private"),
        text="اختبار",
    )


async def _success():
    bot = FakeBot()
    middleware = ActivityIndicatorMiddleware(delay_ms=100, text="⏳ اختبار المعالجة")

    async def slow_handler(_event, _data):
        await asyncio.sleep(0.14)
        return "done"

    result = await middleware(slow_handler, message_event(), {"bot": bot})
    assert result == "done"
    assert any("اختبار المعالجة" in item[1] for item in bot.sent)
    assert bot.deleted


async def _failure():
    bot = FakeBot()
    middleware = ActivityIndicatorMiddleware(delay_ms=100)

    async def broken_handler(_event, _data):
        await asyncio.sleep(0.12)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await middleware(broken_handler, message_event(), {"bot": bot})
    assert bot.edited or any("رقم المتابعة" in item[1] for item in bot.sent)


def test_processing_indicator_for_slow_operations():
    run(_success())


def test_processing_error_has_reference():
    run(_failure())


def callback_event(bot: FakeBot) -> CallbackQuery:
    return CallbackQuery(
        id="rate-test",
        from_user=User(id=8800, is_bot=False, first_name="طالب"),
        chat_instance="rate-chat",
        data="catalog:providers",
        message=message_event(),
    ).as_(bot)


async def _rate_limit_callback_answered():
    bot = FakeBot()
    middleware = RateLimitMiddleware(min_interval=5)
    calls = 0

    async def handler(_event, _data):
        nonlocal calls
        calls += 1
        return "ok"

    event = callback_event(bot)
    data = {"event_from_user": event.from_user}
    assert await middleware(handler, event, data) == "ok"
    assert await middleware(handler, event, data) is None
    assert calls == 1
    assert bot.api_calls
    assert "انتظر" in (getattr(bot.api_calls[-1], "text", "") or "")


def test_rate_limited_callback_is_answered_instead_of_spinning():
    run(_rate_limit_callback_answered())
