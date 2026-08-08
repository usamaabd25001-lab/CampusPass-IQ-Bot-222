from __future__ import annotations

from datetime import UTC, datetime, timedelta
import asyncio
import time
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.config import Settings
from app.db.models import (
    BackupRun,
    BackupRunStatus,
    DeliveryJob,
    DeliveryJobStatus,
    DeploymentRelease,
    EmailAccount,
    EmailAccountStatus,
    EvidenceAsset,
    EvidenceStatus,
    InventoryRemediation,
    InventoryRemediationStatus,
    ModuleRecord,
    Notification,
    Order,
    OrderStatus,
    Refund,
    RefundStatus,
    RuntimeIncident,
    RuntimeIncidentStatus,
    ScheduledRun,
    ScheduledRunStatus,
    SchemaMigration,
    SupportTicket,
    SystemHealthSnapshot,
    TicketStatus,
)
from app.services.modules import ModuleRegistryService
from app.services.system_metrics import RuntimeMetricsService


class HealthService:
    def __init__(self, modules: ModuleRegistryService, settings: Settings, bot: Any | None = None) -> None:
        self.modules = modules
        self.settings = settings
        self.bot = bot
        self.runtime_metrics = RuntimeMetricsService()

    async def _redis_check(self) -> dict[str, Any]:
        if not self.settings.redis_url:
            return {"ok": False, "latency_ms": None, "error": "not_configured"}
        started = time.perf_counter()
        client = None
        try:
            from redis.asyncio import Redis
            client = Redis.from_url(self.settings.redis_url, socket_connect_timeout=1.5, socket_timeout=1.5, decode_responses=True)
            async with asyncio.timeout(2):
                await client.ping()
            return {"ok": True, "latency_ms": round((time.perf_counter()-started)*1000, 2), "error": None}
        except Exception as exc:
            return {"ok": False, "latency_ms": round((time.perf_counter()-started)*1000, 2), "error": type(exc).__name__}
        finally:
            if client is not None:
                await client.aclose()

    async def _telegram_check(self) -> dict[str, Any]:
        if self.bot is None:
            return {"ok": False, "latency_ms": None, "error": "bot_unavailable"}
        started = time.perf_counter()
        try:
            async with asyncio.timeout(2.5):
                me = await self.bot.get_me()
            return {"ok": True, "latency_ms": round((time.perf_counter()-started)*1000, 2), "username": me.username, "error": None}
        except Exception as exc:
            return {"ok": False, "latency_ms": round((time.perf_counter()-started)*1000, 2), "error": type(exc).__name__}

    async def snapshot(self, session: AsyncSession) -> dict[str, Any]:
        database_ok = True
        database_error = None
        try:
            await session.execute(text("SELECT 1"))
        except Exception as exc:  # pragma: no cover - database failure path
            database_ok = False
            database_error = type(exc).__name__

        now = datetime.now(UTC)
        failed_jobs = int(
            await session.scalar(
                select(func.count()).select_from(DeliveryJob).where(
                    DeliveryJob.status == DeliveryJobStatus.FAILED.value
                )
            )
            or 0
        )
        pending_jobs = int(
            await session.scalar(
                select(func.count()).select_from(DeliveryJob).where(
                    DeliveryJob.status == DeliveryJobStatus.PENDING.value
                )
            )
            or 0
        )
        stale_processing_jobs = int(
            await session.scalar(
                select(func.count()).select_from(DeliveryJob).where(
                    DeliveryJob.status == DeliveryJobStatus.PROCESSING.value,
                    or_(
                        DeliveryJob.lease_expires_at.is_(None),
                        DeliveryJob.lease_expires_at <= now,
                    ),
                )
            )
            or 0
        )
        failed_notifications = int(
            await session.scalar(
                select(func.count()).select_from(Notification).where(
                    Notification.delivery_status == "failed"
                )
            )
            or 0
        )
        pending_notifications = int(
            await session.scalar(
                select(func.count()).select_from(Notification).where(
                    Notification.delivery_status == "pending"
                )
            )
            or 0
        )
        payment_reviews = int(
            await session.scalar(
                select(func.count()).select_from(Order).where(
                    Order.status == OrderStatus.PAYMENT_REVIEW.value
                )
            )
            or 0
        )
        open_tickets = int(
            await session.scalar(
                select(func.count()).select_from(SupportTicket).where(
                    SupportTicket.status.not_in(
                        [TicketStatus.CLOSED.value, TicketStatus.RESOLVED.value]
                    )
                )
            )
            or 0
        )
        email_issues = int(
            await session.scalar(
                select(func.count()).select_from(EmailAccount).where(
                    EmailAccount.status.in_(
                        [
                            EmailAccountStatus.RECONNECT.value,
                            EmailAccountStatus.BLOCKED.value,
                        ]
                    )
                )
            )
            or 0
        )
        pending_refunds = int(
            await session.scalar(
                select(func.count()).select_from(Refund).where(
                    Refund.status.in_(
                        [
                            RefundStatus.REQUESTED.value,
                            RefundStatus.APPROVED.value,
                            RefundStatus.TRANSFER_REPORTED.value,
                        ]
                    )
                )
            )
            or 0
        )
        remediation_pending = int(
            await session.scalar(
                select(func.count()).select_from(InventoryRemediation).where(
                    InventoryRemediation.status.in_(
                        [
                            InventoryRemediationStatus.PENDING.value,
                            InventoryRemediationStatus.IN_PROGRESS.value,
                        ]
                    )
                )
            )
            or 0
        )
        evidence_registered = int(
            await session.scalar(
                select(func.count()).select_from(EvidenceAsset).where(
                    EvidenceAsset.status == EvidenceStatus.REGISTERED.value
                )
            )
            or 0
        )
        evidence_failed = int(
            await session.scalar(
                select(func.count()).select_from(EvidenceAsset).where(
                    EvidenceAsset.status == EvidenceStatus.FAILED.value
                )
            )
            or 0
        )
        evidence_expired = int(
            await session.scalar(
                select(func.count()).select_from(EvidenceAsset).where(
                    EvidenceAsset.status.not_in(
                        [EvidenceStatus.DELETED.value]
                    ),
                    EvidenceAsset.retention_until <= now,
                )
            )
            or 0
        )
        migration = await session.scalar(
            select(SchemaMigration.version).order_by(SchemaMigration.applied_at.desc()).limit(1)
        )
        latest_release = await session.scalar(
            select(DeploymentRelease)
            .where(
                DeploymentRelease.release_id == self.settings.release_id,
                DeploymentRelease.runtime_mode == self.settings.runtime_mode,
            )
            .order_by(DeploymentRelease.started_at.desc())
            .limit(1)
        )
        latest_backup = await session.scalar(
            select(BackupRun).order_by(BackupRun.started_at.desc()).limit(1)
        )
        open_incidents = int(
            await session.scalar(
                select(func.count()).select_from(RuntimeIncident).where(
                    RuntimeIncident.status != RuntimeIncidentStatus.RESOLVED.value
                )
            ) or 0
        )
        failed_scheduled_runs = int(
            await session.scalar(
                select(func.count()).select_from(ScheduledRun).where(
                    ScheduledRun.status == ScheduledRunStatus.FAILED.value
                )
            ) or 0
        )
        backup_stale = False
        if self.settings.backup_ready:
            backup_stale = (
                latest_backup is None
                or latest_backup.status != BackupRunStatus.VERIFIED.value
                or latest_backup.verified_at is None
                or latest_backup.verified_at
                < now - timedelta(hours=self.settings.backup_alert_after_hours)
            )

        await self.modules.sync(session)
        for key in ("users", "ui", "catalog", "orders", "payments", "inventory", "workflow"):
            await self.modules.mark_health(
                session, key, "ok" if database_ok else "error", database_error
            )
        await self.modules.mark_health(
            session,
            "email_codes",
            "warning" if email_issues else "ok",
            f"{email_issues} حساب بريد يحتاج مراجعة" if email_issues else None,
        )
        operational_errors = failed_jobs + stale_processing_jobs
        await self.modules.mark_health(
            session,
            "health",
            "error" if not database_ok else "warning" if operational_errors else "ok",
            database_error
            or (
                f"{failed_jobs} مهمة فاشلة و{stale_processing_jobs} مهمة عالقة"
                if operational_errors
                else None
            ),
        )
        modules = list(
            (
                await session.scalars(
                    select(ModuleRecord).order_by(ModuleRecord.is_critical.desc(), ModuleRecord.id)
                )
            ).all()
        )
        overall = "ok"
        if not database_ok or any(m.health_status == "error" and m.is_critical for m in modules):
            overall = "error"
        elif (
            failed_jobs
            or stale_processing_jobs
            or failed_notifications
            or email_issues
            or remediation_pending
            or evidence_failed
            or evidence_expired
            or open_incidents
            or failed_scheduled_runs
            or backup_stale
            or any(m.health_status == "warning" for m in modules)
        ):
            overall = "warning"
        runtime = self.runtime_metrics.snapshot().as_dict()
        redis_check, telegram_check = await asyncio.gather(self._redis_check(), self._telegram_check())
        result = {
            "status": overall,
            "version": __version__,
            "database": {"ok": database_ok, "error": database_error},
            "migration": migration,
            "operations": {
                "release": {
                    "release_id": latest_release.release_id if latest_release else self.settings.release_id,
                    "status": latest_release.status if latest_release else "unknown",
                    "environment": latest_release.environment if latest_release else self.settings.environment,
                    "runtime_mode": latest_release.runtime_mode if latest_release else self.settings.runtime_mode,
                    "git_sha": latest_release.git_sha if latest_release else self.settings.git_sha,
                    "ready_at": latest_release.ready_at.isoformat() if latest_release and latest_release.ready_at else None,
                },
                "backup": {
                    "enabled": self.settings.backup_enabled,
                    "configured": self.settings.backup_ready,
                    "status": latest_backup.status if latest_backup else "never",
                    "public_id": latest_backup.public_id if latest_backup else "",
                    "verified_at": latest_backup.verified_at.isoformat() if latest_backup and latest_backup.verified_at else None,
                    "size_bytes": latest_backup.size_bytes if latest_backup else 0,
                    "stale": backup_stale,
                    "last_error": latest_backup.last_error if latest_backup else None,
                },
                "open_incidents": open_incidents,
                "failed_scheduled_runs": failed_scheduled_runs,
                "encryption_key_version": self.settings.encryption_key_version,
            },
            "delivery_jobs": {
                "pending": pending_jobs,
                "failed": failed_jobs,
                "stale_processing": stale_processing_jobs,
            },
            "notifications": {
                "pending": pending_notifications,
                "failed": failed_notifications,
            },
            "payment_reviews": payment_reviews,
            "open_tickets": open_tickets,
            "refunds": {"pending": pending_refunds},
            "inventory_remediation": {"pending": remediation_pending},
            "evidence": {
                "registered": evidence_registered,
                "failed": evidence_failed,
                "expired": evidence_expired,
            },
            "email_accounts_needing_attention": email_issues,
            "commercial_safety": {
                "money_flow_model": self.settings.money_flow_model,
                "provider_withdrawals_enabled": self.settings.feature_provider_withdrawals,
                "provider_withdrawals_configured": self.settings.provider_withdrawals_ready,
                "database_ssl_mode": self.settings.db_ssl_mode,
                "redis_required_in_production": self.settings.require_redis_in_production,
                "external_evidence_storage_enabled": self.settings.evidence_external_storage_enabled,
                "external_evidence_storage_configured": self.settings.evidence_external_storage_ready,
                "external_evidence_storage_required": self.settings.require_external_evidence_storage_in_production,
                "privacy_policy_version": self.settings.privacy_policy_version,
                "runtime_mode": self.settings.runtime_mode,
                "release_id": self.settings.release_id,
                "backup_enabled": self.settings.backup_enabled,
                "backup_configured": self.settings.backup_ready,
                "gemini_enabled": self.settings.feature_gemini,
                "gemini_configured": self.settings.gemini_ready,
                "mastercard_enabled": self.settings.feature_mastercard,
                "mastercard_configured": self.settings.mastercard_ready,
                "image_moderation_enabled": self.settings.image_moderation_enabled,
                "image_moderation_external_configured": self.settings.image_moderation_external_ready,
                "encryption_key_version": self.settings.encryption_key_version,
            },
            "modules": [
                {
                    "key": row.module_key,
                    "name": row.name_ar,
                    "version": row.version,
                    "enabled": row.is_enabled,
                    "critical": row.is_critical,
                    "health": row.health_status,
                    "error": row.last_error,
                }
                for row in modules
            ],
            "checked_at": now.isoformat(),
        }
        result["runtime"] = runtime
        result["redis"] = redis_check
        result["telegram"] = telegram_check
        session.add(SystemHealthSnapshot(
            status=overall, release_id=self.settings.release_id, runtime_mode=self.settings.runtime_mode,
            metrics_json=runtime, checks_json={"database": result["database"], "redis": redis_check, "telegram": telegram_check},
        ))
        await session.flush()
        return result
