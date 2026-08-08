from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import SecretBox
from app.core.utils import public_id
from app.db.models import BackupRun, BackupRunStatus


class BackupService:
    """Encrypted PostgreSQL logical backups uploaded to S3-compatible storage."""

    def __init__(self, settings: Settings, secrets: SecretBox) -> None:
        self.settings = settings
        self.secrets = secrets

    def _client(self):
        import boto3

        return boto3.client(
            "s3",
            endpoint_url=self.settings.backup_s3_endpoint or None,
            aws_access_key_id=self.settings.backup_s3_access_key,
            aws_secret_access_key=self.settings.backup_s3_secret_key,
            region_name=self.settings.backup_s3_region,
        )

    def _pg_connection(self) -> tuple[str, dict[str, str]]:
        url = make_url(self.settings.database_url)
        password = url.password or ""
        safe_url = url.set(drivername="postgresql", password=None).render_as_string(
            hide_password=False
        )
        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password
        return safe_url, env

    async def create(self, session: AsyncSession, *, actor_user_id: int | None = None) -> BackupRun:
        if not self.settings.backup_ready:
            raise RuntimeError("النسخ الاحتياطي مفعل لكنه ينتظر إعداد S3 الكامل")
        now = datetime.now(UTC)
        run = BackupRun(
            public_id=public_id("BKP"),
            status=BackupRunStatus.STARTED.value,
            backend="s3",
            release_id=self.settings.release_id,
            migration_version="",
            started_at=now,
            retention_until=now + timedelta(days=self.settings.backup_retention_days),
            created_by_user_id=actor_user_id,
        )
        session.add(run)
        await session.flush()

        dump_path: Path | None = None
        try:
            fd, raw_name = tempfile.mkstemp(prefix="campuspass-", suffix=".dump")
            os.close(fd)
            dump_path = Path(raw_name)
            safe_database_url, process_env = self._pg_connection()
            process = await asyncio.create_subprocess_exec(
                self.settings.backup_pg_dump_path,
                "--dbname",
                safe_database_url,
                "--format=custom",
                "--compress=9",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(dump_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env,
            )
            _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=900)
            if process.returncode != 0:
                raise RuntimeError(f"pg_dump failed: {stderr.decode(errors='replace')[:500]}")
            raw = dump_path.read_bytes()
            if not raw:
                raise RuntimeError("pg_dump produced an empty backup")
            if len(raw) > self.settings.backup_max_bytes:
                raise RuntimeError("backup exceeds BACKUP_MAX_BYTES")
            digest = hashlib.sha256(raw).hexdigest()
            encrypted = self.secrets.encrypt_bytes(raw)
            key = (
                f"{self.settings.backup_s3_prefix}/"
                f"{now:%Y/%m/%d}/{run.public_id}-{self.settings.release_id}.dump.fernet"
            )
            client = self._client()
            await asyncio.to_thread(
                client.put_object,
                Bucket=self.settings.backup_s3_bucket,
                Key=key,
                Body=encrypted,
                ContentType="application/octet-stream",
                Metadata={
                    "sha256": digest,
                    "release-id": self.settings.release_id,
                    "key-version": str(self.settings.encryption_key_version),
                },
            )
            run.status = BackupRunStatus.UPLOADED.value
            run.storage_key = key
            run.content_sha256 = digest
            run.size_bytes = len(raw)
            run.completed_at = datetime.now(UTC)
            await session.flush()

            result = await asyncio.to_thread(
                client.get_object,
                Bucket=self.settings.backup_s3_bucket,
                Key=key,
            )
            stored_encrypted = await asyncio.to_thread(result["Body"].read)
            verified_raw = self.secrets.decrypt_bytes(stored_encrypted)
            if hashlib.sha256(verified_raw).hexdigest() != digest:
                raise RuntimeError("backup verification hash mismatch")
            run.status = BackupRunStatus.VERIFIED.value
            run.verified_at = datetime.now(UTC)
            await session.flush()
            return run
        except Exception as exc:
            run.status = BackupRunStatus.FAILED.value
            run.last_error = str(exc)[:2000]
            run.completed_at = datetime.now(UTC)
            await session.flush()
            return run
        finally:
            if dump_path is not None:
                dump_path.unlink(missing_ok=True)

    async def purge_expired(self, session: AsyncSession, runs: list[BackupRun]) -> int:
        if not self.settings.backup_ready:
            return 0
        client = self._client()
        removed = 0
        for run in runs:
            if not run.storage_key:
                continue
            try:
                await asyncio.to_thread(
                    client.delete_object,
                    Bucket=self.settings.backup_s3_bucket,
                    Key=run.storage_key,
                )
                run.status = BackupRunStatus.DELETED.value
                run.storage_key = ""
                removed += 1
            except Exception as exc:
                run.last_error = str(exc)[:2000]
        await session.flush()
        return removed
