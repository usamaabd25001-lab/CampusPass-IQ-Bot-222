from __future__ import annotations

import pytest

from app.services.webapp_validation import (
    normalize_iraqi_phone,
    validate_arabic_platform_name,
    validate_catalog_label,
    validate_person_full_name,
    validate_percentage,
    validate_telegram_id,
)


@pytest.mark.parametrize(
    "value",
    [
        "محمد علي حسن",
        "عبد الله محمد علي",
        "حسين عبد الكريم جاسم",
    ],
)
def test_valid_arabic_triple_names(value: str) -> None:
    assert validate_person_full_name(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "محمد علي",
        "محمد 123 علي",
        "محمد محمد محمد",
        "ماء بقرة حلويات",
        "نيويوذ علي حسن",
        "ااااا علي حسن",
    ],
)
def test_invalid_person_names_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        validate_person_full_name(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("07701234567", "+9647701234567"),
        ("+964 770 123 4567", "+9647701234567"),
        ("9647501234567", "+9647501234567"),
        ("٠٧٧٠١٢٣٤٥٦٧", "+9647701234567"),
    ],
)
def test_iraqi_phone_is_normalized(value: str, expected: str) -> None:
    assert normalize_iraqi_phone(value) == expected


@pytest.mark.parametrize("value", ["071234", "07700000000", "123456789", "abc"])
def test_invalid_iraqi_phone_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_iraqi_phone(value)


def test_platform_validation_contract() -> None:
    assert validate_arabic_platform_name("منصة الطالب") == "منصة الطالب"
    assert validate_telegram_id("8314084021") == 8314084021
    assert validate_percentage("5") == 5
    assert validate_catalog_label("ChatGPT", label="اسم الخدمة") == "ChatGPT"


def test_optional_platform_names_are_strict() -> None:
    from app.services.webapp_validation import (
        validate_optional_arabic_platform_name,
        validate_optional_english_name,
    )

    assert validate_optional_arabic_platform_name("") == ""
    assert validate_optional_arabic_platform_name("أكاديمية الطالب") == "أكاديمية الطالب"
    assert validate_optional_english_name("") == ""
    assert validate_optional_english_name("Student Academy") == "Student Academy"
    with pytest.raises(ValueError):
        validate_optional_arabic_platform_name("Campus 123")
    with pytest.raises(ValueError):
        validate_optional_arabic_platform_name("منصة 123")
    with pytest.raises(ValueError):
        validate_optional_english_name("منصة Student")


def test_iqd_parser_accepts_arabic_persian_and_english_digits() -> None:
    from app.services.webapp_validation import parse_iqd_amount, suggested_iqd_amount

    assert parse_iqd_amount("٥٠٠") == 500
    assert parse_iqd_amount("۵۰۰") == 500
    assert parse_iqd_amount("10,000") == 10000
    assert suggested_iqd_amount("١٠") == (10, 10000)
    assert suggested_iqd_amount("250") == (250, None)


def test_staff_identifiers_are_normalized_and_deduplicated() -> None:
    from app.services.webapp_validation import normalize_staff_identifiers

    assert normalize_staff_identifiers(["٨٣١٤٠٨٤٠٢١", "@Employee_User", "employee_user"]) == [
        "8314084021",
        "@employee_user",
    ]
    with pytest.raises(ValueError):
        normalize_staff_identifiers(["not valid username!"])
