from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
HANDLERS = APP / "bot" / "handlers"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_coupon_prompt_and_targeted_provider_coupon_flow_are_wired() -> None:
    catalog = read("app/bot/handlers/catalog.py")
    provider = read("app/bot/handlers/provider_coupons.py")
    service = read("app/services/order_coupons.py")
    router = read("app/bot/handlers/__init__.py")
    assert "هل لديك كود خصم؟" in catalog
    assert "coupon:apply:" in catalog and "coupon:skip:" in catalog
    assert "provider:student_coupons" in provider
    assert "target_user_id=target.id" in provider
    assert "OrderCouponType.FEE_WAIVER.value" in service
    assert "OrderCouponType.FREE_REPORT.value" in service
    assert "coupon.target_user_id" in service
    assert "router.include_router(provider_coupons.router)" in router


def test_referral_reward_is_first_purchase_only_and_coupon_idempotent() -> None:
    finance = read("app/services/finance.py")
    users = read("app/services/users.py")
    menu = read("app/bot/handlers/menu.py")
    assert "completed_count == 1" in finance
    assert "referral:success:" in finance
    assert "referral:coupon:" in finance
    assert "OrderCouponType.FEE_WAIVER.value" in finance
    assert "referral_invites_per_coupon" in finance
    assert "WalletEntryType.REFERRAL.value" not in finance
    assert "completed == 0" in users
    assert "normalize_referral_payload" in users
    assert "?start=ref_" in menu
    assert "مشاركة رابط الدعوة" in menu
    assert "لا يُضاف رصيد مالي للمحفظة" in menu


def test_payment_proof_review_is_hardened_and_receipt_controls_are_exact() -> None:
    handler = read("app/bot/handlers/payments.py")
    service = read("app/services/payments.py")
    keyboard = read("app/bot/keyboards/inline.py")
    assert "PaymentProofStates.proof_file" in handler
    assert "payment_proof_max_bytes" in handler
    assert "evidence.send(" in handler
    assert "payment_review_keyboard(order.id)" in handler
    assert "existing_for_order" in service
    assert "يوجد وصل قيد المراجعة لهذا الطلب بالفعل" in service
    assert "✅ موافقة وفتح الطلب" in keyboard
    assert "❌ رفض الوصل مع سبب" in keyboard


def test_missing_service_request_has_real_id_and_admin_quick_reply() -> None:
    menu = read("app/bot/handlers/menu.py")
    models = read("app/db/models.py")
    assert "await session.flush()" in menu
    assert 'request_code = f"MSR-{request.id}"' in menu
    assert 'callback_data=f"missing:reply:{request.id}"' in menu
    assert "MissingServiceReplyStates.text" in menu
    assert "request.responded_by_user_id = actor.id" in menu
    assert "response_text" in models and "responded_at" in models


def test_v10_4_migrations_and_runtime_configuration_are_additive() -> None:
    custom = read("app/db/migrations.py")
    alembic = read("alembic/versions/1040_commerce_referral_payments.py")
    config = read("app/core/config.py")
    version = read("VERSION.txt").strip()
    assert version == "10.7.0-emergency-stabilization"
    assert 'version="10.4.0-commerce-referral-payments"' in custom
    assert 'down_revision = "1030_offer_lifecycle_security"' in alembic
    assert "cp_user_benefits" in alembic
    assert "target_user_id" in alembic
    assert "REFERRAL_REWARD_POINTS" in config
    assert "REFERRAL_WALLET_REWARD_IQD" in config
    assert "PAYMENT_PROOF_MAX_BYTES" in config
