from __future__ import annotations

import asyncio
import json

from sqlalchemy import func, inspect, select, text

from app.core.config import get_settings
from app.core.database import Database
from app.core.db_url import safe_database_label
from app.db.models import User


async def main() -> None:
    settings = get_settings()
    database = Database(settings)
    try:
        await database.wait_until_ready()
        async with database.session_factory() as session:
            version = str(await session.scalar(text("SELECT version()")) or "")
            users = int(await session.scalar(select(func.count()).select_from(User)) or 0)
            connection = await session.connection()
            tables = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
        print(
            json.dumps(
                {
                    "ok": True,
                    "database": safe_database_label(settings.database_url),
                    "postgres": version.split(",", 1)[0],
                    "campuspass_tables": len([name for name in tables if name.startswith("cp_")]),
                    "users": users,
                    "ssl_mode": settings.db_ssl_mode,
                    "pool_size": settings.db_pool_size,
                },
                ensure_ascii=False,
            )
        )
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
