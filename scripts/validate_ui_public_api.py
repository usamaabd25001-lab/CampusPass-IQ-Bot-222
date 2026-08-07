from __future__ import annotations

"""Validate the stable :mod:`app.bot.ui` compatibility API.

The project deliberately keeps ``app.bot.ui`` as a *module*, not a package.
Keyboard builders depend on ``app.bot.button_styles`` and the UI runtime may
then depend on keyboard builders.  This one-way dependency prevents the
historical ``inline -> ui package -> runtime -> inline`` circular import.

The validator is safe both as ``python -m scripts.validate_ui_public_api`` and
as a direct script path.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.bot.ui import (  # noqa: E402
    apply_button_style_policy,
    callback_notice,
    clear_button_style_policy_cache,
    delete_safely,
    edit_markup,
    edit_or_send,
    get_button_style_policy,
    install_reply_keyboard_temporarily,
    remove_reply_keyboard_temporarily,
    send_inline_menu,
    send_reply_menu,
    transition_lock,
)

_REQUIRED_CALLABLES = {
    "apply_button_style_policy": apply_button_style_policy,
    "callback_notice": callback_notice,
    "clear_button_style_policy_cache": clear_button_style_policy_cache,
    "delete_safely": delete_safely,
    "edit_markup": edit_markup,
    "edit_or_send": edit_or_send,
    "get_button_style_policy": get_button_style_policy,
    "install_reply_keyboard_temporarily": install_reply_keyboard_temporarily,
    "remove_reply_keyboard_temporarily": remove_reply_keyboard_temporarily,
    "send_inline_menu": send_inline_menu,
    "send_reply_menu": send_reply_menu,
    "transition_lock": transition_lock,
}


def main() -> None:
    for name, value in _REQUIRED_CALLABLES.items():
        if not callable(value):
            raise SystemExit(f"UI API validation failed: {name} is not callable")
    print("UI public API validation passed")


if __name__ == "__main__":
    main()
