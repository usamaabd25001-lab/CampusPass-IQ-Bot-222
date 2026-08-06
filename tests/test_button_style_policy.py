from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.ui.button_styles import (
    apply_button_style_policy,
    clear_button_style_policy_cache,
)


def _markup(callback: str, style: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="x", callback_data=callback, style=style)]]
    )


def test_dangerous_actions_are_deterministic(monkeypatch):
    monkeypatch.delenv("BUTTON_STYLE_OVERRIDES_JSON", raising=False)
    monkeypatch.setenv("FEATURE_CENTRAL_BUTTON_STYLES", "true")
    clear_button_style_policy_cache()
    markup = apply_button_style_policy(_markup("provider:section_delete:17", "success"))
    assert markup.inline_keyboard[0][0].style == "danger"


def test_owner_exact_override_wins(monkeypatch):
    monkeypatch.setenv("FEATURE_CENTRAL_BUTTON_STYLES", "true")
    monkeypatch.setenv(
        "BUTTON_STYLE_OVERRIDES_JSON",
        '{"exact":{"favorites:list":"success"}}',
    )
    clear_button_style_policy_cache()
    markup = apply_button_style_policy(_markup("favorites:list", "danger"))
    assert markup.inline_keyboard[0][0].style == "success"


def test_feature_flag_can_disable_policy(monkeypatch):
    monkeypatch.setenv("FEATURE_CENTRAL_BUTTON_STYLES", "false")
    clear_button_style_policy_cache()
    markup = apply_button_style_policy(_markup("order:cancel:1", "primary"))
    assert markup.inline_keyboard[0][0].style == "primary"
