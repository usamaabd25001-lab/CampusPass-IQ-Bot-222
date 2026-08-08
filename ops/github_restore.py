from __future__ import annotations

import json
import os
import tarfile
import tempfile
from pathlib import Path

from common import parse_postgres_url, require_env, run, sha256_file

RELEASE_TAG = "database-backups"


def main() -> None:
    repository = require_env("GITHUB_REPOSITORY")
    token = require_env("GITHUB_TOKEN")
    asset_name = require_env("RESTORE_ASSET_NAME")
    encryption_key = require_env("BACKUP_ENCRYPTION_KEY")
    mode = os.environ.get("RESTORE_MODE", "verify").strip().lower()
    if mode not in {"verify", "restore"}:
        raise ValueError("RESTORE_MODE must be verify or restore")
    if not asset_name.endswith(".tar.gz.gpg"):
        raise ValueError("RESTORE_ASSET_NAME must point to a .tar.gz.gpg backup asset")

    with tempfile.TemporaryDirectory(prefix="campuspass-restore-") as temporary:
        workdir = Path(temporary)
        env = os.environ.copy()
        env["GH_TOKEN"] = token
        run(
            [
                "gh",
                "release",
                "download",
                RELEASE_TAG,
                "--repo",
                repository,
                "--pattern",
                asset_name,
                "--dir",
                str(workdir),
            ],
            env=env,
        )
        encrypted_path = workdir / asset_name
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
            confirmation = os.environ.get("RESTORE_CONFIRMATION", "")
            if confirmation != "RESTORE_TO_DEDICATED_DATABASE":
                raise RuntimeError("RESTORE_CONFIRMATION is not valid")
            connection = parse_postgres_url(require_env("RESTORE_DATABASE_URL"))
            pg_env = connection.pg_environment()
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
                    connection.database,
                    str(dump_path),
                ],
                env=pg_env,
            )
            restored = True
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": mode,
                    "asset": asset_name,
                    "objects_in_dump": objects,
                    "restored": restored,
                    "source_database": manifest.get("database_name", ""),
                    "created_at": manifest.get("created_at", ""),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
