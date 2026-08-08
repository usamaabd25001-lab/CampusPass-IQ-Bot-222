import asyncio
import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.db.models import (
    Category,
    Offer,
    Order,
    OrderStatus,
    PaymentStatus,
    Provider,
    ProviderStatus,
    Report,
    ReportAccess,
    User,
)
from app.integrations.payments.mastercard import CheckoutSession
from tests.v4_helpers import database_bundle, services_bundle


def run(coro):
    return asyncio.run(coro)


def test_production_requires_stable_secrets_and_https():
    with pytest.raises(ValidationError):
        Settings(
            BOT_TOKEN="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
            ADMIN_IDS="9001",
            DATABASE_URL="postgresql+asyncpg://user:pass@db/app",
            ENVIRONMENT="production",
            PUBLIC_BASE_URL="http://example.com",
        )


async def _gateway_scenario():
    engine, factory = await database_bundle()
    config, _bot, secrets, services = services_bundle(
        FEATURE_MASTERCARD=True,
        PUBLIC_BASE_URL="https://campuspass.example",
        PAYMENT_GATEWAY_CREATE_URL="https://gateway.example/checkout",
        PAYMENT_GATEWAY_API_KEY="gateway-api-key",
        PAYMENT_GATEWAY_MERCHANT_ID="merchant-1",
        PAYMENT_WEBHOOK_SECRET="w" * 40,
    )
    async with factory() as session:
        provider = Provider(
            name_ar="بوابة دفع V4.1",
            slug="gateway-v41",
            status=ProviderStatus.ACTIVE.value,
        )
        category = Category(name="اختبار الدفع V4.1")
        user = User(telegram_id=41001, telegram_name="طالب", referral_code="V41-U")
        session.add_all([provider, category, user])
        await session.flush()
        offer = Offer(
            provider_id=provider.id,
            category_id=category.id,
            title="اشتراك دفع إلكتروني",
            price_iqd=10000,
            service_fee_iqd=500,
            status="active",
        )
        session.add(offer)
        await session.flush()
        order = Order(
            public_id="CP-V41-PAY",
            user_id=user.id,
            provider_id=provider.id,
            offer_id=offer.id,
            status=OrderStatus.WAITING_PAYMENT.value,
            subtotal_iqd=10000,
            service_fee_iqd=500,
            total_iqd=10500,
        )
        session.add(order)
        await session.flush()

        checkout = CheckoutSession(
            reference="GW-REF-41001",
            checkout_url="https://gateway.example/pay/41001",
            raw={"reference": "GW-REF-41001"},
        )
        pending = await services.payments.register_checkout(session, order, checkout)
        assert pending.status == PaymentStatus.PENDING.value

        payload = {
            "event_id": "EV-41001",
            "data": {
                "transaction_id": "GW-REF-41001",
                "order_id": order.public_id,
                "status": "captured",
                "amount": 10500,
                "currency": "IQD",
            },
        }
        notification = services.mastercard.parse_webhook(payload)
        result = await services.payments.process_gateway_notification(session, notification)
        assert result.accepted is True
        assert result.duplicate is False
        assert result.payment and result.payment.status == PaymentStatus.CONFIRMED.value
        assert order.status == OrderStatus.PAID.value

        duplicate = await services.payments.process_gateway_notification(session, notification)
        assert duplicate.duplicate is True
        assert duplicate.accepted is True

        raw = b'{"event":"test"}'
        signature = hmac.new(
            config.payment_webhook_secret.encode(), raw, hashlib.sha256
        ).hexdigest()
        assert services.mastercard.verify_webhook(raw, f"sha256={signature}") is True
        assert services.mastercard.verify_webhook(raw, "bad") is False
        await session.commit()
    await engine.dispose()


def test_gateway_webhook_is_verified_and_idempotent():
    run(_gateway_scenario())


async def _reports_reviews_scenario():
    engine, factory = await database_bundle()
    config, _bot, secrets, services = services_bundle(REPORT_MAX_ACCESSES=1)
    async with factory() as session:
        provider = Provider(
            name_ar="منصة التقارير والتقييم",
            slug="report-review-v41",
            status=ProviderStatus.ACTIVE.value,
        )
        category = Category(name="تقارير V4.1")
        user = User(telegram_id=42001, telegram_name="طالب", referral_code="V41-R")
        session.add_all([provider, category, user])
        await session.flush()
        offer = Offer(
            provider_id=provider.id,
            category_id=category.id,
            title="خدمة مكتملة",
            price_iqd=1000,
            status="active",
        )
        session.add(offer)
        await session.flush()
        order = Order(
            public_id="CP-V41-REVIEW",
            user_id=user.id,
            provider_id=provider.id,
            offer_id=offer.id,
            status=OrderStatus.COMPLETED.value,
            subtotal_iqd=1000,
            total_iqd=1000,
        )
        report = Report(
            provider_id=provider.id,
            report_type="provider_daily",
            period_start=datetime.now(UTC) - timedelta(days=1),
            period_end=datetime.now(UTC),
            snapshot={"emails": [{"username": "ab***z@example.com"}]},
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        session.add_all([order, report])
        await session.flush()

        token = secrets.sign_report(report.id, report.expires_at)
        session.add(
            ReportAccess(
                report_id=report.id,
                token_hash=secrets.hash_value(token),
                max_accesses=config.report_max_accesses,
            )
        )
        await session.flush()
        assert await services.reports.resolve_report(session, token) is report
        assert await services.reports.resolve_report(session, token) is None

        review = await services.reviews.submit_rating(session, user, order, 5)
        assert review.rating == 5
        await services.reviews.set_comment(session, user, order.id, "خدمة ممتازة وسريعة")
        average, count = await services.reviews.provider_summary(session, provider.id)
        assert average == 5.0
        assert count == 1
        await session.commit()
    await engine.dispose()


def test_report_access_limits_and_verified_reviews():
    run(_reports_reviews_scenario())
