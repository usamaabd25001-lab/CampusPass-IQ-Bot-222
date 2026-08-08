from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_VERSION_RE = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)")


@dataclass(frozen=True, slots=True, order=True)
class VersionTriplet:
    major: int
    minor: int
    patch: int


def parse_version(value: str) -> VersionTriplet:
    """Parse the numeric prefix of a release version.

    CampusPass release names intentionally contain readable suffixes, for example
    ``11.7.0-lts-turbo-update-safe``. Compatibility decisions use only the
    numeric semantic prefix and therefore remain stable if a label changes.
    """

    match = _VERSION_RE.match((value or "").strip())
    if match is None:
        raise ValueError(f"Invalid release version: {value!r}")
    return VersionTriplet(
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def version_at_least(current: str, minimum: str) -> bool:
    return parse_version(current) >= parse_version(minimum)


def rollout_bucket(*, subject: int | str, salt: str) -> int:
    """Return a stable bucket from 0 to 9,999 without exposing sequential IDs."""

    payload = f"{salt}\x1f{subject}".encode("utf-8")
    digest = hashlib.blake2s(payload, digest_size=8).digest()
    return int.from_bytes(digest, "big") % 10_000


def included_in_rollout(*, subject: int | str, salt: str, percent: float) -> bool:
    if percent <= 0:
        return False
    if percent >= 100:
        return True
    threshold = round(float(percent) * 100)
    return rollout_bucket(subject=subject, salt=salt) < threshold


def generation_cache_key(namespace: str, generation: int, key: str) -> str:
    safe_namespace = namespace.strip().lower().replace(" ", "-")
    if not safe_namespace or generation < 0:
        raise ValueError("Invalid cache generation")
    digest = hashlib.blake2s(key.encode("utf-8"), digest_size=12).hexdigest()
    return f"cp:{safe_namespace}:g{generation}:{digest}"
