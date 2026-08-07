"""Telegram UI helpers and centralized native button-style policy.

This package intentionally preserves the public API that historically lived in
``app.bot.ui`` while allowing UI concerns to be split into focused modules.
"""
from app.bot.ui.button_styles import (
    apply_button_style_policy,
    clear_button_style_policy_cache,
    get_button_style_policy,
)
from app.bot.ui.runtime import (
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

__all__ = [
    "apply_button_style_policy",
    "callback_notice",
    "clear_button_style_policy_cache",
    "delete_safely",
    "edit_markup",
    "edit_or_send",
    "get_button_style_policy",
    "install_reply_keyboard_temporarily",
    "remove_reply_keyboard_temporarily",
    "send_inline_menu",
    "send_reply_menu",
    "transition_lock",
]
