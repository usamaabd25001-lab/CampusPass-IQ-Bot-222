from __future__ import annotations

import json
import os
import tarfile
import tempfile
from pathlib import Path

import httpx

from common import parse_postgres_url, require_env, run, sha256_file
from google_drive_backup import DRIVE_API, TOKEN_URL, _access_token, _escape_query, _folder_id


def _find_file(
    client: httpx.Client, headers: dict[str, str], folder_id: str
) -> dict[str, str]:
    requested_id = os.environ.get("RESTORE_DRIVE_FILE_ID", "").strip()
    if requested_id:
        response = client.get(
            f"{DRIVE_API}/files/{requested_id}",
            headers=headers,
            params={"fields": "id,name,size,createdTime"},
        )
        response.raise_for_status()
        return dict(response.json())
    name = require_env("RESTORE_ASSET_NAME")
    response = client.get(
        f"{DRIVE_API}/files",
        headers=headers,
        params={
            "q": (
                f"'{_escape_query(folder_id)}' in parents and trashed=false and "
                f"name='{_escape_query(name)}'"
            ),
            "fields": "files(id,name,size,createdTime)",
            "pageSize": 10,
        },
    )
    response.raise_for_status()
    files = response.json().get("files", [])
    if not files:
        raise RuntimeError("Requested Google Drive backup was not found")
    return dict(files[0])


def main() -> None:
    mode = os.environ.get("RESTORE_MODE", "verify").strip().lower()
    if mode not in {"verify", "restore"}:
        raise ValueError("RESTORE_MODE must be verify or restore")
    encryption_key = require_env("BACKUP_ENCRYPTION_KEY")

    timeout = httpx.Timeout(connect=30, read=1800, write=1800, pool=30)
    with tempfile.TemporaryDirectory(prefix="campuspass-drive-restore-") as temporary:
        workdir = Path(temporary)
        with httpx.Client(timeout=timeout) as client:
            token = _access_token(client)
            headers = {"Authorization": f"Bearer {token}"}
            folder_id = _folder_id(client, headers)
            item = _find_file(client, headers, folder_id)
            encrypted_path = workdir / str(item["name"])
            with client.stream(
                "GET",
                f"{DRIVE_API}/files/{item['id']}",
                headers=headers,
                params={"alt": "media"},
            ) as response:
                response.raise_for_status()
                with encrypted_path.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)

        archive_path = workdir / "backup.tar.gz"
        extract_dir = workdir / "extracted"
        extract_dir.mkdir()
        run(
            [
                "gpg",
                "--batch",
                "--yes",
                "--pinentry-mode",
                "loopback",
                "--passphrase-fd",
                "0",
                "--decrypt",
                "--output",
                str(archive_path),
                str(encrypted_path),
            ],
            input_bytes=encryption_key.encode(),
        )
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(extract_dir, filter="data")
        dump_path = extract_dir / "database.dump"
        manifest_path = extract_dir / "manifest.json"
        if not dump_path.exists() or not manifest_path.exists():
            raise RuntimeError("Backup archive is incomplete")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if sha256_file(dump_path) != manifest.get("dump_sha256"):
            raise RuntimeError("Backup dump checksum mismatch")
        listing = run(["pg_restore", "--list", str(dump_path)])
        objects = len(
            [
                line
                for line in listing.stdout.decode(errors="replace").splitlines()
                if line and not line.startswith(";")
            ]
        )

        restored = False
        if mode == "restore":
            if os.environ.get("RESTORE_CONFIRMATION", "") != "RESTORE_TO_EMPTY_DATABASE":
                raise RuntimeError(
                    "Set RESTORE_CONFIRMATION=RESTORE_TO_EMPTY_DATABASE to restore"
                )
            target = parse_postgres_url(require_env("RESTORE_DATABASE_URL"))
            run(
                [
                    "pg_restore",
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    "--no-acl",
                    "--exit-on-error",
                    "--jobs=2",
                    "--dbname",
                    target.database,
                    str(dump_path),
                ],
                env=target.pg_environment(),
            )
            restored = True

    print(
        json.dumps(
            {
                "ok": True,
                "mode": mode,
                "asset": item.get("name"),
                "created_at": manifest.get("created_at"),
                "source_database": manifest.get("database_name"),
                "objects_in_dump": objects,
                "restored": restored,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
