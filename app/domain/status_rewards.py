from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RewardKind(StrEnum):
    WALLET_CREDIT = "wallet_credit"
    DISCOUNT_CODE = "discount_code"
    BOT_FEE_RELIEF = "bot_fee_relief"
    EXCLUSIVE_OFFER = "exclusive_offer"


@dataclass(slots=True, frozen=True)
class ActivitySnapshot:
    successful_referrals: int = 0
    referral_purchases: int = 0
    status_link_shares: int = 0
    completed_orders: int = 0
    activity_points: int = 0

    def __post_init__(self) -> None:
        for value in (
            self.successful_referrals,
            self.referral_purchases,
            self.status_link_shares,
            self.completed_orders,
            self.activity_points,
        ):
            if value < 0:
                raise ValueError("activity counters cannot be negative")


@dataclass(slots=True, frozen=True)
class RewardRule:
    code: str
    kind: RewardKind
    minimum_referrals: int = 0
    minimum_referral_purchases: int = 0
    minimum_status_shares: int = 0
    minimum_completed_orders: int = 0
    minimum_activity_points: int = 0
    value_iqd_or_percent: int = 0

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("reward rule code is required")
        for value in (
            self.minimum_referrals,
            self.minimum_referral_purchases,
            self.minimum_status_shares,
            self.minimum_completed_orders,
            self.minimum_activity_points,
            self.value_iqd_or_percent,
        ):
            if value < 0:
                raise ValueError("reward rule values cannot be negative")

    def is_unlocked(self, activity: ActivitySnapshot) -> bool:
        return (
            activity.successful_referrals >= self.minimum_referrals
            and activity.referral_purchases >= self.minimum_referral_purchases
            and activity.status_link_shares >= self.minimum_status_shares
            and activity.completed_orders >= self.minimum_completed_orders
            and activity.activity_points >= self.minimum_activity_points
        )


def evaluate_rewards(
    activity: ActivitySnapshot,
    rules: list[RewardRule] | tuple[RewardRule, ...],
    *,
    already_granted_codes: set[str] | frozenset[str] = frozenset(),
) -> list[RewardRule]:
    """Return newly unlocked rules.

    Rules are configuration-driven. No fixed «card every three referrals» logic
    exists in the domain layer.
    """

    granted = {code.strip() for code in already_granted_codes}
    return [rule for rule in rules if rule.code not in granted and rule.is_unlocked(activity)]
