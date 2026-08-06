from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

from aiogram.types import InlineKeyboardMarkup

_ALLOWED: Final[set[str | None]] = {None, "primary", "success", "danger"}


@dataclass(frozen=True, slots=True)
class ButtonStylePolicy:
    """Central, deterministic Telegram button-style policy.

    Telegram exposes semantic styles rather than arbitrary HEX colors for native
    keyboards.  Exact callback rules win over prefix rules, which win over the
    explicit style already attached by a legacy handler.  This lets the project
    migrate gradually without random or contradictory colors.
    """

    exact: dict[str, str | None]
    prefixes: tuple[tuple[str, str | None], ...]

    def resolve(self, callback_data: str | None, current: str | None) -> str | None:
        if not callback_data:
            return current if current in _ALLOWED else None
        if callback_data in self.exact:
            return self.exact[callback_data]
        for prefix, style in self.prefixes:
            if callback_data.startswith(prefix):
                return style
        return current if current in _ALLOWED else None


_DEFAULT_EXACT: Final[dict[str, str | None]] = {
    "back_to_main": "primary",
    "nav:back": None,
    "provider:terms:accept": "success",
    "provider:terms:reject": "danger",
    "terms:accept": "success",
    "favorites:list": "primary",
}

_DEFAULT_PREFIXES: Final[tuple[tuple[str, str | None], ...]] = (
    ("admin:delete", "danger"),
    ("provider:section_delete", "danger"),
    ("provider:offer_delete", "danger"),
    ("order:cancel", "danger"),
    ("receipt:reject", "danger"),
    ("payment:reject", "danger"),
    ("admin:approve", "success"),
    ("receipt:approve", "success"),
    ("payment:approve", "success"),
    ("provider:publish", "success"),
    ("buy:", "success"),
    ("report:", "primary"),
    ("provider:report", "primary"),
    ("nav:", None),
)


def _normalize_style(value: object) -> str | None:
    if value in (None, "", "default"):
        return None
    style = str(value).strip().lower()
    if style not in {"primary", "success", "danger"}:
        raise ValueError(f"Unsupported Telegram button style: {value!r}")
    return style


@lru_cache(maxsize=1)
def get_button_style_policy() -> ButtonStylePolicy:
    exact = dict(_DEFAULT_EXACT)
    prefixes = list(_DEFAULT_PREFIXES)
    raw = os.getenv("BUTTON_STYLE_OVERRIDES_JSON", "").strip()
    if raw:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("BUTTON_STYLE_OVERRIDES_JSON must be a JSON object")
        for key, value in payload.get("exact", {}).items():
            exact[str(key)] = _normalize_style(value)
        custom_prefixes = payload.get("prefixes", {})
        if isinstance(custom_prefixes, dict):
            # Custom rules are prepended, so the owner can override defaults.
            prefixes = [
                (str(key), _normalize_style(value))
                for key, value in custom_prefixes.items()
            ] + prefixes
    return ButtonStylePolicy(exact=exact, prefixes=tuple(prefixes))


def apply_button_style_policy(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    if markup is None or os.getenv("FEATURE_CENTRAL_BUTTON_STYLES", "true").lower() in {
        "0", "false", "off", "no"
    }:
        return markup
    policy = get_button_style_policy()
    for row in markup.inline_keyboard:
        for button in row:
            button.style = policy.resolve(button.callback_data, button.style)
    return markup


def clear_button_style_policy_cache() -> None:
    """Used by tests and future owner-panel live reload."""

    get_button_style_policy.cache_clear()
