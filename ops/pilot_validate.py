from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiogram import Bot

from app.core.config import get_settings
from app.core.database import Database
from app.core.security import SecretBox
from app.services.container import Services


async def main() -> int:
    settings = get_settings()
    database = Database(settings)
    bot = Bot(settings.bot_token)
    services = Services(bot, settings, SecretBox(settings.encryption_keys))

    async def telegram_probe() -> tuple[bool, str]:
        me = await bot.get_me()
        return True, f"bot_id={me.id}"

    async def redis_probe() -> tuple[bool, str]:
        if not settings.redis_url:
            return False, "not_configured"
        import redis.asyncio as redis
        client = redis.from_url(settings.redis_url, decode_responses=True)
        try:
            pong = await client.ping()
            return bool(pong), "pong"
        finally:
            await client.aclose()

    async def storage_probe() -> tuple[bool, str]:
        if not settings.backup_s3_bucket or not settings.backup_s3_endpoint:
            return False, "not_configured"
        return True, "configured; write verification occurs during backup"

    await database.connect()
    try:
        async with database.session_factory() as session:
            run = await services.pilot.validate(
                session,
                redis_probe=redis_probe,
                telegram_probe=telegram_probe,
                storage_probe=storage_probe,
            )
            await session.commit()
            print({
                "status": run.status,
                "blocking_failures": run.blocking_failures,
                "warnings": run.warnings,
                "checks": run.checks_json,
            })
            return 0 if run.status == "passed" else 2
    finally:
        await bot.session.close()
        await database.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
