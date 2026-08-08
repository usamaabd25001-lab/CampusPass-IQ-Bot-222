from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Mapping


class FavoriteTarget(StrEnum):
    PROVIDER = "provider"
    SECTION = "section"
    OFFER = "offer"


class PaymentRoute(StrEnum):
    ELECTRONIC = "electronic"
    BALANCE_TRANSFER = "balance_transfer"
    RECHARGE_CARD = "recharge_card"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class ProfileCompletion:
    complete: bool
    missing_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InvoiceBreakdown:
    service_price_iqd: int
    discount_iqd: int
    bot_fee_iqd: int
    wallet_fee_deduction_iqd: int
    cash_due_iqd: int
    wallet_balance_after_iqd: int

    @property
    def discounted_service_price_iqd(self) -> int:
        return max(0, self.service_price_iqd - self.discount_iqd)

    @property
    def wallet_covered_bot_fee(self) -> bool:
        return self.bot_fee_iqd > 0 and self.wallet_fee_deduction_iqd == self.bot_fee_iqd


PROFILE_FIELDS: tuple[str, ...] = (
    "full_name",
    "phone",
    "governorate",
    "university",
    "college",
    "department",
    "stage",
)

_PROFILE_PLACEHOLDERS = {
    "",
    "-",
    "غير محدد",
    "يستكمل لاحقاً",
    "يُستكمل لاحقاً",
    "لاحقاً",
}


def profile_completion(values: Mapping[str, object] | None) -> ProfileCompletion:
    data = values or {}
    missing: list[str] = []
    for field in PROFILE_FIELDS:
        value = str(data.get(field) or "").strip()
        if value in _PROFILE_PLACEHOLDERS or "يستكمل" in value or "يُستكمل" in value:
            missing.append(field)
    return ProfileCompletion(complete=not missing, missing_fields=tuple(missing))


def net_wallet_fee_deduction(
    snapshot: Mapping[str, object] | None,
    *,
    current_bot_fee_iqd: int | None = None,
) -> int:
    """Return the still-effective wallet debit used for the bot fee.

    The order may refund the automatic wallet debit after a fee-waiver coupon
    or cancellation. Reading only the original deduction would therefore
    misreport money that has already been returned.
    """

    values = snapshot or {}
    deducted = max(0, int(values.get("wallet_fee_deduction_iqd", 0) or 0))
    refunded = max(0, int(values.get("wallet_fee_refunded_iqd", 0) or 0))
    net = max(0, deducted - refunded)
    if current_bot_fee_iqd is not None:
        net = min(net, max(0, int(current_bot_fee_iqd)))
    return net


def calculate_invoice(
    *,
    service_price_iqd: int,
    bot_fee_iqd: int,
    wallet_balance_iqd: int,
    discount_iqd: int = 0,
) -> InvoiceBreakdown:
    """Calculate the approved checkout policy using integer IQD only.

    The wallet may cover the complete bot fee, and only the complete bot fee.
    A balance below the fee is preserved and no partial debit is performed.
    """

    service_price = max(0, int(service_price_iqd))
    bot_fee = max(0, int(bot_fee_iqd))
    wallet_balance = max(0, int(wallet_balance_iqd))
    discount = min(max(0, int(discount_iqd)), service_price)

    wallet_fee = bot_fee if bot_fee > 0 and wallet_balance >= bot_fee else 0
    cash_due = (service_price - discount) + (bot_fee - wallet_fee)
    return InvoiceBreakdown(
        service_price_iqd=service_price,
        discount_iqd=discount,
        bot_fee_iqd=bot_fee,
        wallet_fee_deduction_iqd=wallet_fee,
        cash_due_iqd=max(0, cash_due),
        wallet_balance_after_iqd=wallet_balance - wallet_fee,
    )


def format_offer_button(*, service_name: str, duration_label: str, price_iqd: int) -> str:
    service = " ".join((service_name or "الخدمة").split())
    duration = " ".join((duration_label or "حسب العرض").split())
    return f"{service} - {duration} - {max(0, int(price_iqd)):,} د.ع"


def seconds_until_open(
    *,
    now: datetime,
    weekday: int,
    opens_minute: int,
    closes_minute: int,
    is_closed: bool = False,
) -> tuple[bool, int | None]:
    """Return whether a provider is open and minutes until opening for one day row.

    This pure helper intentionally handles the normal same-day Iraqi work schedule.
    Cross-midnight schedules are represented by two working-hour rows.
    """

    if is_closed or now.weekday() != int(weekday):
        return False, None
    minute = now.hour * 60 + now.minute
    opens = max(0, min(1439, int(opens_minute)))
    closes = max(0, min(1440, int(closes_minute)))
    if opens <= minute < closes:
        return True, 0
    if minute < opens:
        return False, opens - minute
    return False, None
