from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from datetime import UTC, datetime, timedelta

from aiogram import Dispatcher
from aiogram.types import Update
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import AppContext
from app.db.models import TelegramUpdateInbox
from app.domain.telegram_delivery import canonical_payload_digest, retry_delay_seconds

logger = logging.getLogger(__name__)


class TelegramUpdateInboxService:
    PENDING = "pending"
    PROCESSING = "processing"
    RETRY = "retry"
    DONE = "done"
    DEAD = "dead"

    @staticmethod
    def payload_digest(payload: dict) -> str:
        return canonical_payload_digest(payload)

    async def enqueue(
        self, session: AsyncSession, *, update_id: int, payload: dict, release_id: str, max_attempts: int
    ) -> tuple[TelegramUpdateInbox, bool]:
        digest = self.payload_digest(payload)
        existing = await session.scalar(
            select(TelegramUpdateInbox).where(TelegramUpdateInbox.update_id == update_id)
        )
        if existing is not None:
            if existing.payload_sha256 != digest:
                raise ValueError("Telegram update_id was reused with a different payload")
            return existing, False
        row = TelegramUpdateInbox(
            update_id=update_id,
            payload_sha256=digest,
            payload_json=payload,
            status=self.PENDING,
            max_attempts=max_attempts,
            release_id=release_id,
        )
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            existing = await session.scalar(
                select(TelegramUpdateInbox).where(TelegramUpdateInbox.update_id == update_id)
            )
            if existing is None:
                raise
            if existing.payload_sha256 != digest:
                raise ValueError("Telegram update_id collision")
            return existing, False
        return row, True

    async def claim_batch(
        self,
        session: AsyncSession,
        *,
        owner: str,
        lease_seconds: int,
        batch_size: int,
    ) -> list[TelegramUpdateInbox]:
        now = datetime.now(UTC)
        eligible = or_(
            (
                TelegramUpdateInbox.status.in_({self.PENDING, self.RETRY})
                & (TelegramUpdateInbox.available_at <= now)
            ),
            (
                (TelegramUpdateInbox.status == self.PROCESSING)
                & (TelegramUpdateInbox.lease_expires_at.is_not(None))
                & (TelegramUpdateInbox.lease_expires_at < now)
            ),
        )
        rows = list(
            (
                await session.scalars(
                    select(TelegramUpdateInbox)
                    .where(eligible)
                    .order_by(TelegramUpdateInbox.update_id)
                    .limit(max(1, min(int(batch_size), 64)))
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        for row in rows:
            row.status = self.PROCESSING
            row.attempts += 1
            row.lease_owner = owner
            row.lease_expires_at = lease_expires_at
            row.last_error = ""
        if rows:
            await session.flush()
        return rows

    async def claim_next(
        self, session: AsyncSession, *, owner: str, lease_seconds: int
    ) -> TelegramUpdateInbox | None:
        rows = await self.claim_batch(
            session,
            owner=owner,
            lease_seconds=lease_seconds,
            batch_size=1,
        )
        return rows[0] if rows else None

    async def mark_done(self, session: AsyncSession, row_id: int, *, owner: str) -> bool:
        row = await session.scalar(
            select(TelegramUpdateInbox)
            .where(TelegramUpdateInbox.id == row_id)
            .with_for_update()
        )
        if row is None or row.lease_owner != owner:
            return False
        row.status = self.DONE
        row.processed_at = datetime.now(UTC)
        row.lease_owner = None
        row.lease_expires_at = None
        await session.flush()
        return True

    async def mark_failed(
        self, session: AsyncSession, row_id: int, *, owner: str, error: str
    ) -> bool:
        row = await session.scalar(
            select(TelegramUpdateInbox)
            .where(TelegramUpdateInbox.id == row_id)
            .with_for_update()
        )
        if row is None or row.lease_owner != owner:
            return False
        row.last_error = error[:4000]
        row.lease_owner = None
        row.lease_expires_at = None
        if row.attempts >= row.max_attempts:
            row.status = self.DEAD
            row.processed_at = datetime.now(UTC)
        else:
            row.status = self.RETRY
            delay = retry_delay_seconds(row.attempts)
            row.available_at = datetime.now(UTC) + timedelta(seconds=delay)
        await session.flush()
        return True

    async def purge_completed(self, session: AsyncSession, *, retention_days: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        rows = list(
            (
                await session.scalars(
                    select(TelegramUpdateInbox).where(
                        TelegramUpdateInbox.status == self.DONE,
                        TelegramUpdateInbox.processed_at < cutoff,
                    ).limit(1000)
                )
            ).all()
        )
        for row in rows:
            await session.delete(row)
        return len(rows)


class TelegramUpdateRuntime:
    def __init__(self, context: AppContext, dispatcher: Dispatcher) -> None:
        self.context = context
        self.dispatcher = dispatcher
        self.owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:10]}"
        self.tasks: list[asyncio.Task] = []
        self.stop_event = asyncio.Event()

    async def start(self) -> None:
        if self.tasks:
            return
        self.stop_event.clear()
        self.context.draining = False
        for index in range(self.context.settings.telegram_update_consumers):
            self.tasks.append(
                asyncio.create_task(self._consume(index), name=f"telegram-update-{index}")
            )
        self.context.update_processor_ready = True

    async def stop(self) -> None:
        self.context.update_processor_ready = False
        self.context.draining = True
        self.stop_event.set()
        self.context.update_wakeup.set()
        if not self.tasks:
            return
        grace = self.context.settings.telegram_update_graceful_shutdown_seconds
        try:
            async with asyncio.timeout(grace):
                await asyncio.gather(*self.tasks, return_exceptions=True)
        except TimeoutError:
            logger.warning(
                "Telegram update drain exceeded %.1fs; cancelling remaining consumers inflight=%s",
                grace,
                self.context.update_inflight,
            )
            for task in self.tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()

    async def _wait_for_work(self) -> None:
        timeout = self.context.settings.telegram_update_idle_wait_ms / 1_000
        try:
            await asyncio.wait_for(self.context.update_wakeup.wait(), timeout=timeout)
        except TimeoutError:
            pass
        finally:
            self.context.update_wakeup.clear()

    async def _process_claimed(
        self, *, row_id: int, payload: dict, owner: str
    ) -> None:
        self.context.update_inflight += 1
        try:
            update = Update.model_validate(payload, context={"bot": self.context.bot})
            await self.dispatcher.feed_update(self.context.bot, update)
            async with self.context.database.session_factory() as session:
                await self.context.services.telegram_updates.mark_done(
                    session, row_id, owner=owner
                )
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Durable Telegram update processing failed row_id=%s", row_id)
            try:
                async with self.context.database.session_factory() as session:
                    await self.context.services.telegram_updates.mark_failed(
                        session,
                        row_id,
                        owner=owner,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    await session.commit()
            except Exception:
                logger.exception("Could not persist Telegram update retry state row_id=%s", row_id)
        finally:
            self.context.update_inflight = max(0, self.context.update_inflight - 1)

    async def _consume(self, index: int) -> None:
        owner = f"{self.owner}:{index}"
        while True:
            if self.stop_event.is_set():
                return
            try:
                async with self.context.database.session_factory() as session:
                    rows = await self.context.services.telegram_updates.claim_batch(
                        session,
                        owner=owner,
                        lease_seconds=self.context.settings.telegram_update_lease_seconds,
                        batch_size=self.context.settings.telegram_update_claim_batch_size,
                    )
                    claimed = [
                        (int(row.id), dict(row.payload_json or {})) for row in rows
                    ]
                    await session.commit()
                if not claimed:
                    await self._wait_for_work()
                    continue
                for row_id, payload in claimed:
                    await self._process_claimed(
                        row_id=row_id, payload=payload, owner=owner
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Telegram update consumer loop failed index=%s", index)
                await asyncio.sleep(0.10)

