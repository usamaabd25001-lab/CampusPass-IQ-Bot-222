from __future__ import annotations

import re

_VERSIONED_CALLBACK = re.compile(r"^v(?P<version>\d+)\|(?P<payload>.+)$", re.DOTALL)
CURRENT_CALLBACK_SCHEMA_VERSION = 1

# Keep this map append-only. Old inline keyboards may remain in Telegram chats
# for months after a release. Removing an alias would make an otherwise valid
# historical button appear broken.
LEGACY_CALLBACK_ALIASES: dict[str, str] = {
    "menu:home": "back_to_main",
    "nav:home": "back_to_main",
    "home": "back_to_main",
    "provider:dashboard": "provider:home",
    "admin:dashboard": "admin:home",
}


def versioned_callback(payload: str, *, version: int = CURRENT_CALLBACK_SCHEMA_VERSION) -> str:
    clean = (payload or "").strip()
    if not clean:
        raise ValueError("Callback payload cannot be empty")
    value = f"v{int(version)}|{clean}"
    if len(value.encode("utf-8")) > 64:
        raise ValueError("Versioned callback exceeds Telegram's 64-byte limit")
    return value


def normalize_callback(payload: str | None) -> tuple[str | None, int]:
    if payload is None:
        return None, CURRENT_CALLBACK_SCHEMA_VERSION
    raw = payload.strip()
    match = _VERSIONED_CALLBACK.match(raw)
    if match is not None:
        version = int(match.group("version"))
        if version > CURRENT_CALLBACK_SCHEMA_VERSION:
            # A newer button must not be interpreted using older semantics.
            return raw, version
        raw = match.group("payload")
    else:
        version = 0
    normalized = LEGACY_CALLBACK_ALIASES.get(raw, raw)
    return normalized, version
