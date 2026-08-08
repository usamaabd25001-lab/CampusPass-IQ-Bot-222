from __future__ import annotations

import html
import re
import secrets
import string
from datetime import UTC, datetime

ARABIC_NAME_RE = re.compile(r"^[\u0621-\u064A\u066E-\u06D3 ]+$")
ARABIC_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
INVISIBLE_CHARS_RE = re.compile(r"[\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF]")
IRAQI_PHONE_RE = re.compile(r"^07(?:5|7|8|9)\d{8}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

BLOCKED_NAME_WORDS = {
    "مجهول",
    "اسم",
    "وهمي",
    "لااعرف",
    "لا أعرف",
    "test",
    "user",
    "admin",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def safe(value: object | None, fallback: str = "غير محدد") -> str:
    if value is None or str(value).strip() == "":
        return fallback
    return html.escape(str(value))


def normalize_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if digits.startswith("00964"):
        digits = digits[5:]
    elif digits.startswith("964"):
        digits = digits[3:]
    if digits.startswith("7"):
        digits = "0" + digits
    return digits if IRAQI_PHONE_RE.fullmatch(digits) else None


def _clean_arabic_name(value: str) -> str:
    """Normalize user-entered Arabic names without changing real letters.

    Telegram clients may insert invisible direction marks, Arabic tatweel, or
    diacritics. They are presentation characters and should not cause a real
    Iraqi name to be rejected.
    """
    value = INVISIBLE_CHARS_RE.sub("", value)
    value = value.replace("ـ", "")
    value = ARABIC_DIACRITICS_RE.sub("", value)
    return re.sub(r"\s+", " ", value.strip())


def _canonical_for_blocklist(value: str) -> str:
    """Create a comparison form used only for blocked placeholder words."""
    return value.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا"}))


def validate_full_name(value: str) -> str | None:
    name = _clean_arabic_name(value)
    if len(name) < 6 or len(name) > 180 or not ARABIC_NAME_RE.fullmatch(name):
        return None

    parts = [part for part in name.split(" ") if part]
    if len(parts) < 3 or len(parts) > 8 or any(len(part) < 2 for part in parts):
        return None

    canonical_name = _canonical_for_blocklist(name)
    canonical_parts = {_canonical_for_blocklist(part) for part in parts}
    blocked_single_words = {
        _canonical_for_blocklist(word) for word in BLOCKED_NAME_WORDS if " " not in word
    }
    blocked_phrases = {_canonical_for_blocklist(word) for word in BLOCKED_NAME_WORDS if " " in word}

    # Match blocked placeholders as complete words/phrases only.  The previous
    # substring check incorrectly rejected valid names such as "اسامة" and
    # "أسماء" because they contain the letters "اسم".
    if canonical_parts & blocked_single_words:
        return None
    if any(phrase in canonical_name for phrase in blocked_phrases):
        return None

    if len(set(parts)) == 1:
        return None

    compact = name.replace(" ", "")
    if re.search(r"(.)\1{3,}", compact):
        return None
    return name


def validate_email(value: str) -> str | None:
    value = value.strip().lower()
    return value if len(value) <= 255 and EMAIL_RE.fullmatch(value) else None


def public_id(prefix: str, length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(length))
    return f"{prefix}-{datetime.now(UTC):%y%m%d}-{suffix}"


def referral_code() -> str:
    return public_id("STU", 6)


def parse_money(value: str) -> int | None:
    digits = re.sub(r"[^0-9]", "", value)
    if not digits:
        return None
    amount = int(digits)
    return amount if 0 < amount <= 100_000_000 else None


def extract_code(text: str, pattern: str = r"\b(\d{4,8})\b") -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    return match.group(1) if match else None


def calculate_order_amounts(
    price_iqd: int, service_fee_iqd: int, management_percent: int
) -> dict[str, int]:
    management_fee = max(0, round(price_iqd * management_percent / 100))
    return {
        "subtotal_iqd": price_iqd,
        "service_fee_iqd": service_fee_iqd,
        "total_iqd": price_iqd + service_fee_iqd,
        "management_fee_iqd": management_fee,
        "provider_net_iqd": max(0, price_iqd - management_fee),
        "owner_net_iqd": service_fee_iqd + management_fee,
    }
