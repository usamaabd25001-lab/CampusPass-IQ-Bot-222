"""Release compatibility helpers.

CampusPass release identifiers start with a semantic ``MAJOR.MINOR.PATCH``
version and may include a descriptive suffix, for example
``8.0.0-enterprise-scale-b``.  Verification must be capability/additive based:
newer patch/minor/major releases remain compatible with checks for older phases.
"""
from __future__ import annotations

import re
from typing import Final

_RELEASE_RE: Final = re.compile(r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$")


def release_tuple(value: str) -> tuple[int, int, int]:
    """Return the numeric semantic-version prefix or raise a clear error."""
    normalized = value.strip()
    match = _RELEASE_RE.fullmatch(normalized)
    if match is None:
        raise ValueError(
            "invalid release identifier; expected MAJOR.MINOR.PATCH with an "
            f"optional suffix, got {value!r}"
        )
    return tuple(int(match.group(name)) for name in ("major", "minor", "patch"))


def is_release_at_least(current: str, minimum: str) -> bool:
    """Whether ``current`` is numerically equal to or newer than ``minimum``."""
    return release_tuple(current) >= release_tuple(minimum)


def require_release_at_least(current: str, minimum: str, *, context: str) -> None:
    """Fail verification only for malformed or genuinely older releases."""
    try:
        compatible = is_release_at_least(current, minimum)
    except ValueError as exc:
        raise SystemExit(f"{context}: {exc}") from exc
    if not compatible:
        raise SystemExit(
            f"{context}: release {current!r} is older than required baseline {minimum!r}"
        )
