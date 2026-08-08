from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.database import Database
from app.core.security import SecretBox
from app.db.migrations import run_migrations
from app.db.models import (
    Base,
    Category,
    DeliveryType,
    InventoryItem,
    InventoryStatus,
    Offer,
    OfferStatus,
    Order,
    Provider,
    ProviderStatus,
    PurchaseReservation,
    User,
)
from app.db.seed import seed_defaults
from app.services.container import Services


class NullBot:
    async def __call__(self, method, request_timeout=None):
        del method, request_timeout
        return True

    async def send_message(self, *args, **kwargs):
        del args, kwargs
        return None

    async def send_chat_action(self, *args, **kwargs):
        del args, kwargs
        return True


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percent)))
    return ordered[index]


def validate_dedicated_database(database_url: str) -> None:
    normalized = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    database_name = parsed.path.lstrip("/").lower()
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise RuntimeError("LOAD_TEST_DATABASE_URL must be PostgreSQL")
    allowed_markers = ("load", "stress", "staging", "stage", "test", "qa")
    if not any(marker in database_name for marker in allowed_markers):
        raise RuntimeError(
            "The database name must contain load/stress/staging/test/qa. "
            "Use a dedicated disposable database, never production."
        )
    if os.environ.get("LOAD_TEST_CONFIRMATION") != "RESET_DEDICATED_LOAD_TEST_DATABASE":
        raise RuntimeError("LOAD_TEST_CONFIRMATION is missing or invalid")


def build_settings(database_url: str) -> Settings:
    return Settings(
        BOT_TOKEN="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",  # nosec B106
        ADMIN_IDS="9001",
        DATABASE_URL=database_url,
        ENVIRONMENT="test",
        DEFAULT_PROVIDER_PLAN="pro",
        ENCRYPTION_KEY="load-test-encryption-key-keep-out-of-production",
        REPORT_SECRET_KEY="load-test-report-key-keep-out-of-production",
        FEATURE_EMAIL_CODES=False,
        FEATURE_GEMINI=False,
        FEATURE_MASTERCARD=False,
        FEATURE_REPORTS=False,
    )


async def reset_database(database: Database) -> None:
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    async with database.session_factory() as session:
        await run_migrations(session)
        await seed_defaults(session)
        await session.commit()


