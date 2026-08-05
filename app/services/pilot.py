from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import (
    BackupRun,
    BackupRunStatus,
    InventoryItem,
    InventoryStatus,
    PilotValidationRun,
    PilotValidationStatus,
    RecoveryDrill,
    RecoveryDrillStatus,
)

Probe = Callable[[], Awaitable[tuple[bool, str]]]


class PilotValidationService:
    """Runs production-like dependency gates and stores auditable results."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def _with_timeout(self, probe: Probe) -> tuple[bool, str]:
        try:
            return await asyncio.wait_for(
                probe(), timeout=max(1, self.settings.pilot_validation_timeout_seconds)
            )
        except TimeoutError:
            return False, "timeout"
        except Exception as exc:  # external dependency boundary
            return False, type(exc).__name__

    async def validate(
        self,
        session: AsyncSession,
        *,
        redis_probe: Probe | None = None,
        telegram_probe: Probe | None = None,
        storage_probe: Probe | None = None,
    ) -> PilotValidationRun:
        run = PilotValidationRun(
            release_id=self.settings.release_id,
            environment=self.settings.environment,
            status=PilotValidationStatus.RUNNING.value,
        )
        session.add(run)
        await session.flush()

        checks: dict[str, dict[str, Any]] = {}
        blockers = 0
        warnings = 0

        async def database_probe() -> tuple[bool, str]:
            await session.execute(text("SELECT 1"))
            return True, "ok"

        checks["database"] = await self._check(database_probe, required=True)

        checks["redis"] = await self._check(
            redis_probe,
            required=self.settings.pilot_require_redis,
            configured=bool(self.settings.redis_url),
        )
        checks["telegram"] = await self._check(telegram_probe, required=True)
        checks["storage"] = await self._check(
            storage_probe,
            required=self.settings.pilot_require_storage,
            configured=bool(self.settings.backup_s3_bucket and self.settings.backup_s3_endpoint),
        )

        backup_ok, backup_detail = await self._verified_backup_status(session)
        checks["verified_backup"] = {
            "ok": backup_ok,
            "required": self.settings.pilot_require_verified_backup,
            "detail": backup_detail,
        }

        available = int(
            await session.scalar(
                select(func.count()).select_from(InventoryItem).where(
                    InventoryItem.status == InventoryStatus.AVAILABLE.value
                )
            )
            or 0
        )
        inventory_ok = available >= max(0, self.settings.pilot_min_free_inventory)
        checks["inventory_capacity"] = {
            "ok": inventory_ok,
            "required": False,
            "detail": f"available={available}",
        }

        for check in checks.values():
            if check["ok"]:
                continue
            if check.get("required"):
                blockers += 1
            else:
                warnings += 1

        run.checks_json = checks
        run.blocking_failures = blockers
        run.warnings = warnings
        run.status = (
            PilotValidationStatus.PASSED.value
            if blockers == 0
            else PilotValidationStatus.FAILED.value
        )
        run.completed_at = datetime.now(UTC)
        await session.flush()
        return run

    async def _check(
        self,
        probe: Probe | None,
        *,
        required: bool,
        configured: bool = True,
    ) -> dict[str, Any]:
        if not configured:
            return {"ok": False, "required": required, "detail": "not_configured"}
        if probe is None:
            return {"ok": False, "required": required, "detail": "probe_unavailable"}
        ok, detail = await self._with_timeout(probe)
        return {"ok": ok, "required": required, "detail": detail[:300]}

    async def _verified_backup_status(self, session: AsyncSession) -> tuple[bool, str]:
        latest = await session.scalar(
            select(BackupRun)
            .where(BackupRun.status == BackupRunStatus.VERIFIED.value)
            .order_by(BackupRun.completed_at.desc())
            .limit(1)
        )
        if not latest or not latest.completed_at:
            return False, "no_verified_backup"
        age = datetime.now(UTC) - latest.completed_at
        if age > timedelta(hours=max(1, self.settings.pilot_backup_max_age_hours)):
            return False, f"stale_hours={int(age.total_seconds() // 3600)}"
        return True, f"backup_id={latest.id}"

    async def latest(self, session: AsyncSession) -> PilotValidationRun | None:
        return await session.scalar(
            select(PilotValidationRun).order_by(PilotValidationRun.created_at.desc()).limit(1)
        )

    async def record_recovery_drill(
        self,
        session: AsyncSession,
        *,
        public_id: str,
        source_backup_id: int,
        target_fingerprint: str,
        restored_fingerprint: str,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> RecoveryDrill:
        passed = bool(target_fingerprint) and target_fingerprint == restored_fingerprint and not error
        row = RecoveryDrill(
            public_id=public_id[:48],
            drill_type="backup_restore",
            source_backup_id=source_backup_id,
            target_fingerprint=target_fingerprint[:128],
            restored_fingerprint=restored_fingerprint[:128],
            status=(RecoveryDrillStatus.PASSED.value if passed else RecoveryDrillStatus.FAILED.value),
            result_json=result or {},
            error=error[:2000],
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        session.add(row)
        await session.flush()
        return row
