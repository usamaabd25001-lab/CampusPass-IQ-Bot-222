from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.config import Settings
from app.db.models import (
    BackupRun,
    DeploymentRelease,
    DeploymentStatus,
    RuntimeIncident,
    RuntimeIncidentStatus,
    ScheduledRun,
    ScheduledRunStatus,
    SchemaMigration,
)


class OperationsService:
    """Database-backed deployment, scheduled-run and incident control plane."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def latest_migration(self, session: AsyncSession) -> str:
        return str(
            await session.scalar(
                select(SchemaMigration.version)
                .order_by(SchemaMigration.applied_at.desc())
                .limit(1)
            )
            or ""
        )

    async def register_release(self, session: AsyncSession) -> DeploymentRelease:
        query = select(DeploymentRelease).where(
            DeploymentRelease.release_id == self.settings.release_id,
            DeploymentRelease.runtime_mode == self.settings.runtime_mode,
        )
        release = await session.scalar(query.with_for_update())
        migration = await self.latest_migration(session)
        now = datetime.now(UTC)
        if release is None:
            try:
                async with session.begin_nested():
                    release = DeploymentRelease(
                        release_id=self.settings.release_id,
                        version=__version__,
                        environment=self.settings.environment,
                        runtime_mode=self.settings.runtime_mode,
                        git_sha=self.settings.git_sha,
                        previous_release_id=self.settings.previous_release_id,
                        migration_version=migration,
                        status=DeploymentStatus.STARTING.value,
                        started_at=now,
                        metadata_json={"hosted": True},
                    )
                    session.add(release)
                    await session.flush()
            except IntegrityError:
                release = await session.scalar(query.with_for_update())
                if release is None:  # pragma: no cover - defensive database race
                    raise
        release.version = __version__
        release.environment = self.settings.environment
        release.runtime_mode = self.settings.runtime_mode
        release.git_sha = self.settings.git_sha
        release.previous_release_id = self.settings.previous_release_id
        release.migration_version = migration
        release.status = DeploymentStatus.STARTING.value
        release.started_at = now
        release.ready_at = None
        release.stopped_at = None
        release.last_error = None
        await session.flush()
        return release

    async def mark_release_ready(self, session: AsyncSession) -> None:
        release = await session.scalar(
            select(DeploymentRelease)
            .where(
                DeploymentRelease.release_id == self.settings.release_id,
                DeploymentRelease.runtime_mode == self.settings.runtime_mode,
            )
            .with_for_update()
        )
        if release:
            release.status = DeploymentStatus.READY.value
            release.ready_at = datetime.now(UTC)
            release.migration_version = await self.latest_migration(session)
            await session.flush()

    async def mark_release_failed(self, session: AsyncSession, error: str) -> None:
        release = await session.scalar(
            select(DeploymentRelease)
            .where(
                DeploymentRelease.release_id == self.settings.release_id,
                DeploymentRelease.runtime_mode == self.settings.runtime_mode,
            )
            .with_for_update()
        )
        if release:
            release.status = DeploymentStatus.FAILED.value
            release.last_error = error[:1000]
            release.stopped_at = datetime.now(UTC)
            await session.flush()

    async def mark_release_stopped(self, session: AsyncSession) -> None:
        release = await session.scalar(
            select(DeploymentRelease)
            .where(
                DeploymentRelease.release_id == self.settings.release_id,
                DeploymentRelease.runtime_mode == self.settings.runtime_mode,
            )
            .with_for_update()
        )
        if release:
            if release.status != DeploymentStatus.FAILED.value:
                release.status = DeploymentStatus.STOPPED.value
            release.stopped_at = datetime.now(UTC)
            await session.flush()

    async def claim_scheduled_run(
        self,
        session: AsyncSession,
        task_name: str,
        schedule_key: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ScheduledRun | None:
        now = datetime.now(UTC)
        query = select(ScheduledRun).where(
            ScheduledRun.task_name == task_name,
            ScheduledRun.schedule_key == schedule_key,
        )
        row = await session.scalar(query.with_for_update())
        if row is None:
            try:
                async with session.begin_nested():
                    row = ScheduledRun(
                        task_name=task_name[:100],
                        schedule_key=schedule_key[:160],
                        status=ScheduledRunStatus.RUNNING.value,
                        lease_owner=self.settings.release_id,
                        lease_expires_at=now
                        + timedelta(seconds=self.settings.scheduler_lease_seconds),
                        metadata_json=metadata or {},
                    )
                    session.add(row)
                    await session.flush()
                    return row
            except IntegrityError:
                row = await session.scalar(query.with_for_update())
                if row is None:  # pragma: no cover - defensive database race
                    raise
        if row.status == ScheduledRunStatus.SUCCEEDED.value:
            return None
        if (
            row.status == ScheduledRunStatus.RUNNING.value
            and row.lease_expires_at
            and row.lease_expires_at > now
            and row.lease_owner != self.settings.release_id
        ):
            return None
        row.status = ScheduledRunStatus.RUNNING.value
        row.lease_owner = self.settings.release_id
        row.lease_expires_at = now + timedelta(
            seconds=self.settings.scheduler_lease_seconds
        )
        row.started_at = now
        row.completed_at = None
        row.last_error = None
        row.attempts += 1
        row.metadata_json = metadata or row.metadata_json
        await session.flush()
        return row

    async def finish_scheduled_run(
        self,
        session: AsyncSession,
        row: ScheduledRun,
        *,
        success: bool,
        error: str = "",
    ) -> None:
        row.status = (
            ScheduledRunStatus.SUCCEEDED.value if success else ScheduledRunStatus.FAILED.value
        )
        row.completed_at = datetime.now(UTC)
        row.lease_expires_at = None
        row.last_error = error[:2000] or None
        await session.flush()

    async def record_incident(
        self,
        session: AsyncSession,
        *,
        code: str,
        severity: str,
        source: str,
        summary: str,
        details: str = "",
    ) -> RuntimeIncident:
        now = datetime.now(UTC)
        incident = await session.scalar(
            select(RuntimeIncident).where(RuntimeIncident.code == code).with_for_update()
        )
        if incident is None:
            incident = RuntimeIncident(
                code=code[:120],
                severity=severity[:20],
                source=source[:80],
                summary=summary[:255],
                details=details[:4000],
                status=RuntimeIncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(incident)
        else:
            incident.severity = severity[:20]
            incident.source = source[:80]
            incident.summary = summary[:255]
            incident.details = details[:4000]
            incident.status = RuntimeIncidentStatus.OPEN.value
            incident.last_seen_at = now
            incident.resolved_at = None
            incident.occurrences += 1
        await session.flush()
        return incident

    async def resolve_incident(self, session: AsyncSession, code: str) -> bool:
        incident = await session.scalar(
            select(RuntimeIncident).where(RuntimeIncident.code == code).with_for_update()
        )
        if not incident:
            return False
        incident.status = RuntimeIncidentStatus.RESOLVED.value
        incident.resolved_at = datetime.now(UTC)
        await session.flush()
        return True

    async def cleanup(self, session: AsyncSession) -> dict[str, int]:
        now = datetime.now(UTC)
        scheduled_before = now - timedelta(days=self.settings.scheduled_run_retention_days)
        incidents_before = now - timedelta(days=self.settings.incident_retention_days)
        deleted_runs = await session.execute(
            delete(ScheduledRun).where(
                ScheduledRun.completed_at.is_not(None),
                ScheduledRun.completed_at < scheduled_before,
            )
        )
        deleted_incidents = await session.execute(
            delete(RuntimeIncident).where(
                RuntimeIncident.status == RuntimeIncidentStatus.RESOLVED.value,
                RuntimeIncident.resolved_at.is_not(None),
                RuntimeIncident.resolved_at < incidents_before,
            )
        )
        return {
            "scheduled_runs": int(deleted_runs.rowcount or 0),
            "incidents": int(deleted_incidents.rowcount or 0),
        }

    async def status_snapshot(self, session: AsyncSession) -> dict[str, Any]:
        latest_release = await session.scalar(
            select(DeploymentRelease)
            .where(
                DeploymentRelease.release_id == self.settings.release_id,
                DeploymentRelease.runtime_mode == self.settings.runtime_mode,
            )
            .order_by(DeploymentRelease.started_at.desc())
            .limit(1)
        )
        component_releases = list(
            (
                await session.scalars(
                    select(DeploymentRelease)
                    .where(DeploymentRelease.release_id == self.settings.release_id)
                    .order_by(DeploymentRelease.runtime_mode)
                )
            ).all()
        )
        latest_backup = await session.scalar(
            select(BackupRun).order_by(BackupRun.started_at.desc()).limit(1)
        )
        open_incidents = int(
            await session.scalar(
                select(func.count())
                .select_from(RuntimeIncident)
                .where(RuntimeIncident.status != RuntimeIncidentStatus.RESOLVED.value)
            )
            or 0
        )
        failed_runs = int(
            await session.scalar(
                select(func.count())
                .select_from(ScheduledRun)
                .where(ScheduledRun.status == ScheduledRunStatus.FAILED.value)
            )
            or 0
        )
        return {
            "release": {
                "release_id": latest_release.release_id if latest_release else "",
                "version": latest_release.version if latest_release else __version__,
                "status": latest_release.status if latest_release else "unknown",
                "environment": latest_release.environment if latest_release else self.settings.environment,
                "runtime_mode": latest_release.runtime_mode if latest_release else self.settings.runtime_mode,
                "git_sha": latest_release.git_sha if latest_release else self.settings.git_sha,
                "started_at": latest_release.started_at.isoformat() if latest_release else None,
                "ready_at": latest_release.ready_at.isoformat() if latest_release and latest_release.ready_at else None,
            },
            "components": [
                {
                    "runtime_mode": item.runtime_mode,
                    "status": item.status,
                    "ready_at": item.ready_at.isoformat() if item.ready_at else None,
                    "last_error": item.last_error,
                }
                for item in component_releases
            ],
            "backup": {
                "enabled": self.settings.backup_enabled,
                "configured": self.settings.backup_ready,
                "status": latest_backup.status if latest_backup else "never",
                "public_id": latest_backup.public_id if latest_backup else "",
                "started_at": latest_backup.started_at.isoformat() if latest_backup else None,
                "verified_at": latest_backup.verified_at.isoformat() if latest_backup and latest_backup.verified_at else None,
                "size_bytes": latest_backup.size_bytes if latest_backup else 0,
                "last_error": latest_backup.last_error if latest_backup else None,
            },
            "open_incidents": open_incidents,
            "failed_scheduled_runs": failed_runs,
        }
