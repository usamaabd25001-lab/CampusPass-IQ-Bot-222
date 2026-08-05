from app.core.utils import calculate_order_amounts, normalize_phone, validate_full_name


def test_phone():
    assert normalize_phone("+964 770 123 4567") == "07701234567"


def test_name():
    assert validate_full_name("علي حيدر عباس") == "علي حيدر عباس"


def test_valid_iraqi_names_are_not_rejected_by_substring_blocking():
    assert validate_full_name("اسامة وسام ميثم") == "اسامة وسام ميثم"
    assert validate_full_name("أسماء محمد علي") == "أسماء محمد علي"
    assert validate_full_name("عبد الله علي حسن") == "عبد الله علي حسن"


def test_name_diacritics_and_invisible_marks_are_cleaned():
    assert validate_full_name("عَلِي حَيْدَر عَبَّاس") == "علي حيدر عباس"
    assert validate_full_name("علي\u200f محمد حسن") == "علي محمد حسن"


def test_fake_or_malformed_names_are_rejected():
    assert validate_full_name("اسم وهمي طالب") is None
    assert validate_full_name("علي123 محمد حسن") is None
    assert validate_full_name("علي علي علي") is None


def test_amounts():
    result = calculate_order_amounts(10000, 500, 5)
    assert result["total_iqd"] == 10500
    assert result["provider_net_iqd"] == 9500
    assert result["owner_net_iqd"] == 1000


def test_many_realistic_arabic_names():
    valid_names = [
        "اسامة وسام ميثم",
        "أسامة وسام ميثم",
        "أسماء محمد علي",
        "عبد الله علي حسن",
        "عبد الرحمن كريم جاسم",
        "محمد باقر عبد الزهرة",
        "علي حيدر عباس",
        "زينب أحمد كاظم",
        "نور الهدى جبار حسن",
        "مصطفى ضياء عبد الكريم",
        "سجاد مؤيد خليل",
        "رؤى حسين طالب",
        "هدى قاسم عبد الأمير",
        "كرار ثامر مهدي",
        "آية عدنان صالح",
        "ياسر نجم عبد الواحد",
        "حسنين علي شاكر",
        "منتظر حامد جبار",
        "مريم لؤي عبد الستار",
        "سارة هيثم عبد الرزاق",
    ]
    for name in valid_names:
        assert validate_full_name(name) is not None, name


def test_more_invalid_names():
    invalid_names = [
        "علي محمد",
        "123 محمد حسن علي",
        "test user admin",
        "طالب مجهول وهمي",
        "ع ع ع",
        "هههههههه محمد علي",
        "محمد@ علي حسن",
        "محمد_علي حسن عباس",
        "علي علي علي",
        "",
    ]
    for name in invalid_names:
        assert validate_full_name(name) is None, name
