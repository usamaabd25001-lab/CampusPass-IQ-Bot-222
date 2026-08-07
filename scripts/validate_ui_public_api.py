from __future__ import annotations

"""Fail the build if the stable :mod:`app.bot.ui` compatibility API is broken.

The validator is intentionally safe to run both as ``python -m`` and as a
plain script path.  Docker/build runners differ in how they seed ``sys.path``;
bootstrapping the repository root here prevents a false ``No module named
'app'`` failure when the file is executed directly.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.bot.ui import (  # noqa: E402
    callback_notice,
    delete_safely,
    edit_markup,
    edit_or_send,
    install_reply_keyboard_temporarily,
    remove_reply_keyboard_temporarily,
    send_inline_menu,
    send_reply_menu,
    transition_lock,
)

_REQUIRED = {
    "callback_notice": callback_notice,
    "delete_safely": delete_safely,
    "edit_markup": edit_markup,
    "edit_or_send": edit_or_send,
    "install_reply_keyboard_temporarily": install_reply_keyboard_temporarily,
    "remove_reply_keyboard_temporarily": remove_reply_keyboard_temporarily,
    "send_inline_menu": send_inline_menu,
    "send_reply_menu": send_reply_menu,
    "transition_lock": transition_lock,
}


def main() -> None:
    for name, value in _REQUIRED.items():
        if not callable(value):
            raise SystemExit(f"UI API validation failed: {name} is not callable")
    print("UI public API validation passed")


if __name__ == "__main__":
    main()
