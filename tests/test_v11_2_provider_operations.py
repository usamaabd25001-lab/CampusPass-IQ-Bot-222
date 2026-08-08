from datetime import UTC, datetime, timedelta

import pytest

from app.domain.provider_operations import (
    OtpLeaseDecision,
    ProviderInboxStatus,
    can_transition_inbox,
    canonical_payment_name,
    normalize_balance_mode,
    parse_clock_minutes,
    provider_working_status,
    otp_lease_result,
    temporary_access_deadline,
)


def test_arabic_clock_and_payment_labels() -> None:
    assert parse_clock_minutes("١٠:٣٠") == 630
    assert canonical_payment_name("electronic").startswith("💳 دفع إلكتروني")
    assert canonical_payment_name("mobile_balance").startswith("📱 تحويل رصيد")
    assert normalize_balance_mode("recharge_card") == "recharge_card"


def test_normal_and_overnight_working_hours() -> None:
    open_now = provider_working_status(
        now=datetime(2026, 8, 4, 15, 0, tzinfo=UTC),
        weekday=1,
        opens_minute=600,
        closes_minute=1380,
    )
    assert open_now.is_open
    overnight = provider_working_status(
        now=datetime(2026, 8, 4, 1, 0, tzinfo=UTC),
        weekday=1,
        opens_minute=1320,
        closes_minute=120,
    )
    assert overnight.is_open


def test_inbox_terminal_states_cannot_reopen() -> None:
    assert can_transition_inbox("new", "resolved")
    assert not can_transition_inbox(ProviderInboxStatus.RESOLVED.value, "opened")


def test_otp_lease_is_never_longer_than_sixty_seconds() -> None:
    now = datetime.now(UTC)
    result = otp_lease_result(
        now=now,
        existing_order_id=10,
        existing_expires_at=now + timedelta(seconds=41),
        requested_order_id=20,
        lease_seconds=60,
    )
    assert result.decision is OtpLeaseDecision.BUSY
    assert 40 <= result.wait_seconds <= 41
    same = otp_lease_result(
        now=now,
        existing_order_id=10,
        existing_expires_at=now + timedelta(seconds=30),
        requested_order_id=10,
        lease_seconds=60,
    )
    assert same.decision is OtpLeaseDecision.ALREADY_HELD_BY_ORDER
    with pytest.raises(ValueError):
        otp_lease_result(
            now=now,
            existing_order_id=None,
            existing_expires_at=None,
            requested_order_id=1,
            lease_seconds=61,
        )


def test_temporary_access_grace_and_escalation() -> None:
    ends = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    grace = temporary_access_deadline(
        now=ends + timedelta(minutes=10),
        ends_at=ends,
        grace_minutes=30,
    )
    assert grace.in_grace_period and not grace.should_escalate
    overdue = temporary_access_deadline(
        now=ends + timedelta(minutes=31),
        ends_at=ends,
        grace_minutes=30,
    )
    assert overdue.should_escalate
    confirmed = temporary_access_deadline(
        now=ends + timedelta(hours=1),
        ends_at=ends,
        grace_minutes=30,
        proof_confirmed=True,
    )
    assert not confirmed.should_escalate
