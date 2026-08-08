from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


class PaymentChannel(StrEnum):
    ELECTRONIC = "electronic"
    MOBILE_BALANCE = "mobile_balance"


class BalanceTransferMode(StrEnum):
    PHONE_TRANSFER = "phone_transfer"
    RECHARGE_CARD = "recharge_card"


class ProviderInboxStatus(StrEnum):
    NEW = "new"
    OPENED = "opened"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class ProviderInboxKind(StrEnum):
    PAYMENT_PROOF = "payment_proof"
    STUDENT_ACTIVATION_EMAIL = "student_activation_email"
    STUDENT_CODE_RELAY = "student_code_relay"
    LOGOUT_PROOF = "logout_proof"
    WARRANTY = "warranty"
    OTP_MANUAL_REVIEW = "otp_manual_review"


class OtpLeaseDecision(StrEnum):
    ACQUIRED = "acquired"
    ALREADY_HELD_BY_ORDER = "already_held_by_order"
    BUSY = "busy"


@dataclass(frozen=True, slots=True)
class WorkingStatus:
    is_open: bool
    message: str
    next_open_at: datetime | None


@dataclass(frozen=True, slots=True)
class OtpLeaseResult:
    decision: OtpLeaseDecision
    wait_seconds: int


@dataclass(frozen=True, slots=True)
class TemporaryAccessDeadline:
    expired: bool
    in_grace_period: bool
    grace_ends_at: datetime
    should_escalate: bool


def normalize_digits(value: str) -> str:
    return str(value or "").translate(_ARABIC_DIGITS).strip()


def parse_clock_minutes(value: str) -> int:
    """Parse 24-hour HH:MM input, accepting Arabic and Persian digits."""

    raw = normalize_digits(value).replace(".", ":").replace("،", ":")
    parts = [part.strip() for part in raw.split(":")]
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("اكتب الوقت بصيغة 24 ساعة، مثال 10:00 أو 23:30")
    hour, minute = (int(part) for part in parts)
    if hour not in range(24) or minute not in range(60):
        raise ValueError("الوقت خارج النطاق الصحيح")
    return hour * 60 + minute


def format_clock_minutes(value: int) -> str:
    if value < 0 or value >= 24 * 60:
        raise ValueError("minute-of-day is out of range")
    return f"{value // 60:02d}:{value % 60:02d}"


def provider_working_status(
    *,
    now: datetime,
    weekday: int,
    opens_minute: int,
    closes_minute: int,
    is_closed: bool = False,
) -> WorkingStatus:
    """Return the public provider status, including overnight working windows."""

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if weekday not in range(7):
        raise ValueError("weekday must be between 0 and 6")
    if is_closed:
        next_open = (now + timedelta(days=1)).replace(
            hour=opens_minute // 60,
            minute=opens_minute % 60,
            second=0,
            microsecond=0,
        )
        return WorkingStatus(False, f"🔴 خارج أوقات العمل - نعود {format_clock_minutes(opens_minute)}", next_open)

    minute = now.hour * 60 + now.minute
    overnight = closes_minute <= opens_minute
    is_open = (
        opens_minute <= minute < closes_minute
        if not overnight
        else minute >= opens_minute or minute < closes_minute
    )
    if is_open:
        return WorkingStatus(True, "🟢 متواجد الآن", None)

    if not overnight and minute < opens_minute:
        next_open = now.replace(
            hour=opens_minute // 60,
            minute=opens_minute % 60,
            second=0,
            microsecond=0,
        )
    else:
        next_open = (now + timedelta(days=1)).replace(
            hour=opens_minute // 60,
            minute=opens_minute % 60,
            second=0,
            microsecond=0,
        )
    return WorkingStatus(
        False,
        f"🔴 خارج أوقات العمل - نعود {format_clock_minutes(opens_minute)}",
        next_open,
    )


