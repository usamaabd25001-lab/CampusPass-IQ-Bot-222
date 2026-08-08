from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import SecretBox
from app.db.models import EvidenceAsset, Order, SecretRotationRun, StudentProfile


class KeyRotationService:
    """Gradually re-encrypt sensitive rows with the current primary key."""

    def __init__(self, settings: Settings, secrets: SecretBox) -> None:
        self.settings = settings
        self.secrets = secrets

    async def rotate_batch(self, session: AsyncSession) -> dict[str, int]:
        target = self.settings.encryption_key_version
        limit = self.settings.key_rotation_batch_size
        run = SecretRotationRun(from_version=max(1, target - 1), to_version=target)
        session.add(run)
        await session.flush()
        try:
            profiles = list(
                (
                    await session.scalars(
                        select(StudentProfile)
                        .where(
                            StudentProfile.private_data_encrypted.is_not(None),
                            StudentProfile.private_data_key_version < target,
                        )
                        .order_by(StudentProfile.id)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for row in profiles:
                row.private_data_encrypted = self.secrets.rotate(row.private_data_encrypted or "")
                row.private_data_key_version = target
            orders = list(
                (
                    await session.scalars(
                        select(Order)
                        .where(
                            Order.activation_data_encrypted.is_not(None),
                            Order.activation_data_key_version < target,
                        )
                        .order_by(Order.id)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for row in orders:
                row.activation_data_encrypted = self.secrets.rotate(
                    row.activation_data_encrypted or ""
                )
                row.activation_data_key_version = target
            evidence = list(
                (
                    await session.scalars(
                        select(EvidenceAsset)
                        .where(
                            EvidenceAsset.encrypted_telegram_file_id != "",
                            EvidenceAsset.encryption_key_version < target,
                        )
                        .order_by(EvidenceAsset.id)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for row in evidence:
                row.encrypted_telegram_file_id = self.secrets.rotate(
                    row.encrypted_telegram_file_id
                )
                row.encryption_key_version = target
            run.profiles_rotated = len(profiles)
            run.orders_rotated = len(orders)
            run.evidence_rotated = len(evidence)
            run.status = "succeeded"
            run.completed_at = datetime.now(UTC)
            await session.flush()
            return {
                "profiles": len(profiles),
                "orders": len(orders),
                "evidence": len(evidence),
            }
        except Exception as exc:
            run.status = "failed"
            run.last_error = str(exc)[:2000]
            run.completed_at = datetime.now(UTC)
            await session.flush()
            raise
