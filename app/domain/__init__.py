"""Pure domain rules for CampusPass V11.

These modules intentionally avoid Telegram, SQLAlchemy, Redis and network imports.
They are the deterministic core used by handlers and services and can be tested in isolation.
"""

from app.domain.friend_packages import FriendPackageInvoice, FriendPackageProgress
from app.domain.money import CheckoutBreakdown, build_checkout_breakdown
from app.domain.navigation import NavigationAction, NavigationDecision
from app.domain.security import IdempotencyScope, ReceiptFingerprint
from app.domain.status_rewards import ActivitySnapshot, RewardRule, evaluate_rewards

__all__ = [
    "ActivitySnapshot",
    "CheckoutBreakdown",
    "FriendPackageInvoice",
    "FriendPackageProgress",
    "IdempotencyScope",
    "NavigationAction",
    "NavigationDecision",
    "ReceiptFingerprint",
    "RewardRule",
    "build_checkout_breakdown",
    "evaluate_rewards",
]
