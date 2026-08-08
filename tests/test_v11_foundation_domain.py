from app.domain.friend_packages import FriendPackageInvoice, FriendPackageProgress
from app.domain.money import build_checkout_breakdown
from app.domain.navigation import NavigationAction, NavigationDecision
from app.domain.security import IdempotencyScope, ReceiptFingerprint, idempotency_key
from app.domain.status_rewards import (
    ActivitySnapshot,
    RewardKind,
    RewardRule,
    evaluate_rewards,
)


def test_wallet_covers_complete_bot_fee_only() -> None:
    result = build_checkout_breakdown(
        service_price_iqd=10_000,
        bot_fee_iqd=500,
        wallet_balance_iqd=700,
    )
    assert result.wallet_fee_deduction_iqd == 500
    assert result.wallet_balance_after_iqd == 200
    assert result.amount_due_iqd == 10_000


def test_wallet_below_fee_is_not_partially_debited() -> None:
    result = build_checkout_breakdown(
        service_price_iqd=10_000,
        bot_fee_iqd=500,
        wallet_balance_iqd=499,
    )
    assert result.wallet_fee_deduction_iqd == 0
    assert result.wallet_balance_after_iqd == 499
    assert result.amount_due_iqd == 10_500


def test_discount_never_uses_wallet_against_service_price() -> None:
    result = build_checkout_breakdown(
        service_price_iqd=10_000,
        discount_iqd=2_000,
        bot_fee_iqd=500,
        wallet_balance_iqd=500,
    )
    assert result.discounted_service_price_iqd == 8_000
    assert result.wallet_fee_deduction_iqd == 500
    assert result.amount_due_iqd == 8_000


def test_friend_package_charges_full_bot_fee_per_member() -> None:
    invoice = FriendPackageInvoice(member_share_iqd=5_000, bot_fee_iqd=500)
    assert invoice.amount_due_iqd == 5_500


def test_friend_package_progress_requires_full_group() -> None:
    progress = FriendPackageProgress(required_members=4, paid_members=3)
    assert progress.remaining_members == 1
    assert not progress.is_complete
    assert "المتبقي 1" in progress.status_text


def test_status_rewards_are_configuration_driven() -> None:
    activity = ActivitySnapshot(
        successful_referrals=5,
        referral_purchases=3,
        status_link_shares=8,
        completed_orders=2,
        activity_points=100,
    )
    rules = [
        RewardRule(
            code="ACTIVE-MEDICAL-STUDENT",
            kind=RewardKind.DISCOUNT_CODE,
            minimum_referral_purchases=3,
            minimum_activity_points=80,
            value_iqd_or_percent=20,
        ),
        RewardRule(
            code="POWER-AMBASSADOR",
            kind=RewardKind.EXCLUSIVE_OFFER,
            minimum_referral_purchases=10,
        ),
    ]
    unlocked = evaluate_rewards(activity, rules)
    assert [item.code for item in unlocked] == ["ACTIVE-MEDICAL-STUDENT"]


def test_navigation_contract() -> None:
    back = NavigationDecision.back()
    home = NavigationDecision.home()
    assert back.action is NavigationAction.BACK
    assert not back.clear_fsm
    assert home.action is NavigationAction.HOME
    assert home.clear_fsm
    assert home.preserve_committed_order


def test_receipt_fingerprint_and_idempotency_are_deterministic() -> None:
    first = ReceiptFingerprint.from_bytes(b"receipt-image")
    second = ReceiptFingerprint.from_bytes(b"receipt-image")
    assert first == second
    key1 = idempotency_key(IdempotencyScope.PAYMENT_CONFIRMATION, 123, 456)
    key2 = idempotency_key(IdempotencyScope.PAYMENT_CONFIRMATION, 123, 456)
    assert key1 == key2
    assert key1.startswith("payment-confirmation:")
