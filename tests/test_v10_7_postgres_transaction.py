from __future__ import annotations

import os

import pytest

pytest.importorskip("asyncpg")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_postgresql_transaction_rollback_does_not_leak_session_state() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL PostgreSQL connection was not provided")
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TEMP TABLE cp_patch_rollback_probe(value integer)"))
            transaction = await connection.begin_nested()
            await connection.execute(text("INSERT INTO cp_patch_rollback_probe VALUES (1)"))
            await transaction.rollback()
            count = await connection.scalar(text("SELECT COUNT(*) FROM cp_patch_rollback_probe"))
            assert int(count or 0) == 0
    finally:
        await engine.dispose()
