from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_MULTI_SPACE_RE = re.compile(r"\s+")
_REPEATED_CHAR_RE = re.compile(r"(.)\1{4,}", re.UNICODE)
_URL_RE = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
_HTML_RE = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
_ARABIC_NAME_RE = re.compile(r"^[\u0621-\u063A\u0641-\u064A\u066E\u066F\u0671-\u06D3]+(?:[ -][\u0621-\u063A\u0641-\u064A\u066E\u066F\u0671-\u06D3]+){2,5}$")
_ARABIC_LABEL_RE = re.compile(r"^[\u0621-\u063A\u0641-\u064A\u066E\u066F\u0671-\u06D3]+(?:[ \-–—][\u0621-\u063A\u0641-\u064A\u066E\u066F\u0671-\u06D3]+)*$")
_ENGLISH_LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 &+._()\-–—']*$")
_TELEGRAM_ID_RE = re.compile(r"^[1-9]\d{5,14}$")
_TELEGRAM_USERNAME_RE = re.compile(r"^@?[A-Za-z][A-Za-z0-9_]{4,31}$")

# The list is intentionally tiny and high-confidence. It blocks obvious non-name
# placeholders without pretending to be a dictionary of Iraqi names.
_NON_PERSON_NAME_TOKENS = {
    "ماء",
    "بقرة",
    "حلويات",
    "مطعم",
    "شركة",
    "منصة",
    "متجر",
    "اختبار",
    "تجربة",
    "مجهول",
    "نيويوذ",
}

IRAQI_GOVERNORATES = frozenset(
    {
        "بغداد",
        "البصرة",
        "نينوى",
        "أربيل",
        "الأنبار",
        "كركوك",
        "السليمانية",
        "دهوك",
        "ديالى",
        "بابل",
        "كربلاء",
        "النجف",
        "واسط",
        "صلاح الدين",
        "القادسية",
        "الديوانية",
        "ذي قار",
        "ميسان",
        "المثنى",
        "حلبجة",
    }
)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    value: str


