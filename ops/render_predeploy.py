from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from redis.asyncio import Redis
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError
from redis.retry import Retry
from sqlalchemy import select

from app import __version__
from app.core.config import get_settings
from app.core.database import Database
from app.core.security import SecretBox
from app.db.migrations import MIGRATIONS, run_migrations
from app.db.models import BackupRunStatus, SchemaMigration
from app.db.seed import seed_defaults
from app.services.backups import BackupService
from app.services.deployment_gates import DeploymentGateService
from app.services.cache_coherence import CacheCoherenceService
from app.services.update_safety import UpdateSafetyService


async def main() -> int:
    settings = get_settings()
    database = Database(settings)
    secret_box = SecretBox(settings)
    bot = Bot(
        settings.bot_token,
        session=AiohttpSession(
            limit=max(10, min(settings.telegram_http_connection_limit, 40)),
            timeout=settings.telegram_request_timeout_seconds,
        ),
    )
    redis_client: Redis | None = None
    try:
        await database.wait_until_ready()
        await database.create_tables()
        async with database.session_factory() as session:
            has_lock = await database.try_transaction_lock(session, settings.scheduler_lock_id + 6)
            if not has_lock:
                raise RuntimeError("Another pre-deploy migration process owns the database lock")
            existing = set((await session.scalars(select(SchemaMigration.version))).all())
            pending = [item.version for item in MIGRATIONS if item.version not in existing]
            if pending and settings.backup_ready and settings.auto_pre_deploy_backup:
                backup = await BackupService(settings, secret_box).create(session)
                if backup.status != BackupRunStatus.VERIFIED.value:
                    if settings.require_pre_deploy_backup:
                        raise RuntimeError(
                            "Verified pre-deploy backup failed: "
                            f"{backup.last_error or 'unknown backup error'}"
                        )
            elif pending and settings.require_pre_deploy_backup:
                raise RuntimeError(
                    "Pending migrations require a verified backup, but backup is unavailable"
                )
            applied = await run_migrations(session)
            await seed_defaults(session)
            coherence = CacheCoherenceService(settings.cache_generation_poll_seconds)
            await coherence.ensure_defaults(session)
            update_safety = UpdateSafetyService(settings)
            current_schema_head = MIGRATIONS[-1].version
            await update_safety.register(
                session,
                schema_head=current_schema_head,
                metadata={"phase": "render-predeploy"},
            )
            compatibility_checks = await update_safety.assert_compatible(
                session,
                schema_order=tuple(item.version for item in MIGRATIONS),
                current_schema_head=current_schema_head,
            )
            await update_safety.mark_ready(session, checks=compatibility_checks)
            await session.commit()

        if settings.redis_url:
            redis_client = Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                protocol=2,
                socket_connect_timeout=3,
                socket_timeout=2,
                health_check_interval=30,
                retry=Retry(ExponentialBackoff(cap=1.0, base=0.05), retries=3),
                retry_on_error=(RedisConnectionError, RedisTimeoutError),
            )
            await redis_client.ping()

        async with database.session_factory() as session:
            result = await DeploymentGateService(settings, bot).run(
                session,
                redis_client=redis_client,
                include_telegram=True,
                include_webhook=False,
                include_worker=False,
                include_release=False,
                persist=True,
            )
            await session.commit()
        output = {
            "version": __version__,
            "release_id": settings.release_id,
            "latest_migration": MIGRATIONS[-1].version,
            "applied_migrations": applied,
            "compatibility": compatibility_checks,
            "gate": result,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    finally:
        if redis_client is not None:
            with contextlib.suppress(Exception):
                await redis_client.aclose()
        with contextlib.suppress(Exception):
            await bot.session.close()
        await database.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
