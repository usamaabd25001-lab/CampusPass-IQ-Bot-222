from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# libpq-only parameters are removed from asyncpg URLs. SSL is configured with
# explicit connect_args in app.core.database so external providers behave the
# same whether their copied URL uses sslmode=require or channel_binding=require.
_LIBPQ_ONLY_QUERY_KEYS = {
    "sslmode",
    "sslrootcert",
    "sslcert",
    "sslkey",
    "channel_binding",
    "gssencmode",
    "target_session_attrs",
}


def normalize_async_database_url(raw_url: str) -> str:
    value = raw_url.strip()
    if value.startswith("postgres://"):
        value = value.replace("postgres://", "postgresql+asyncpg://", 1)
    elif value.startswith("postgresql://"):
        value = value.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif value.startswith("postgres+asyncpg://"):
        value = value.replace("postgres+asyncpg://", "postgresql+asyncpg://", 1)

    if not value.startswith("postgresql+asyncpg://"):
        return value

    parts = urlsplit(value)
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _LIBPQ_ONLY_QUERY_KEYS
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def database_hostname(database_url: str) -> str:
    try:
        return (urlsplit(database_url).hostname or "").lower()
    except ValueError:
        return ""


def safe_database_label(database_url: str) -> str:
    """Return host/database only; never include username or password."""
    try:
        parts = urlsplit(database_url)
    except ValueError:
        return "invalid-database-url"
    database = parts.path.lstrip("/") or "unknown"
    host = parts.hostname or "unknown"
    port = f":{parts.port}" if parts.port else ""
    return f"{host}{port}/{database}"
