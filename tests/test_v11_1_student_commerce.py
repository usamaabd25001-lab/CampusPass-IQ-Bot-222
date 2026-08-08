from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest

from app.core.telegram_webapp import TelegramWebAppAuthError, verify_telegram_init_data
from app.domain.student_commerce import (
    calculate_invoice,
    format_offer_button,
    net_wallet_fee_deduction,
    profile_completion,
    seconds_until_open,
)


def _signed_init_data(*, bot_token: str, auth_date: int, user_id: int = 77112233) -> str:
    values = {
        "auth_date": str(auth_date),
        "query_id": "AAEAA-test-query",
        "user": json.dumps(
            {
                "id": user_id,
                "first_name": "Ali",
                "last_name": "Hassan",
                "username": "ali_student",
                "language_code": "ar",
            },
            separators=(",", ":"),
        ),
    }
    check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_profile_completion_requires_all_student_fields() -> None:
    incomplete = profile_completion(
        {
            "full_name": "علي محمد حسن",
            "phone": "07701234567",
            "governorate": "بغداد",
            "university": "جامعة بغداد",
            "college": "الطب",
            "department": "يستكمل لاحقاً",
            "stage": "الثانية",
        }
    )
    assert not incomplete.complete
    assert incomplete.missing_fields == ("department",)

    complete = profile_completion(
        {
            "full_name": "علي محمد حسن",
            "phone": "07701234567",
            "governorate": "بغداد",
            "university": "جامعة بغداد",
            "college": "الطب",
            "department": "الطب العام",
            "stage": "الثانية",
        }
    )
    assert complete.complete
    assert complete.missing_fields == ()


def test_invoice_wallet_covers_only_the_complete_bot_fee() -> None:
    covered = calculate_invoice(
        service_price_iqd=10_000,
        bot_fee_iqd=500,
        wallet_balance_iqd=700,
        discount_iqd=1_000,
    )
    assert covered.wallet_fee_deduction_iqd == 500
    assert covered.wallet_balance_after_iqd == 200
    assert covered.cash_due_iqd == 9_000

    preserved = calculate_invoice(
        service_price_iqd=10_000,
        bot_fee_iqd=500,
        wallet_balance_iqd=499,
    )
    assert preserved.wallet_fee_deduction_iqd == 0
    assert preserved.wallet_balance_after_iqd == 499
    assert preserved.cash_due_iqd == 10_500


def test_net_wallet_fee_ignores_money_already_refunded() -> None:
    assert net_wallet_fee_deduction(
        {
            "wallet_fee_deduction_iqd": 500,
            "wallet_fee_refunded_iqd": 500,
        },
        current_bot_fee_iqd=0,
    ) == 0
    assert net_wallet_fee_deduction(
        {
            "wallet_fee_deduction_iqd": 500,
            "wallet_fee_refunded_iqd": 200,
        },
        current_bot_fee_iqd=500,
    ) == 300


def test_offer_button_is_compact_and_uses_integer_iqd() -> None:
    assert (
        format_offer_button(
            service_name="ChatGPT Plus",
            duration_label="شهر واحد",
            price_iqd=10_000,
        )
        == "ChatGPT Plus - شهر واحد - 10,000 د.ع"
    )


def test_working_hours_helper_uses_baghdad_local_time() -> None:
    now = datetime(2026, 8, 4, 10, 30, tzinfo=ZoneInfo("Asia/Baghdad"))
    is_open, wait = seconds_until_open(
        now=now,
        weekday=now.weekday(),
        opens_minute=10 * 60,
        closes_minute=23 * 60,
    )
    assert is_open
    assert wait == 0


def test_telegram_webapp_signature_binds_profile_to_telegram_user() -> None:
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
    payload = _signed_init_data(bot_token=token, auth_date=1_800_000_000, user_id=445566)
    verified = verify_telegram_init_data(
        payload,
        bot_token=token,
        now=1_800_000_100,
        max_age_seconds=900,
    )
    assert verified.user.id == 445566
    assert verified.user.full_name == "Ali Hassan"


def test_telegram_webapp_rejects_tampering_and_expiry() -> None:
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
    payload = _signed_init_data(bot_token=token, auth_date=1_800_000_000)
    with pytest.raises(TelegramWebAppAuthError):
        verify_telegram_init_data(
            payload.replace("ali_student", "fake_admin"),
            bot_token=token,
            now=1_800_000_100,
        )
    with pytest.raises(TelegramWebAppAuthError):
        verify_telegram_init_data(
            payload,
            bot_token=token,
            now=1_800_002_000,
            max_age_seconds=900,
        )
