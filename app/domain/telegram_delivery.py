from __future__ import annotations

import hashlib
import json


def canonical_payload_digest(payload: dict) -> str:
    """Stable SHA-256 for Telegram JSON regardless of object key order."""
    raw = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def retry_delay_seconds(attempts: int, *, cap_seconds: int = 300) -> int:
    """Bounded exponential retry delay for durable update processing."""
    if attempts < 1:
        return 1
    return min(int(cap_seconds), 2 ** min(int(attempts), 8))
