from __future__ import annotations

import hashlib
import os
import re
import subprocess  # nosec B404
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class PostgresConnection:
    host: str
    port: int
    user: str
    password: str
    database: str
    sslmode: str | None

    def pg_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "PGHOST": self.host,
                "PGPORT": str(self.port),
                "PGUSER": self.user,
                "PGPASSWORD": self.password,
                "PGDATABASE": self.database,
            }
        )
        if self.sslmode:
            env["PGSSLMODE"] = self.sslmode
        return env


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def parse_postgres_url(raw_url: str) -> PostgresConnection:
    normalized = raw_url.strip().replace("postgresql+asyncpg://", "postgresql://", 1)
    normalized = normalized.replace("postgres+asyncpg://", "postgresql://", 1)
    if normalized.startswith("postgres://"):
        normalized = normalized.replace("postgres://", "postgresql://", 1)
    parsed = urlparse(normalized)
    if parsed.scheme != "postgresql":
        raise ValueError("Only PostgreSQL URLs are supported")
    database = parsed.path.lstrip("/")
    if not parsed.hostname or not parsed.username or not database:
        raise ValueError("PostgreSQL URL must include host, username, and database")
    params = dict(
        item.split("=", 1) if "=" in item else (item, "")
        for item in parsed.query.split("&")
        if item
    )
    return PostgresConnection(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=unquote(parsed.username),
        password=unquote(parsed.password or ""),
        database=unquote(database),
        sslmode=params.get("sslmode"),
    )


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip("-._") or "backup"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # nosec B603
        command,
        env=env,
        input=input_bytes,
        check=True,
        capture_output=True,
    )