async def seed_scenario(
    database: Database,
    services: Services,
    secrets: SecretBox,
    attempts: int,
    inventory_count: int,
) -> tuple[int, list[int], str]:
    run_id = uuid.uuid4().hex[:10]
    async with database.session_factory() as session:
        provider = Provider(
            name_ar=f"منصة ضغط {run_id}",
            name_en=f"Load Test {run_id}",
            slug=f"load-test-{run_id}",
            status=ProviderStatus.ACTIVE.value,
            management_percent=5,
        )
        category = Category(name=f"Load Test {run_id}")
        session.add_all([provider, category])
        await session.flush()
        offer = Offer(
            provider_id=provider.id,
            category_id=category.id,
            title=f"Concurrent Inventory {run_id}",
            description="Synthetic concurrency load test",
            price_iqd=1000,
            service_fee_iqd=100,
            delivery_type=DeliveryType.INVENTORY_ACCOUNT.value,
            status=OfferStatus.ACTIVE.value,
        )
        session.add(offer)
        await session.flush()
        users = [
            User(
                telegram_id=8_000_000_000 + index,
                telegram_name=f"Load User {index}",
                referral_code=f"L{run_id}{index:06d}"[:32],
            )
            for index in range(attempts)
        ]
        session.add_all(users)
        inventory = [
            InventoryItem(
                offer_id=offer.id,
                item_kind="account",
                label=f"Load Item {index}",
                encrypted_payload=secrets.encrypt(
                    json.dumps({"login": f"load-{run_id}-{index}@example.invalid"})
                ),
                status=InventoryStatus.AVAILABLE.value,
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
            for index in range(inventory_count)
        ]
        session.add_all(inventory)
        await session.flush()
        user_ids = [user.id for user in users]
        await session.commit()
        return offer.id, user_ids, run_id


async def create_one_order(
    database: Database,
    services: Services,
    offer_id: int,
    user_id: int,
    start_event: asyncio.Event,
    semaphore: asyncio.Semaphore,
) -> dict[str, object]:
    await start_event.wait()
    async with semaphore:
        started = time.perf_counter()
        async with database.session_factory() as session:
            try:
                offer = await session.get(Offer, offer_id)
                user = await session.get(User, user_id)
                if not offer or not user:
                    raise RuntimeError("Load-test fixture disappeared")
                order = await services.orders.create(
                    session,
                    user,
                    offer,
                    {"source": "github-actions-load-test"},
                )
                await session.commit()
                return {
                    "status": "success",
                    "order_id": order.id,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }
            except ValueError as exc:
                await session.rollback()
                return {
                    "status": "rejected",
                    "reason": str(exc),
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }
            except Exception as exc:
                await session.rollback()
                return {
                    "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }


async def verify_results(
    database: Database,
    offer_id: int,
    results: list[dict[str, object]],
    attempts: int,
    inventory_count: int,
    run_id: str,
) -> dict[str, object]:
    async with database.session_factory() as session:
        order_count = int(
            await session.scalar(
                select(func.count()).select_from(Order).where(Order.offer_id == offer_id)
            )
            or 0
        )
        reservation_count = int(
            await session.scalar(
                select(func.count())
                .select_from(PurchaseReservation)
                .where(PurchaseReservation.offer_id == offer_id)
            )
            or 0
        )
        reserved_inventory = int(
            await session.scalar(
                select(func.count())
                .select_from(InventoryItem)
                .where(
                    InventoryItem.offer_id == offer_id,
                    InventoryItem.status == InventoryStatus.RESERVED.value,
                )
            )
            or 0
        )
        duplicate_reservations = (
            await session.execute(
                select(
                    PurchaseReservation.inventory_item_id,
                    func.count(PurchaseReservation.id),
                )
                .where(PurchaseReservation.offer_id == offer_id)
                .group_by(PurchaseReservation.inventory_item_id)
                .having(func.count(PurchaseReservation.id) > 1)
            )
        ).all()

    successes = [result for result in results if result["status"] == "success"]
    rejected = [result for result in results if result["status"] == "rejected"]
    errors = [result for result in results if result["status"] == "error"]
    latencies = [float(result["latency_ms"]) for result in results]
    expected_successes = min(attempts, inventory_count)
    passed = (
        len(successes) == expected_successes
        and order_count == expected_successes
        and reservation_count == expected_successes
        and reserved_inventory == expected_successes
        and not duplicate_reservations
        and not errors
    )
    reason_counts: dict[str, int] = {}
    for result in rejected + errors:
        reason = str(result.get("reason", "unknown"))
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "ok": passed,
        "run_id": run_id,
        "attempts": attempts,
        "inventory_count": inventory_count,
        "successes": len(successes),
        "rejected": len(rejected),
        "errors": len(errors),
        "orders_committed": order_count,
        "reservations": reservation_count,
        "reserved_inventory": reserved_inventory,
        "duplicate_inventory_reservations": [list(row) for row in duplicate_reservations],
        "latency_ms": {
            "min": round(min(latencies, default=0), 2),
            "mean": round(statistics.fmean(latencies) if latencies else 0, 2),
            "p50": round(percentile(latencies, 0.50), 2),
            "p95": round(percentile(latencies, 0.95), 2),
            "p99": round(percentile(latencies, 0.99), 2),
            "max": round(max(latencies, default=0), 2),
        },
        "reasons": reason_counts,
    }


async def execute(args: argparse.Namespace) -> dict[str, object]:
    database_url = os.environ.get("LOAD_TEST_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("LOAD_TEST_DATABASE_URL is required")
    validate_dedicated_database(database_url)
    settings = build_settings(database_url)
    database = Database(settings)
    if database.engine.dialect.name != "postgresql":
        raise RuntimeError("Concurrency stress test requires PostgreSQL")
    secrets = SecretBox(settings)
    services = Services(NullBot(), settings, secrets)
    try:
        await reset_database(database)
        offer_id, user_ids, run_id = await seed_scenario(
            database,
            services,
            secrets,
            args.attempts,
            args.inventory,
        )
        start_event = asyncio.Event()
        semaphore = asyncio.Semaphore(args.workers)
        tasks = [
            asyncio.create_task(
                create_one_order(database, services, offer_id, user_id, start_event, semaphore)
            )
            for user_id in user_ids
        ]
        started = time.perf_counter()
        start_event.set()
        results = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - started
        summary = await verify_results(
            database,
            offer_id,
            results,
            args.attempts,
            args.inventory,
            run_id,
        )
        summary["elapsed_seconds"] = round(elapsed, 3)
        summary["attempts_per_second"] = round(args.attempts / elapsed if elapsed else 0, 2)
        return summary
    finally:
        await database.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stress-test concurrent CampusPass inventory reservations on a dedicated PostgreSQL database."
    )
    parser.add_argument("--attempts", type=int, default=500)
    parser.add_argument("--inventory", type=int, default=1)
    parser.add_argument("--workers", type=int, default=100)
    parser.add_argument("--output", default="load-test-result.json")
    args = parser.parse_args()
    if not 1 <= args.attempts <= 10_000:
        parser.error("--attempts must be between 1 and 10000")
    if not 1 <= args.inventory <= args.attempts:
        parser.error("--inventory must be between 1 and attempts")
    if not 1 <= args.workers <= min(1000, args.attempts):
        parser.error("--workers must be between 1 and min(1000, attempts)")
    return args


def main() -> None:
    args = parse_args()
    result = asyncio.run(execute(args))
    output = Path(args.output)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
