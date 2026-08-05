from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.core.security import SecretBox


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Restore an encrypted CampusPass pg_dump backup")
    p.add_argument("--storage-key", required=True)
    p.add_argument("--target-database-url", required=True)
    p.add_argument("--expected-sha256", default="")
    p.add_argument("--confirm", default="", help="Must equal RESTORE-CAMPUSPASS")
    return p


async def main() -> int:
    args = parser().parse_args()
    if args.confirm != "RESTORE-CAMPUSPASS":
        raise SystemExit("Refusing restore without --confirm RESTORE-CAMPUSPASS")
    settings = get_settings()
    if not settings.backup_ready:
        raise SystemExit("BACKUP_ENABLED must be true and S3 variables must be configured")
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=settings.backup_s3_endpoint or None,
        aws_access_key_id=settings.backup_s3_access_key,
        aws_secret_access_key=settings.backup_s3_secret_key,
        region_name=settings.backup_s3_region,
    )
    result = await asyncio.to_thread(
        client.get_object,
        Bucket=settings.backup_s3_bucket,
        Key=args.storage_key,
    )
    encrypted = await asyncio.to_thread(result["Body"].read)
    raw = SecretBox(settings).decrypt_bytes(encrypted)
    digest = hashlib.sha256(raw).hexdigest()
    if args.expected_sha256 and digest.lower() != args.expected_sha256.lower():
        raise SystemExit("Backup SHA-256 mismatch; restore aborted")

    url = make_url(args.target_database_url)
    password = url.password or ""
    safe_url = url.set(drivername="postgresql", password=None).render_as_string(
        hide_password=False
    )
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    fd, name = tempfile.mkstemp(prefix="campuspass-restore-", suffix=".dump")
    os.close(fd)
    path = Path(name)
    try:
        path.write_bytes(raw)
        process = await asyncio.create_subprocess_exec(
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--dbname",
            safe_url,
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise SystemExit(f"pg_restore failed: {stderr.decode(errors='replace')[:1000]}")
        print(stdout.decode(errors="replace"))
        print(f"Restore completed. sha256={digest}")
        return 0
    finally:
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
