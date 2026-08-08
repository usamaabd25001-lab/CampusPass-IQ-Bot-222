from app.utils import normalize_phone, validate_full_name


def test_phone_formats() -> None:
    assert normalize_phone("07701234567") == "07701234567"
    assert normalize_phone("+964 770 123 4567") == "07701234567"
    assert normalize_phone("123") is None


def test_name_validation() -> None:
    assert validate_full_name("علي محمد حسن") == "علي محمد حسن"
    assert validate_full_name("علي") is None
    assert validate_full_name("علي 123 حسن") is None
