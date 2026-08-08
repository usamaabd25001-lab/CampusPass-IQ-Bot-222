from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.database import Database
from app.core.security import SecretBox
from app.services.backups import BackupService


async def main() -> int:
    settings = get_settings()
    database = Database(settings)
    backup = BackupService(settings, SecretBox(settings))
    try:
        await database.wait_until_ready()
        await database.create_tables()
        async with database.session_factory() as session:
            run = await backup.create(session)
            await session.commit()
        print(f"backup={run.public_id} status={run.status} bytes={run.size_bytes}")
        if run.last_error:
            print(f"error={run.last_error}")
        return 0 if run.status == "verified" else 1
    finally:
        await database.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
