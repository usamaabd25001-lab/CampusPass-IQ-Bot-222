from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import Database
from app.db.models import RuntimeLease

logger = logging.getLogger(__name__)


class RuntimeLeaseError(RuntimeError):
    pass


class RuntimeLeaseGuard:
    """Database-backed singleton lease for Telegram polling.

    Railway can overlap old and new deployments for a short period. A renewable row lock prevents
    both replicas from calling getUpdates with the same bot token, which otherwise triggers
    TelegramConflictError and intermittent button behaviour.
    """

    def __init__(
        self,
        database: Database,
        *,
        bot_token: str,
        release_id: str,
        ttl_seconds: int = 45,
    ) -> None:
        fingerprint = hashlib.sha256(bot_token.encode("utf-8")).hexdigest()[:20]
        self.database = database
        self.lease_key = f"telegram-polling:{fingerprint}"
        self.owner_id = f"{release_id}:{secrets.token_hex(6)}"
        self.ttl_seconds = max(20, int(ttl_seconds))
        self._task: asyncio.Task[None] | None = None
        self._owner_task: asyncio.Task[object] | None = None
        self._stopped = asyncio.Event()

    async def acquire(self, *, wait_seconds: int = 90) -> None:
        deadline = asyncio.get_running_loop().time() + max(0, int(wait_seconds))
        while True:
            now = datetime.now(UTC)
            expires = now + timedelta(seconds=self.ttl_seconds)
            busy = False
            async with self.database.session_factory() as session:
                row = await session.scalar(
                    select(RuntimeLease)
                    .where(RuntimeLease.lease_key == self.lease_key)
                    .with_for_update()
                )
                if row is None:
                    try:
                        async with session.begin_nested():
                            row = RuntimeLease(
                                lease_key=self.lease_key,
                                owner_id=self.owner_id,
                                expires_at=expires,
                                heartbeat_at=now,
                                metadata_json={"component": "telegram_polling"},
                            )
                            session.add(row)
                            await session.flush()
                    except IntegrityError:
                        row = await session.scalar(
                            select(RuntimeLease)
                            .where(RuntimeLease.lease_key == self.lease_key)
                            .with_for_update()
                        )
                if row is None:
                    raise RuntimeLeaseError("Could not create Telegram polling lease")
                busy = row.owner_id != self.owner_id and row.expires_at > now
                if not busy:
                    row.owner_id = self.owner_id
                    row.expires_at = expires
                    row.heartbeat_at = now
                    await session.commit()
            if not busy:
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeLeaseError(
                    "Another active CampusPass instance still owns Telegram polling"
                )
            logger.info("Waiting for previous Telegram polling instance to stop")
            await asyncio.sleep(2)
        self._owner_task = asyncio.current_task()
        self._task = asyncio.create_task(self._heartbeat(), name="telegram-polling-lease")
        logger.info("Telegram polling lease acquired owner=%s", self.owner_id)

    async def _heartbeat(self) -> None:
        interval = max(5.0, self.ttl_seconds / 3)
        try:
            while not self._stopped.is_set():
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=interval)
                    break
                except TimeoutError:
                    pass
                now = datetime.now(UTC)
                async with self.database.session_factory() as session:
                    row = await session.scalar(
                        select(RuntimeLease)
                        .where(RuntimeLease.lease_key == self.lease_key)
                        .with_for_update()
                    )
                    if row is None or row.owner_id != self.owner_id:
                        raise RuntimeLeaseError("Telegram polling lease ownership was lost")
                    row.heartbeat_at = now
                    row.expires_at = now + timedelta(seconds=self.ttl_seconds)
                    await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram polling lease heartbeat failed; stopping this bot replica")
            # Continuing to poll after losing the renewable lease can recreate TelegramConflictError.
            # Cancel the owning startup/polling task so Railway restarts a clean singleton replica.
            if self._owner_task is not None and not self._owner_task.done():
                self._owner_task.cancel()

    async def release(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._owner_task = None
        with contextlib.suppress(Exception):
            async with self.database.session_factory() as session:
                row = await session.scalar(
                    select(RuntimeLease)
                    .where(RuntimeLease.lease_key == self.lease_key)
                    .with_for_update()
                )
                if row is not None and row.owner_id == self.owner_id:
                    await session.delete(row)
                    await session.commit()
        logger.info("Telegram polling lease released owner=%s", self.owner_id)
