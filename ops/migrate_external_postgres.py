from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from common import parse_postgres_url, require_env, run


def main() -> None:
    source_url = require_env("SOURCE_DATABASE_URL")
    target_url = require_env("TARGET_DATABASE_URL")
    if os.environ.get("MIGRATION_CONFIRM", "") != "MIGRATE_CAMPUSPASS_DATABASE":
        raise RuntimeError(
            "Set MIGRATION_CONFIRM=MIGRATE_CAMPUSPASS_DATABASE before migration"
        )

    source = parse_postgres_url(source_url)
    target = parse_postgres_url(target_url)
    if (
        source.host.lower(),
        source.port,
        source.database.lower(),
        source.user.lower(),
    ) == (
        target.host.lower(),
        target.port,
        target.database.lower(),
        target.user.lower(),
    ):
        raise RuntimeError("Source and target databases appear to be the same")

    with tempfile.TemporaryDirectory(prefix="campuspass-migrate-") as temporary:
        dump_path = Path(temporary) / "campuspass.dump"
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
            env=source.pg_environment(),
        )
        listing = run(["pg_restore", "--list", str(dump_path)])
        object_count = len(
            [
                line
                for line in listing.stdout.decode(errors="replace").splitlines()
                if line and not line.startswith(";")
            ]
        )
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
        verify = run(
            [
                "psql",
                "--no-psqlrc",
                "--tuples-only",
                "--no-align",
                "--command",
                (
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_name LIKE 'cp_%';"
                ),
            ],
            env=target.pg_environment(),
        )
        table_count = int(verify.stdout.decode().strip() or "0")
        if table_count < 10:
            raise RuntimeError(
                f"Target verification failed: only {table_count} CampusPass tables found"
            )

    print(
        json.dumps(
            {
                "ok": True,
                "source": f"{source.host}:{source.port}/{source.database}",
                "target": f"{target.host}:{target.port}/{target.database}",
                "dump_objects": object_count,
                "target_campuspass_tables": table_count,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
