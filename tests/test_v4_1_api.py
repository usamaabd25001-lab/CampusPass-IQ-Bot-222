import asyncio
import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app.api.server import build_api
from app.core.context import AppContext
from app.core.database import Database
from app.core.security import SecretBox
from app.db.migrations import run_migrations
from app.db.models import Category, Offer, Order, OrderStatus, Provider, ProviderStatus, User
from app.db.seed import seed_defaults
from app.services.container import Services
from tests.v4_helpers import FakeBot, settings


def run(coro):
    return asyncio.run(coro)


async def _prepare(context: AppContext) -> int:
    await context.database.create_tables()
    async with context.database.session_factory() as session:
        await run_migrations(session)
        await seed_defaults(session)
        provider = Provider(
            name_ar="منصة API V4.1",
            slug="api-v41",
            status=ProviderStatus.ACTIVE.value,
        )
        category = Category(name="API V4.1")
        user = User(telegram_id=43001, telegram_name="طالب API", referral_code="API-V41")
        session.add_all([provider, category, user])
        await session.flush()
        offer = Offer(
            provider_id=provider.id,
            category_id=category.id,
            title="خدمة API يدوية",
            price_iqd=2500,
            service_fee_iqd=500,
            status="active",
            delivery_type="manual",
        )
        session.add(offer)
        await session.flush()
        order = Order(
            public_id="CP-API-V41",
            user_id=user.id,
            provider_id=provider.id,
            offer_id=offer.id,
            status=OrderStatus.WAITING_PAYMENT.value,
            subtotal_iqd=2500,
            service_fee_iqd=500,
            total_iqd=3000,
        )
        session.add(order)
        await session.commit()
        return order.id


async def _order_status(context: AppContext, order_id: int) -> str:
    async with context.database.session_factory() as session:
        order = await session.get(Order, order_id)
        assert order
        return order.status


def test_api_health_is_minimal_and_payment_webhook_is_end_to_end(tmp_path):
    config = settings(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'api.db'}",
        API_ADMIN_TOKEN="a" * 40,
        FEATURE_MASTERCARD=True,
        PUBLIC_BASE_URL="https://campuspass.example",
        PAYMENT_GATEWAY_CREATE_URL="https://gateway.example/checkout",
        PAYMENT_GATEWAY_API_KEY="api-key",
        PAYMENT_GATEWAY_MERCHANT_ID="merchant",
        PAYMENT_WEBHOOK_SECRET="s" * 40,
    )
    database = Database(config)
    bot = FakeBot()
    secrets = SecretBox(config)
    services = Services(bot, config, secrets)
    context = AppContext(config, database, secrets, services, bot)
    order_id = run(_prepare(context))

    with TestClient(build_api(context)) as client:
        live = client.get("/health/live")
        assert live.status_code == 200
        assert set(live.json()) == {"status", "version", "checked_at"}

        ready = client.get("/health")
        assert ready.status_code == 200
        assert set(ready.json()) == {"status", "version"}

        assert client.get("/admin/health").status_code == 401
        admin = client.get(
            "/admin/health", headers={"Authorization": f"Bearer {config.api_admin_token}"}
        )
        assert admin.status_code == 200
        assert "modules" in admin.json()

        payload = {
            "event_id": "API-EVENT-1",
            "reference": "API-GATEWAY-REF-1",
            "order_id": "CP-API-V41",
            "status": "captured",
            "amount": 3000,
            "currency": "IQD",
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        signature = hmac.new(
            config.payment_webhook_secret.encode(), raw, hashlib.sha256
        ).hexdigest()
        response = client.post(
            "/webhooks/payments/mastercard",
            content=raw,
            headers={"Content-Type": "application/json", "X-Signature": signature},
        )
        assert response.status_code == 200
        assert response.json()["accepted"] is True
        assert response.json()["fulfillment"] == "queued"

        repeated = client.post(
            "/webhooks/payments/mastercard",
            content=raw,
            headers={"Content-Type": "application/json", "X-Signature": signature},
        )
        assert repeated.status_code == 200
        assert repeated.json()["duplicate"] is True

    assert run(_order_status(context, order_id)) == OrderStatus.PROCESSING.value
    run(database.close())
