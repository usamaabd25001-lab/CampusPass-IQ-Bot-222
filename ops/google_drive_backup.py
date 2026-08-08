from __future__ import annotations

import json
import os
import tarfile
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator

import httpx

from common import parse_postgres_url, require_env, run, safe_filename, sha256_file

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"


def _admin_ids() -> list[int]:
    raw = os.environ.get("ADMIN_IDS", "")
    values: list[int] = []
    for item in raw.replace(";", ",").replace(" ", ",").replace("[", "").replace("]", "").split(","):
        item = item.strip()
        if item.isdigit():
            values.append(int(item))
    return sorted(set(values))


def _send_admin_alert(text: str) -> None:
    """Best-effort Telegram alert for Google Drive authentication failures."""
    token = os.environ.get("BOT_TOKEN", "").strip()
    targets = _admin_ids()
    if not token or not targets:
        return
    safe_text = text[:3500]
    with httpx.Client(timeout=httpx.Timeout(8.0)) as alert_client:
        for chat_id in targets:
            try:
                response = alert_client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": safe_text,
                        "disable_web_page_preview": True,
                    },
                )
                response.raise_for_status()
            except Exception:
                # Alerting must never hide the original backup failure.
                pass


def _access_token(client: httpx.Client) -> str:
    try:
        response = client.post(
            TOKEN_URL,
            data={
                "client_id": require_env("GOOGLE_DRIVE_CLIENT_ID"),
                "client_secret": require_env("GOOGLE_DRIVE_CLIENT_SECRET"),
                "refresh_token": require_env("GOOGLE_DRIVE_REFRESH_TOKEN"),
                "grant_type": "refresh_token",
            },
        )
        if response.status_code >= 400:
            payload = response.json() if "json" in response.headers.get("content-type", "") else {}
            error_code = str(payload.get("error") or response.status_code)
            description = str(payload.get("error_description") or "OAuth refresh failed")
            _send_admin_alert(
                "🚨 CampusPass Google Drive token alert\n"
                f"OAuth error: {error_code}\n"
                f"Details: {description[:500]}\n"
                "Run scripts/google_drive_oauth_setup.py and replace GOOGLE_DRIVE_REFRESH_TOKEN."
            )
            response.raise_for_status()
        token = response.json().get("access_token", "")
        if not token:
            _send_admin_alert(
                "🚨 CampusPass Google Drive token alert\n"
                "Google returned no access token. Re-authorize the backup integration."
            )
            raise RuntimeError("Google OAuth token response did not include access_token")
        return str(token)
    except Exception as exc:
        if not isinstance(exc, httpx.HTTPStatusError):
            _send_admin_alert(
                "🚨 CampusPass Google Drive authentication failed\n"
                f"Error: {type(exc).__name__}\n"
                "Check or renew GOOGLE_DRIVE_REFRESH_TOKEN."
            )
        raise


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _folder_id(client: httpx.Client, headers: dict[str, str]) -> str:
    explicit = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    if explicit:
        return explicit
    folder_name = os.environ.get(
        "GOOGLE_DRIVE_FOLDER_NAME", "CampusPass IQ Backups"
    ).strip() or "CampusPass IQ Backups"
    query = (
        "mimeType='application/vnd.google-apps.folder' and trashed=false and "
        f"name='{_escape_query(folder_name)}'"
    )
    response = client.get(
        f"{DRIVE_API}/files",
        headers=headers,
        params={
            "q": query,
            "fields": "files(id,name,createdTime)",
            "pageSize": 10,
            "spaces": "drive",
        },
    )
    response.raise_for_status()
    files = response.json().get("files", [])
    if files:
        return str(files[0]["id"])
    response = client.post(
        f"{DRIVE_API}/files",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "appProperties": {"campuspass": "backup-folder"},
        },
        params={"fields": "id"},
    )
    response.raise_for_status()
    return str(response.json()["id"])


def _file_chunks(path: Path, chunk_size: int = 8 * 1024 * 1024) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            yield chunk


