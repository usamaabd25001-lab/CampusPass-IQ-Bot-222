from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class CheckoutBreakdown:
    """Deterministic IQD checkout calculation.

    All values are integer Iraqi dinars. The student wallet may cover the bot
    service fee only. A partial wallet deduction is never allowed.
    """

    service_price_iqd: int
    discount_iqd: int
    bot_fee_iqd: int
    wallet_balance_before_iqd: int
    wallet_fee_deduction_iqd: int
    wallet_balance_after_iqd: int
    amount_due_iqd: int

    @property
    def discounted_service_price_iqd(self) -> int:
        return self.service_price_iqd - self.discount_iqd


def _non_negative(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer IQD amount")
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
    return value


def build_checkout_breakdown(
    *,
    service_price_iqd: int,
    discount_iqd: int = 0,
    bot_fee_iqd: int = 500,
    wallet_balance_iqd: int = 0,
) -> CheckoutBreakdown:
    """Apply the approved V11 wallet rule.

    - Discount cannot exceed the service price.
    - Wallet covers the complete bot fee only when its balance is sufficient.
    - If wallet balance is below the complete fee, zero is deducted.
    - Wallet never reduces the service price.
    """

    service_price_iqd = _non_negative("service_price_iqd", service_price_iqd)
    discount_iqd = _non_negative("discount_iqd", discount_iqd)
    bot_fee_iqd = _non_negative("bot_fee_iqd", bot_fee_iqd)
    wallet_balance_iqd = _non_negative("wallet_balance_iqd", wallet_balance_iqd)

    if discount_iqd > service_price_iqd:
        raise ValueError("discount_iqd cannot exceed service_price_iqd")

    wallet_deduction = bot_fee_iqd if wallet_balance_iqd >= bot_fee_iqd else 0
    discounted_service = service_price_iqd - discount_iqd
    amount_due = discounted_service + bot_fee_iqd - wallet_deduction

    return CheckoutBreakdown(
        service_price_iqd=service_price_iqd,
        discount_iqd=discount_iqd,
        bot_fee_iqd=bot_fee_iqd,
        wallet_balance_before_iqd=wallet_balance_iqd,
        wallet_fee_deduction_iqd=wallet_deduction,
        wallet_balance_after_iqd=wallet_balance_iqd - wallet_deduction,
        amount_due_iqd=amount_due,
    )
