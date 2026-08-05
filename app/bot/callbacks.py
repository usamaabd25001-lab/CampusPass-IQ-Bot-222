from __future__ import annotations

MAX_CALLBACK_BYTES = 64


class CallbackPayloadError(ValueError):
    pass


def callback_payload(*parts: object) -> str:
    """Build a compact Telegram callback payload and enforce the 64-byte protocol limit."""

    value = ":".join(str(part) for part in parts)
    size = len(value.encode("utf-8"))
    if size > MAX_CALLBACK_BYTES:
        raise CallbackPayloadError(
            f"callback_data is {size} bytes; use numeric IDs or a shorter action code"
        )
    return value


def callback_size(value: str) -> int:
    return len(value.encode("utf-8"))