def _upload(
    client: httpx.Client,
    headers: dict[str, str],
    path: Path,
    folder_id: str,
    content_type: str,
) -> dict[str, object]:
    size = path.stat().st_size
    start = client.post(
        f"{DRIVE_UPLOAD_API}/files",
        headers={
            **headers,
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": content_type,
            "X-Upload-Content-Length": str(size),
        },
        params={
            "uploadType": "resumable",
            "fields": "id,name,size,createdTime,webViewLink",
        },
        json={
            "name": path.name,
            "parents": [folder_id],
            "appProperties": {"campuspassBackup": "true"},
        },
    )
    start.raise_for_status()
    location = start.headers.get("Location")
    if not location:
        raise RuntimeError("Google Drive did not return a resumable upload URL")
    upload = client.put(
        location,
        headers={"Content-Type": content_type, "Content-Length": str(size)},
        content=_file_chunks(path),
    )
    upload.raise_for_status()
    return dict(upload.json())


def _delete_expired(
    client: httpx.Client,
    headers: dict[str, str],
    folder_id: str,
    retention_days: int,
) -> int:
    response = client.get(
        f"{DRIVE_API}/files",
        headers=headers,
        params={
            "q": f"'{_escape_query(folder_id)}' in parents and trashed=false",
            "fields": "files(id,name,createdTime,size)",
            "pageSize": 1000,
            "orderBy": "createdTime desc",
        },
    )
    response.raise_for_status()
    files = [
        item
        for item in response.json().get("files", [])
        if str(item.get("name", "")).startswith("campuspass-")
    ]
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    deleted = 0
    # Keep at least the three newest backup sets (encrypted file + checksum).
    for index, item in enumerate(files):
        if index < 6:
            continue
        created = datetime.fromisoformat(str(item["createdTime"]).replace("Z", "+00:00"))
        if created >= cutoff:
            continue
        response = client.delete(f"{DRIVE_API}/files/{item['id']}", headers=headers)
        response.raise_for_status()
        deleted += 1
    return deleted


def main() -> None:
    database_url = require_env("BACKUP_DATABASE_URL")
    encryption_key = require_env("BACKUP_ENCRYPTION_KEY")
    retention_days = max(3, min(365, int(os.environ.get("BACKUP_RETENTION_DAYS", "30"))))
    connection = parse_postgres_url(database_url)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    prefix = safe_filename(f"campuspass-{connection.database}-{timestamp}")

    timeout = httpx.Timeout(connect=30, read=1800, write=1800, pool=30)
    with tempfile.TemporaryDirectory(prefix="campuspass-drive-backup-") as temporary:
        workdir = Path(temporary)
        dump_path = workdir / "database.dump"
        manifest_path = workdir / "manifest.json"
        archive_path = workdir / f"{prefix}.tar.gz"
        encrypted_path = workdir / f"{prefix}.tar.gz.gpg"
        checksum_path = workdir / f"{prefix}.sha256"

        run(
            [
                "pg_dump",
                "--format=custom",
                "--compress=9",
                "--no-owner",
                "--no-acl",
                "--file",
                str(dump_path),
            ],
            env=connection.pg_environment(),
        )
        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "database_host": connection.host,
            "database_port": connection.port,
            "database_name": connection.database,
            "dump_sha256": sha256_file(dump_path),
            "format": "pg_dump custom",
            "encrypted": True,
            "version": "10.0.0-render-ready",
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(dump_path, arcname="database.dump")
            archive.add(manifest_path, arcname="manifest.json")
        run(
            [
                "gpg",
                "--batch",
                "--yes",
                "--pinentry-mode",
                "loopback",
                "--passphrase-fd",
                "0",
                "--symmetric",
                "--cipher-algo",
                "AES256",
                "--output",
                str(encrypted_path),
                str(archive_path),
            ],
            input_bytes=encryption_key.encode(),
        )
        checksum = sha256_file(encrypted_path)
        checksum_path.write_text(f"{checksum}  {encrypted_path.name}\n", encoding="utf-8")

        with httpx.Client(timeout=timeout) as client:
            token = _access_token(client)
            headers = {"Authorization": f"Bearer {token}"}
            folder_id = _folder_id(client, headers)
            encrypted_result = _upload(
                client, headers, encrypted_path, folder_id, "application/octet-stream"
            )
            checksum_result = _upload(
                client, headers, checksum_path, folder_id, "text/plain"
            )
            deleted = _delete_expired(client, headers, folder_id, retention_days)

    print(
        json.dumps(
            {
                "ok": True,
                "asset": encrypted_result,
                "checksum_asset": checksum_result,
                "checksum": checksum,
                "retention_days": retention_days,
                "deleted_old_files": deleted,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
