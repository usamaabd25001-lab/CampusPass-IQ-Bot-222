from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.core.config import Settings
from app.core.database import Database
from app.core.security import SecretBox

if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher

    from app.services.container import Services


@dataclass(slots=True)
class AppContext:
    settings: Settings
    database: Database
    secrets: SecretBox
    services: Services
    bot: Bot
    ready: bool = False
    startup_error: str = ""
    database_ready: bool = False
    bot_ready: bool = False
    worker_ready: bool = False
    release_registered: bool = False
    redis_ready: bool = False
    webhook_ready: bool = False
    update_processor_ready: bool = False
    deployment_gate_ready: bool = False
    dispatcher: Dispatcher | None = None
    redis_client: Any | None = None
    last_gate_checks: dict[str, Any] | None = None
    update_wakeup: asyncio.Event = field(default_factory=asyncio.Event)
    update_inflight: int = 0
    draining: bool = False
