from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import public_id
from app.db.migrations import MIGRATIONS
from app.db.models import (
    DeploymentGateRun,
    DeploymentRelease,
    DeploymentStatus,
    SchemaMigration,
    ReleaseCompatibility,
    WorkerHeartbeat,
)


class DeploymentGateService:
    def __init__(self, settings, bot) -> None:
        self.settings = settings
        self.bot = bot

    async def run(
        self,
        session: AsyncSession,
        *,
        redis_client=None,
        include_telegram: bool = True,
        include_webhook: bool = True,
        include_worker: bool = True,
        include_release: bool = True,
        persist: bool = True,
    ) -> dict:
        started = datetime.now(UTC)
        checks: dict[str, dict] = {}

        async def checked(name: str, operation):
            try:
                value = await operation()
                checks[name] = {"ok": True, "value": value}
            except Exception as exc:
                checks[name] = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:500]}"}

        async def db_check():
            return int(await session.scalar(text("SELECT 1")) or 0)

        async def schema_check():
            latest = await session.scalar(
                select(SchemaMigration.version).order_by(SchemaMigration.id.desc()).limit(1)
            )
            expected = MIGRATIONS[-1].version
            if latest != expected:
                raise RuntimeError(f"schema={latest!r}, expected={expected!r}")
            return latest

        async def release_check():
            release = await session.scalar(
                select(DeploymentRelease)
                .where(
                    DeploymentRelease.release_id == self.settings.release_id,
                    DeploymentRelease.runtime_mode == self.settings.runtime_mode,
                )
                .order_by(desc(DeploymentRelease.started_at))
                .limit(1)
            )
            if release is None:
                raise RuntimeError("release is not registered")
            if release.status != DeploymentStatus.READY.value:
                raise RuntimeError(f"release status is {release.status}")
            return release.status

        async def compatibility_check():
            row = await session.scalar(
                select(ReleaseCompatibility).where(
                    ReleaseCompatibility.release_id == self.settings.release_id
                )
            )
            if row is None:
                raise RuntimeError("release compatibility contract is missing")
            if row.status != "ready":
                raise RuntimeError(f"compatibility status is {row.status}")
            expected = MIGRATIONS[-1].version
            if row.schema_head != expected:
                raise RuntimeError(
                    f"compatibility schema={row.schema_head!r}, expected={expected!r}"
                )
            return {
                "schema": row.schema_head,
                "callbacks": row.callback_schema_version,
                "events": row.event_schema_version,
                "rollout_percent": row.rollout_percent,
            }

        async def redis_check():
            if redis_client is None:
                if self.settings.require_redis_in_production:
                    raise RuntimeError("Redis client is unavailable")
                return "not_required"
            pong = await redis_client.ping()
            if not pong:
                raise RuntimeError("Redis PING failed")
            return "pong"

        async def telegram_check():
            me = await self.bot.get_me()
            return {"id": me.id, "username": me.username or ""}

        async def webhook_check():
            if self.settings.telegram_delivery_mode != "webhook":
                return "polling"
            info = await self.bot.get_webhook_info()
            expected = f"{self.settings.public_base_url}{self.settings.telegram_webhook_path}"
            if info.url != expected:
                raise RuntimeError(f"webhook URL mismatch: {info.url!r}")
            if info.last_error_message:
                raise RuntimeError(f"Telegram webhook error: {info.last_error_message}")
            return {"url": info.url, "pending": info.pending_update_count}

        async def worker_check():
            if not self.settings.require_fresh_worker_heartbeat:
                return "not_required"
            cutoff = datetime.now(UTC) - timedelta(
                seconds=self.settings.enterprise_worker_stale_seconds
            )
            worker = await session.scalar(
                select(WorkerHeartbeat)
                .where(
                    WorkerHeartbeat.runtime_mode.in_({"worker", "combined"}),
                    WorkerHeartbeat.last_seen_at >= cutoff,
                )
                .order_by(WorkerHeartbeat.last_seen_at.desc())
                .limit(1)
            )
            if worker is None:
                raise RuntimeError("no fresh worker heartbeat")
            return {"worker_id": worker.worker_id, "last_seen_at": worker.last_seen_at.isoformat()}

        await checked("database", db_check)
        await checked("schema", schema_check)
        await checked("compatibility", compatibility_check)
        if include_release:
            await checked("release", release_check)
        await checked("redis", redis_check)
        if include_worker:
            await checked("worker", worker_check)
        if include_telegram:
            await checked("telegram", telegram_check)
            if include_webhook:
                await checked("webhook", webhook_check)

        ok = all(item.get("ok") for item in checks.values())
        result = {
            "ok": ok,
            "release_id": self.settings.release_id,
            "runtime_mode": self.settings.runtime_mode,
            "checks": checks,
            "started_at": started.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
        }
        if persist:
            run = DeploymentGateRun(
                public_id=public_id("GATE"),
                release_id=self.settings.release_id,
                environment=self.settings.environment,
                runtime_mode=self.settings.runtime_mode,
                status="passed" if ok else "failed",
                checks_json=checks,
                error="" if ok else "one or more deployment checks failed",
                started_at=started,
                completed_at=datetime.now(UTC),
            )
            session.add(run)
            await session.flush()
            result["public_id"] = run.public_id
        return result

    async def latest(self, session: AsyncSession) -> DeploymentGateRun | None:
        return await session.scalar(
            select(DeploymentGateRun)
            .order_by(DeploymentGateRun.started_at.desc())
            .limit(1)
        )
