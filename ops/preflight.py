from __future__ import annotations

import asyncio
import hashlib
import shutil

from redis.asyncio import Redis
from sqlalchemy import text

from app import __version__
from app.core.config import get_settings
from app.core.database import Database
from app.db.migrations import MIGRATIONS


async def main() -> int:
    settings = get_settings()
    checks: list[tuple[str, bool, str]] = []
    checks.append(
        (
            "release_id",
            settings.release_id != "local" or settings.environment != "production",
            settings.release_id,
        )
    )
    checks.append(
        (
            "pg_dump",
            bool(shutil.which(settings.backup_pg_dump_path)),
            settings.backup_pg_dump_path,
        )
    )
    checks.append(("pg_restore", bool(shutil.which("pg_restore")), "pg_restore"))
    database = Database(settings)
    try:
        await database.wait_until_ready()
        async with database.session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks.append(("database", True, "connected"))
    except Exception as exc:
        checks.append(("database", False, type(exc).__name__))
    finally:
        await database.close()

    if settings.runtime_mode in {"combined", "bot"} and settings.redis_url:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await redis.ping()
            checks.append(("redis", True, "connected"))
        except Exception as exc:
            checks.append(("redis", False, type(exc).__name__))
        finally:
            await redis.aclose()
    elif settings.runtime_mode in {"combined", "bot"} and settings.require_redis_in_production:
        checks.append(("redis", False, "required but REDIS_URL is empty"))
    else:
        checks.append(("redis", True, "optional/not required"))

    if settings.environment == "staging" and settings.staging_guard_enabled:
        current = hashlib.sha256(settings.bot_token.encode()).hexdigest()
        checks.append(
            (
                "staging-token-isolation",
                current != settings.staging_bot_token_fingerprint,
                "fingerprint checked",
            )
        )

    print(f"CampusPass preflight version={__version__} runtime={settings.runtime_mode}")
    print(f"Expected latest migration: {MIGRATIONS[-1].version}")
    failed = False
    for name, ok, details in checks:
        print(f"{'OK' if ok else 'FAIL'} {name}: {details}")
        failed = failed or not ok
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
