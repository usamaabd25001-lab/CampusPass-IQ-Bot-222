import asyncio
from datetime import timedelta

from app.db.models import (
    InventoryItem,
    OfferValidityPolicy,
    SubscriptionStartTrigger,
    ValidityType,
)
from app.services.student_subscriptions import StudentSubscriptionService, _add_months
from tests.v4_helpers import aware


def run(coro):
    return asyncio.run(coro)


def test_calendar_month_end_and_days_are_distinct():
    start = aware(2028, 1, 31, 10)
    assert _add_months(start, 1) == aware(2028, 2, 29, 10)

    service = StudentSubscriptionService()
    days = OfferValidityPolicy(
        offer_id=1,
        validity_type=ValidityType.DAYS_FROM_ACTIVATION.value,
        duration_value=30,
        start_trigger=SubscriptionStartTrigger.USER_ACTIVATED.value,
    )
    months = OfferValidityPolicy(
        offer_id=2,
        validity_type=ValidityType.MONTHS_FROM_ACTIVATION.value,
        duration_value=1,
        start_trigger=SubscriptionStartTrigger.USER_ACTIVATED.value,
    )
    assert service._compute_end(days, start) == start + timedelta(days=30)
    assert service._compute_end(months, start) == aware(2028, 2, 29, 10)


def test_fixed_inventory_and_manual_validity():
    service = StudentSubscriptionService()
    start = aware(2026, 9, 1)
    fixed_end = aware(2026, 9, 30)
    item_end = aware(2026, 10, 20)
    fixed = OfferValidityPolicy(
        offer_id=3,
        validity_type=ValidityType.FIXED_OFFER_END.value,
        fixed_end_at=fixed_end,
    )
    inventory_policy = OfferValidityPolicy(
        offer_id=4,
        validity_type=ValidityType.INVENTORY_END.value,
    )
    manual = OfferValidityPolicy(offer_id=5, validity_type=ValidityType.MANUAL.value)
    item = InventoryItem(
        offer_id=4,
        encrypted_payload="encrypted",
        expires_at=item_end,
    )
    assert service._compute_end(fixed, start) == fixed_end
    assert service._compute_end(inventory_policy, start, item) == item_end
    assert service._compute_end(manual, start) is None
    assert "30/09/2026" in service.validity_label(fixed, now=start)
    assert "20/10/2026" in service.validity_label(inventory_policy, item, now=start)
