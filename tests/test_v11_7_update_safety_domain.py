from __future__ import annotations

import pytest

from app.domain.callback_compat import normalize_callback, versioned_callback
from app.domain.update_safety import (
    generation_cache_key,
    included_in_rollout,
    parse_version,
    rollout_bucket,
    version_at_least,
)


def test_suffix_versions_compare_by_numeric_prefix() -> None:
    assert parse_version("11.7.0-lts-turbo").minor == 7
    assert version_at_least("11.7.0-lts", "11.6.0-render")
    assert not version_at_least("11.5.9", "11.6.0")


def test_rollout_is_deterministic_and_bounded() -> None:
    first = rollout_bucket(subject=12345, salt="feature-a")
    assert first == rollout_bucket(subject=12345, salt="feature-a")
    assert 0 <= first < 10_000
    assert not included_in_rollout(subject=12345, salt="x", percent=0)
    assert included_in_rollout(subject=12345, salt="x", percent=100)


def test_generation_key_changes_without_exposing_raw_key() -> None:
    one = generation_cache_key("menus", 1, "student:123")
    two = generation_cache_key("menus", 2, "student:123")
    assert one != two
    assert "student:123" not in one


def test_legacy_callbacks_remain_compatible() -> None:
    assert normalize_callback("menu:home") == ("back_to_main", 0)
    assert normalize_callback("v1|provider:dashboard") == ("provider:home", 1)


def test_future_callback_is_not_silently_reinterpreted() -> None:
    assert normalize_callback("v2|menu:home") == ("v2|menu:home", 2)


def test_callback_payload_limit_is_enforced() -> None:
    assert versioned_callback("offer:42") == "v1|offer:42"
    with pytest.raises(ValueError):
        versioned_callback("x" * 65)
