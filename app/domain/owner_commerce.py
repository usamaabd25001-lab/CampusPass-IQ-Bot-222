from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

_ALLOWED_AUDIENCE_KEYS = {
    "all",
    "college",
    "university",
    "department",
    "stage",
    "governorate",
    "provider_buyers",
    "provider_top_buyers",
    "expired_subscription",
    "favorite_offer",
    "status_link_sharers",
    "most_active",
}


@dataclass(frozen=True, slots=True)
class BillingDecision:
    should_issue: bool
    due_at: datetime
    next_invoice_at: datetime


@dataclass(frozen=True, slots=True)
class HybridAllocation:
    provider_id: int
    offer_id: int
    amount_iqd: int


def normalize_audience_rule(rule: dict[str, Any] | None) -> dict[str, Any]:
    value = dict(rule or {})
    key = str(value.get("type") or "all").strip().lower()
    if key not in _ALLOWED_AUDIENCE_KEYS:
        raise ValueError("نوع الجمهور غير مدعوم")
    result: dict[str, Any] = {"type": key}
    if key not in {"all", "most_active", "status_link_sharers"}:
        target = value.get("value")
        if target in {None, ""}:
            raise ValueError("قيمة الجمهور مطلوبة")
        result["value"] = int(target) if key in {"provider_buyers", "provider_top_buyers", "favorite_offer"} else str(target).strip()
    limit = int(value.get("limit") or 50000)
    if not 1 <= limit <= 100000:
        raise ValueError("حد الجمهور يجب أن يكون بين 1 و100000")
    result["limit"] = limit
    return result


def billing_decision(*, next_invoice_at: datetime, cycle_days: int, due_hours: int, now: datetime | None = None) -> BillingDecision:
    moment = now or datetime.now(UTC)
    if cycle_days not in {7, 30}:
        raise ValueError("دورة الفوترة يجب أن تكون أسبوعية أو شهرية")
    if not 1 <= due_hours <= 24 * 30:
        raise ValueError("مهلة السداد غير صالحة")
    return BillingDecision(
        should_issue=next_invoice_at <= moment,
        due_at=moment + timedelta(hours=due_hours),
        next_invoice_at=max(next_invoice_at, moment) + timedelta(days=cycle_days),
    )


def validate_hybrid_allocations(*, bundle_price_iqd: int, bot_fee_iqd: int, allocations: list[HybridAllocation]) -> None:
    if bundle_price_iqd <= 0:
        raise ValueError("سعر الباقة يجب أن يكون أكبر من صفر")
    if bot_fee_iqd < 0 or bot_fee_iqd >= bundle_price_iqd:
        raise ValueError("رسوم البوت غير صالحة")
    if len(allocations) < 2:
        raise ValueError("الباقة الهجينة تحتاج خدمتين على الأقل")
    keys = {(item.provider_id, item.offer_id) for item in allocations}
    if len(keys) != len(allocations):
        raise ValueError("لا يمكن تكرار مكون داخل الباقة")
    if any(item.amount_iqd <= 0 for item in allocations):
        raise ValueError("حصة كل منصة يجب أن تكون أكبر من صفر")
    if sum(item.amount_iqd for item in allocations) + bot_fee_iqd != bundle_price_iqd:
        raise ValueError("مجموع حصص المنصات ورسوم البوت لا يساوي سعر الباقة")


def reward_campaign_capacity(*, budget_iqd: int, reward_iqd: int, requested_count: int) -> int:
    if budget_iqd <= 0 or reward_iqd <= 0 or requested_count <= 0:
        raise ValueError("ميزانية ومكافأة وعدد المهمة يجب أن تكون موجبة")
    affordable = budget_iqd // reward_iqd
    if affordable <= 0:
        raise ValueError("الميزانية لا تكفي لمكافأة طالب واحد")
    return min(affordable, requested_count)
