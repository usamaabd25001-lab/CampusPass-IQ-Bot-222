from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.security import SecretBox
from app.db.migrations import run_migrations
from app.db.models import Base
from app.db.seed import seed_defaults
from app.services.container import Services


@dataclass
class SentMessage:
    chat: Any
    message_id: int
    text: str


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, Any]] = []
        self.deleted: list[tuple[int, int]] = []
        self.edited: list[tuple[int, int, str]] = []
        self.actions: list[tuple[int, Any]] = []
        self.api_calls: list[Any] = []
        self.pinned: list[tuple[int, int]] = []
        self.unpinned: list[tuple[int, int | None]] = []

    async def __call__(self, method, request_timeout=None):
        self.api_calls.append(method)
        return True

    async def send_message(self, chat_id: int, text: str, reply_markup=None, **kwargs):
        self.sent.append((chat_id, text, reply_markup))
        return SentMessage(SimpleNamespace(id=chat_id), len(self.sent), text)

    async def send_photo(self, chat_id: int, photo, caption: str = "", reply_markup=None, **kwargs):
        self.sent.append((chat_id, caption, reply_markup))
        return SentMessage(SimpleNamespace(id=chat_id), len(self.sent), caption)

    async def send_video(self, chat_id: int, video, caption: str = "", reply_markup=None, **kwargs):
        self.sent.append((chat_id, caption, reply_markup))
        return SentMessage(SimpleNamespace(id=chat_id), len(self.sent), caption)

    async def send_document(
        self, chat_id: int, document, caption: str = "", reply_markup=None, **kwargs
    ):
        self.sent.append((chat_id, caption, reply_markup))
        return SentMessage(SimpleNamespace(id=chat_id), len(self.sent), caption)

    async def pin_chat_message(self, chat_id: int, message_id: int, **kwargs):
        self.pinned.append((chat_id, message_id))
        return True

    async def unpin_chat_message(self, chat_id: int, message_id: int | None = None, **kwargs):
        self.unpinned.append((chat_id, message_id))
        return True

    async def delete_message(self, chat_id: int, message_id: int):
        self.deleted.append((chat_id, message_id))
        return True

    async def edit_message_text(self, text: str, chat_id: int, message_id: int, **kwargs):
        self.edited.append((chat_id, message_id, text))
        return True

    async def send_chat_action(self, chat_id: int, action):
        self.actions.append((chat_id, action))
        return True


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
        "ADMIN_IDS": "9001",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "ENVIRONMENT": "test",
        "ENCRYPTION_KEY": "v4-test-encryption-key",
        "REPORT_SECRET_KEY": "v4-test-report-key",
        "FEATURE_EMAIL_CODES": False,
        "FEATURE_GEMINI": False,
        "FEATURE_MASTERCARD": False,
    }
    values.update(overrides)
    return Settings(**values)


async def database_bundle():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        await run_migrations(session)
        await seed_defaults(session)
        await session.commit()
    return engine, factory


def services_bundle(**settings_overrides: Any):
    config = settings(**settings_overrides)
    bot = FakeBot()
    secrets = SecretBox(config)
    services = Services(bot, config, secrets)
    return config, bot, secrets, services


def aware(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)
