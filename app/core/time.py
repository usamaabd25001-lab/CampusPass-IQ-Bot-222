from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def as_utc(value: datetime | None) -> datetime | None:
    """Return an aware UTC datetime.

    PostgreSQL preserves timezone-aware values. SQLite, which is used by the
    local test suite, can return the same columns as naive values. Normalizing
    at service boundaries keeps calculations deterministic in both engines.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_timezone(value: datetime | None, timezone_name: str = "Asia/Baghdad") -> datetime | None:
    """Normalize a database timestamp and render it in the configured local zone."""
    normalized = as_utc(value)
    if normalized is None:
        return None
    try:
        timezone = ZoneInfo(timezone_name)
    except Exception:
        timezone = UTC
    return normalized.astimezone(timezone)


def format_datetime(
    value: datetime | None,
    timezone_name: str = "Asia/Baghdad",
    fallback: str = "غير محدد",
) -> str:
    localized = as_timezone(value, timezone_name)
    return localized.strftime("%d/%m/%Y %H:%M") if localized else fallback


def format_date(
    value: datetime | None,
    timezone_name: str = "Asia/Baghdad",
    fallback: str = "غير محدد",
) -> str:
    localized = as_timezone(value, timezone_name)
    return localized.strftime("%d/%m/%Y") if localized else fallback


def format_iso_datetime(
    value: str | None,
    timezone_name: str = "Asia/Baghdad",
    fallback: str = "غير محدد",
) -> str:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return fallback
    return format_datetime(parsed, timezone_name, fallback)
