from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.migrations import MIGRATIONS
from app.db.models import (
    Base,
    ReleaseCompatibility,
    RuntimeConfigGeneration,
    TelegramUpdateInbox,
)
from app.domain.callback_compat import normalize_callback, versioned_callback
from app.domain.update_safety import (
    generation_cache_key,
    included_in_rollout,
    parse_version,
    rollout_bucket,
    version_at_least,
)
from app.services.cache_coherence import CacheCoherenceService
from app.services.telegram_updates import TelegramUpdateInboxService
from app.services.update_safety import UpdateSafetyService

ROOT = Path(__file__).resolve().parents[1]


def run(coro):
    return asyncio.run(coro)


def settings() -> Settings:
    return Settings(
        BOT_TOKEN="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789",
        ADMIN_IDS="9001",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        ENVIRONMENT="development",
        RELEASE_ID="test-v117",
        UPDATE_MIN_COMPATIBLE_VERSION="11.6.0-render-e2e-hardening",
        UPDATE_MIN_COMPATIBLE_SCHEMA="11.6.0-render-e2e-hardening",
    )


def test_version_rollout_and_cache_keys_are_stable() -> None:
    assert parse_version("11.7.0-lts-turbo-update-safe").minor == 7
    assert version_at_least("11.7.0-lts", "11.6.0-render-e2e-hardening")
    assert rollout_bucket(subject=1234, salt="release") == rollout_bucket(
        subject=1234, salt="release"
    )
    assert included_in_rollout(subject=1, salt="x", percent=100)
    assert not included_in_rollout(subject=1, salt="x", percent=0)
    assert generation_cache_key("menus", 4, "main") == generation_cache_key(
        "menus", 4, "main"
    )


def test_old_and_versioned_callbacks_remain_compatible() -> None:
    assert normalize_callback("menu:home")[0] == "back_to_main"
    encoded = versioned_callback("offer:42")
    assert encoded == "v1|offer:42"
    assert normalize_callback(encoded) == ("offer:42", 1)
    # A future payload is not silently reinterpreted by an older release.
    assert normalize_callback("v999|offer:42") == ("v999|offer:42", 999)


async def _batch_claim_scenario() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = TelegramUpdateInboxService()
    async with factory() as session:
        for update_id in range(1, 7):
            await service.enqueue(
                session,
                update_id=update_id,
                payload={"update_id": update_id},
                release_id="r1",
                max_attempts=8,
            )
        await session.commit()
    async with factory() as session:
        first = await service.claim_batch(
            session, owner="a", lease_seconds=90, batch_size=4
        )
        await session.commit()
        assert [row.update_id for row in first] == [1, 2, 3, 4]
    async with factory() as session:
        second = await service.claim_batch(
            session, owner="b", lease_seconds=90, batch_size=4
        )
        await session.commit()
        assert [row.update_id for row in second] == [5, 6]
        assert all(row.status == service.PROCESSING for row in second)
    await engine.dispose()


def test_update_inbox_claims_in_ordered_batches() -> None:
    run(_batch_claim_scenario())


async def _coherence_and_compatibility_scenario() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    first = CacheCoherenceService(poll_seconds=0.25)
    second = CacheCoherenceService(poll_seconds=0.25)
    async with factory() as session:
        await first.ensure_defaults(session)
        await session.commit()
    async with factory() as session:
        assert await first.generation(session, "menus", force=True) == 1
        assert await second.generation(session, "menus", force=True) == 1
        assert await first.bump(session, "menus", reason="test") == 2
        await session.commit()
    async with factory() as session:
        assert await second.generation(session, "menus", force=True) == 2

        update_safety = UpdateSafetyService(settings())
        current = MIGRATIONS[-1].version
        await update_safety.register(session, schema_head=current)
        checks = await update_safety.assert_compatible(
            session,
            schema_order=tuple(item.version for item in MIGRATIONS),
            current_schema_head=current,
        )
        await update_safety.mark_ready(session, checks=checks)
        await session.commit()
        row = await session.scalar(
            select(ReleaseCompatibility).where(
                ReleaseCompatibility.release_id == "test-v117"
            )
        )
        assert row is not None and row.status == "ready"
        assert row.schema_head == "11.7.0-lts-turbo-update-safe"
    await engine.dispose()


def test_cache_generations_and_release_contracts() -> None:
    run(_coherence_and_compatibility_scenario())


def test_v117_tables_and_migration_are_registered() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert RuntimeConfigGeneration.__tablename__ in tables
    assert ReleaseCompatibility.__tablename__ in tables
    assert TelegramUpdateInbox.__tablename__ in tables
    assert len(tables) >= 157
    assert MIGRATIONS[-1].version == "11.7.1-all-features-ready"


def test_fast_webhook_and_graceful_drain_are_integrated() -> None:
    api = (ROOT / "app/api/server.py").read_text(encoding="utf-8")
    runtime = (ROOT / "app/services/telegram_updates.py").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "orjson.loads" in api
    assert "context.update_wakeup.set()" in api
    assert "Deployment draining" in api
    assert "claim_batch" in runtime
    assert "telegram_update_graceful_shutdown_seconds" in runtime
    assert 'http="httptools"' in main
    assert "CallbackCompatibilityOuterMiddleware" in main