def normalize_digits(value: str) -> str:
    return (value or "").translate(_ARABIC_DIGITS)


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = _CONTROL_RE.sub("", text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text


def _letters_count(value: str) -> int:
    return sum(1 for ch in value if ch.isalpha())


def _reject_common_text_abuse(value: str, *, label: str) -> None:
    if _REPEATED_CHAR_RE.search(value):
        raise ValueError(f"{label}: يوجد تكرار غير طبيعي للحروف")
    if _HTML_RE.search(value):
        raise ValueError(f"{label}: أكواد HTML غير مسموحة")
    if _URL_RE.search(value):
        raise ValueError(f"{label}: الروابط غير مسموحة في هذا الحقل")


def validate_person_full_name(value: str) -> str:
    text = normalize_text(value)
    text = _DIACRITICS_RE.sub("", text)
    if not 8 <= len(text) <= 180:
        raise ValueError("الاسم الكامل يجب أن يكون بين 8 و180 حرفًا")
    _reject_common_text_abuse(text, label="الاسم")
    if not _ARABIC_NAME_RE.fullmatch(text):
        raise ValueError("اكتب الاسم الثلاثي بالعربية فقط، مثل: محمد علي حسن")
    words = [part for part in re.split(r"[ -]+", text) if part]
    if not 3 <= len(words) <= 6:
        raise ValueError("الاسم يجب أن يتكون من ثلاثة مقاطع على الأقل")
    if any(len(word) < 2 for word in words):
        raise ValueError("كل مقطع في الاسم يجب أن يكون واضحًا وغير مختصر")
    normalized_words = {word.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا") for word in words}
    if normalized_words & _NON_PERSON_NAME_TOKENS:
        raise ValueError("القيمة المدخلة لا تبدو اسم شخص")
    if len(set(words)) == 1:
        raise ValueError("الاسم لا يمكن أن يكون نفس الكلمة مكررة")
    return text


def normalize_iraqi_phone(value: str) -> str:
    raw = normalize_digits(value)
    raw = re.sub(r"[\s()\-]", "", raw)
    if raw.startswith("+964"):
        local = "0" + raw[4:]
    elif raw.startswith("964"):
        local = "0" + raw[3:]
    else:
        local = raw
    if not re.fullmatch(r"07[3-9]\d{8}", local):
        raise ValueError("رقم الهاتف يجب أن يكون رقم موبايل عراقي صحيحًا من 11 رقمًا ويبدأ بـ 07")
    if len(set(local[-8:])) <= 2:
        raise ValueError("رقم الهاتف يبدو غير صحيح")
    return "+964" + local[1:]


def validate_governorate(value: str) -> str:
    text = normalize_text(value)
    if text not in IRAQI_GOVERNORATES:
        raise ValueError("اختر المحافظة من القائمة المعتمدة")
    return text


def validate_required_human_text(
    value: str,
    *,
    label: str,
    min_length: int = 2,
    max_length: int = 180,
    min_letters: int = 2,
) -> str:
    text = normalize_text(value)
    if not min_length <= len(text) <= max_length:
        raise ValueError(f"{label}: الطول يجب أن يكون بين {min_length} و{max_length}")
    _reject_common_text_abuse(text, label=label)
    if _letters_count(text) < min_letters:
        raise ValueError(f"{label}: اكتب قيمة واضحة وليست أرقامًا أو رموزًا فقط")
    if len(set(ch for ch in text if ch.isalpha())) < 2:
        raise ValueError(f"{label}: النص غير واضح")
    return text


def validate_optional_human_text(
    value: str | None,
    *,
    label: str,
    max_length: int,
) -> str:
    text = normalize_text(value or "")
    if not text:
        return ""
    return validate_required_human_text(
        text,
        label=label,
        min_length=2,
        max_length=max_length,
        min_letters=2,
    )


def validate_arabic_platform_name(value: str) -> str:
    text = normalize_text(value)
    if not 2 <= len(text) <= 180:
        raise ValueError("اسم المنصة يجب أن يكون بين حرفين و180 حرفًا")
    _reject_common_text_abuse(text, label="اسم المنصة")
    if not _ARABIC_LABEL_RE.fullmatch(text):
        raise ValueError("اسم المنصة العربي يجب أن يحتوي أحرفًا عربية فقط بدون أرقام أو إنجليزي")
    if _letters_count(text) < 2:
        raise ValueError("اسم المنصة العربي غير واضح")
    return text


def validate_optional_arabic_platform_name(value: str | None) -> str:
    text = normalize_text(value or "")
    if not text:
        return ""
    return validate_arabic_platform_name(text)


def validate_optional_english_name(value: str | None) -> str:
    text = normalize_text(value or "")
    if not text:
        return ""
    if not 2 <= len(text) <= 180 or not _ENGLISH_LABEL_RE.fullmatch(text):
        raise ValueError("اسم المنصة الإنجليزي يجب أن يبدأ بحرف إنجليزي ولا يحتوي أحرفًا عربية")
    _reject_common_text_abuse(text, label="الاسم الإنجليزي")
    if not any(ch.isalpha() and ch.isascii() for ch in text):
        raise ValueError("اسم المنصة الإنجليزي غير واضح")
    return text


def validate_telegram_id(value: int | str) -> int:
    raw = normalize_digits(str(value)).strip()
    if not _TELEGRAM_ID_RE.fullmatch(raw):
        raise ValueError("Telegram ID غير صحيح")
    return int(raw)


def validate_percentage(value: int | str) -> int:
    try:
        number = int(normalize_digits(str(value)).strip())
    except ValueError as exc:
        raise ValueError("النسبة يجب أن تكون رقمًا صحيحًا") from exc
    if not 0 <= number <= 100:
        raise ValueError("النسبة يجب أن تكون بين 0 و100")
    return number


def validate_catalog_label(value: str, *, label: str) -> str:
    return validate_required_human_text(
        value,
        label=label,
        min_length=2,
        max_length=160,
        min_letters=2,
    )


def validate_offer_title(value: str) -> str:
    return validate_required_human_text(
        value,
        label="اسم العرض",
        min_length=3,
        max_length=220,
        min_letters=2,
    )


def validate_offer_description(value: str | None) -> str:
    return validate_optional_human_text(value, label="وصف العرض", max_length=4000)


def validate_terms(value: str | None) -> str:
    text = normalize_text(value or "")
    if not text:
        return ""
    if len(text) > 4000:
        raise ValueError("شروط العرض طويلة جدًا")
    if _HTML_RE.search(text):
        raise ValueError("HTML غير مسموح داخل الشروط")
    return text


def validate_optional_percentage(value: int | str | None, *, default: int = 0) -> int:
    if value is None or normalize_text(str(value)) == "":
        return int(default)
    return validate_percentage(value)


def parse_iqd_amount(
    value: int | str | None,
    *,
    optional: bool = False,
    maximum: int = 2_000_000_000,
) -> int:
    if value is None or normalize_text(str(value)) == "":
        if optional:
            return 0
        raise ValueError("المبلغ مطلوب")
    raw = normalize_digits(str(value))
    raw = raw.replace(",", "").replace("٬", "").replace(" ", "")
    raw = raw.replace("د.ع", "").replace("دينارعراقي", "").replace("دينار", "")
    if not re.fullmatch(r"\d+", raw):
        raise ValueError("اكتب المبلغ بالأرقام فقط")
    amount = int(raw)
    if amount < 0 or amount > maximum:
        raise ValueError(f"المبلغ يجب أن يكون بين 0 و{maximum:,} د.ع")
    if amount == 0 and not optional:
        raise ValueError("المبلغ يجب أن يكون أكبر من صفر")
    return amount


def suggested_iqd_amount(value: int | str | None) -> tuple[int, int | None]:
    amount = parse_iqd_amount(value, optional=False)
    return amount, (amount * 1000 if 1 <= amount < 250 else None)


def normalize_staff_identifiers(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        chunks = [str(item) for item in value]
    else:
        chunks = re.split(r"[,;\n]+", str(value))
    result: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        item = normalize_text(chunk)
        if not item:
            continue
        digits = normalize_digits(item)
        if _TELEGRAM_ID_RE.fullmatch(digits):
            canonical = digits
        elif _TELEGRAM_USERNAME_RE.fullmatch(item):
            canonical = "@" + item.lstrip("@").lower()
        else:
            raise ValueError(
                f"معرف الموظف «{item}» غير صحيح؛ استخدم Telegram ID أو @username"
            )
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    if len(result) > 25:
        raise ValueError("يمكن إضافة 25 موظفًا كحد أقصى أثناء إنشاء المنصة")
    return result
