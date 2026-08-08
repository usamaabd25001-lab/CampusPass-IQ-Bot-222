from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.config import Settings
from app.db.models import DeploymentRelease, ReleaseCompatibility
from app.domain.update_safety import included_in_rollout, version_at_least


class UpdateSafetyService:
    """Release compatibility and deterministic rollout control.

    This service deliberately does not execute code updates. It blocks unsafe
    startup combinations and records the contract that future releases must
    preserve: database schema, callback payloads and durable event payloads.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def actor_in_rollout(self, actor_id: int | str, *, feature: str = "release") -> bool:
        return included_in_rollout(
            subject=actor_id,
            salt=f"{self.settings.release_id}:{feature}",
            percent=self.settings.update_rollout_percent,
        )

    async def register(
        self,
        session: AsyncSession,
        *, schema_head: str,
        metadata: dict[str, Any] | None = None,
    ) -> ReleaseCompatibility:
        row = await session.scalar(
            select(ReleaseCompatibility)
            .where(ReleaseCompatibility.release_id == self.settings.release_id)
            .with_for_update()
        )
        if row is None:
            row = ReleaseCompatibility(release_id=self.settings.release_id)
            session.add(row)
        row.version = __version__
        row.schema_head = schema_head
        row.minimum_release_version = self.settings.update_min_compatible_version
        row.minimum_schema_head = self.settings.update_min_compatible_schema
        row.callback_schema_version = self.settings.update_callback_schema_version
        row.event_schema_version = self.settings.update_event_schema_version
        row.rollout_percent = self.settings.update_rollout_percent
        row.status = "starting"
        row.metadata_json = metadata or {}
        row.checked_at = datetime.now(UTC)
        await session.flush()
        return row

    async def assert_compatible(
        self,
        session: AsyncSession,
        *, schema_order: tuple[str, ...],
        current_schema_head: str,
    ) -> dict[str, Any]:
        minimum_version_ok = version_at_least(
            __version__, self.settings.update_min_compatible_version
        )
        try:
            current_index = schema_order.index(current_schema_head)
            minimum_index = schema_order.index(self.settings.update_min_compatible_schema)
        except ValueError as exc:
            raise RuntimeError("Update compatibility references an unknown schema head") from exc
        schema_ok = current_index >= minimum_index

        previous_release: DeploymentRelease | None = None
        if self.settings.previous_release_id:
            previous_release = await session.scalar(
                select(DeploymentRelease)
                .where(DeploymentRelease.release_id == self.settings.previous_release_id)
                .order_by(DeploymentRelease.started_at.desc())
                .limit(1)
            )
        previous_schema_ok = True
        previous_schema = ""
        if previous_release is not None:
            previous_schema = previous_release.migration_version or ""
            if previous_schema:
                try:
                    previous_schema_ok = (
                        schema_order.index(previous_schema) >= minimum_index
                    )
                except ValueError:
                    previous_schema_ok = False

        checks = {
            "version": {"ok": minimum_version_ok, "minimum": self.settings.update_min_compatible_version},
            "schema": {
                "ok": schema_ok,
                "current": current_schema_head,
                "minimum": self.settings.update_min_compatible_schema,
            },
            "previous_release": {
                "ok": previous_schema_ok,
                "release_id": self.settings.previous_release_id,
                "schema": previous_schema,
            },
            "callback_schema_version": self.settings.update_callback_schema_version,
            "event_schema_version": self.settings.update_event_schema_version,
            "expand_contract_required": self.settings.update_require_expand_contract,
        }
        if not minimum_version_ok or not schema_ok or not previous_schema_ok:
            raise RuntimeError(f"Unsafe update compatibility: {checks}")
        return checks

    async def mark_ready(
        self, session: AsyncSession, *, checks: dict[str, Any]
    ) -> None:
        row = await session.scalar(
            select(ReleaseCompatibility)
            .where(ReleaseCompatibility.release_id == self.settings.release_id)
            .with_for_update()
        )
        if row is not None:
            row.status = "ready"
            row.metadata_json = checks
            row.checked_at = datetime.now(UTC)
            await session.flush()

    async def mark_failed(self, session: AsyncSession, error: str) -> None:
        row = await session.scalar(
            select(ReleaseCompatibility)
            .where(ReleaseCompatibility.release_id == self.settings.release_id)
            .with_for_update()
        )
        if row is not None:
            row.status = "failed"
            row.last_error = error[:2000]
            row.checked_at = datetime.now(UTC)
            await session.flush()
