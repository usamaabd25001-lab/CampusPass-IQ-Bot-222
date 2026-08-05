import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.migrations import MIGRATIONS, run_migrations
from app.db.models import Base, SchemaMigration


def run(coro):
    return asyncio.run(coro)


async def _scenario() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        first = await run_migrations(session)
        second = await run_migrations(session)
        assert first == [migration.version for migration in MIGRATIONS]
        assert second == []
        count = int(await session.scalar(select(func.count()).select_from(SchemaMigration)) or 0)
        assert count == len(MIGRATIONS)
        await session.commit()
    await engine.dispose()


def test_migrations_are_idempotent():
    run(_scenario())