def canonical_payment_name(channel: str) -> str:
    normalized = str(channel or "").strip().lower()
    if normalized == PaymentChannel.ELECTRONIC.value:
        return "💳 دفع إلكتروني (ماستر كارد، زين كاش)"
    if normalized == PaymentChannel.MOBILE_BALANCE.value:
        return "📱 تحويل رصيد (آسيا، زين، كورك)"
    raise ValueError("نوع الدفع غير مدعوم")


def normalize_balance_mode(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    normalized = str(value).strip().lower()
    allowed = {item.value for item in BalanceTransferMode}
    if normalized not in allowed:
        raise ValueError("نوع دفع الرصيد غير مدعوم")
    return normalized


_ALLOWED_INBOX_TRANSITIONS: dict[str, frozenset[str]] = {
    ProviderInboxStatus.NEW.value: frozenset(
        {
            ProviderInboxStatus.OPENED.value,
            ProviderInboxStatus.IN_PROGRESS.value,
            ProviderInboxStatus.RESOLVED.value,
            ProviderInboxStatus.REJECTED.value,
            ProviderInboxStatus.ESCALATED.value,
        }
    ),
    ProviderInboxStatus.OPENED.value: frozenset(
        {
            ProviderInboxStatus.IN_PROGRESS.value,
            ProviderInboxStatus.RESOLVED.value,
            ProviderInboxStatus.REJECTED.value,
            ProviderInboxStatus.ESCALATED.value,
        }
    ),
    ProviderInboxStatus.IN_PROGRESS.value: frozenset(
        {
            ProviderInboxStatus.RESOLVED.value,
            ProviderInboxStatus.REJECTED.value,
            ProviderInboxStatus.ESCALATED.value,
        }
    ),
    ProviderInboxStatus.ESCALATED.value: frozenset(
        {
            ProviderInboxStatus.IN_PROGRESS.value,
            ProviderInboxStatus.RESOLVED.value,
            ProviderInboxStatus.REJECTED.value,
        }
    ),
    ProviderInboxStatus.RESOLVED.value: frozenset(),
    ProviderInboxStatus.REJECTED.value: frozenset(),
}


def can_transition_inbox(current: str, target: str) -> bool:
    return target in _ALLOWED_INBOX_TRANSITIONS.get(str(current), frozenset())


def otp_lease_result(
    *,
    now: datetime,
    existing_order_id: int | None,
    existing_expires_at: datetime | None,
    requested_order_id: int,
    lease_seconds: int = 60,
) -> OtpLeaseResult:
    """Pure decision function used before the database lease is changed."""

    if lease_seconds < 1 or lease_seconds > 60:
        raise ValueError("OTP lease must be between 1 and 60 seconds")
    if existing_expires_at is None or existing_expires_at <= now:
        return OtpLeaseResult(OtpLeaseDecision.ACQUIRED, 0)
    wait = max(1, int((existing_expires_at - now).total_seconds()))
    if existing_order_id == requested_order_id:
        return OtpLeaseResult(OtpLeaseDecision.ALREADY_HELD_BY_ORDER, wait)
    return OtpLeaseResult(OtpLeaseDecision.BUSY, wait)


def temporary_access_deadline(
    *,
    now: datetime,
    ends_at: datetime,
    grace_minutes: int = 30,
    proof_confirmed: bool = False,
) -> TemporaryAccessDeadline:
    if grace_minutes < 1:
        raise ValueError("grace_minutes must be positive")
    if now.tzinfo is None or ends_at.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    grace_end = ends_at + timedelta(minutes=grace_minutes)
    expired = now >= ends_at
    in_grace = expired and now < grace_end and not proof_confirmed
    return TemporaryAccessDeadline(
        expired=expired,
        in_grace_period=in_grace,
        grace_ends_at=grace_end,
        should_escalate=not proof_confirmed and now >= grace_end,
    )


def utc_now() -> datetime:
    return datetime.now(UTC)
