import asyncio

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Category,
    InventoryFingerprint,
    InventoryItem,
    Offer,
    Order,
    OrderStatus,
    PaymentMethod,
    PaymentProof,
    PaymentProofStatus,
    Provider,
    ProviderStatus,
    User,
)
from tests.v4_helpers import database_bundle, services_bundle


def run(coro):
    return asyncio.run(coro)


async def _payment_security_scenario():
    engine, factory = await database_bundle()
    _settings, _bot, _secrets, services = services_bundle()
    async with factory() as session:
        category = Category(name="أمن الدفع V4")
        provider_a = Provider(
            name_ar="منصة الأمن أ",
            slug="security-a",
            status=ProviderStatus.ACTIVE.value,
        )
        provider_b = Provider(
            name_ar="منصة الأمن ب",
            slug="security-b",
            status=ProviderStatus.ACTIVE.value,
        )
        user = User(telegram_id=3333, telegram_name="طالب", referral_code="SEC-U")
        session.add_all([category, provider_a, provider_b, user])
        await session.flush()
        offer = Offer(
            provider_id=provider_a.id,
            category_id=category.id,
            title="عرض أمني",
            price_iqd=1000,
            service_fee_iqd=500,
            status="active",
        )
        session.add(offer)
        await session.flush()
        method_a = PaymentMethod(provider_id=provider_a.id, name="دفع أ")
        method_b = PaymentMethod(provider_id=provider_b.id, name="دفع ب")
        session.add_all([method_a, method_b])
        await session.flush()
        order = Order(
            public_id="CP-SEC-A",
            user_id=user.id,
            provider_id=provider_a.id,
            offer_id=offer.id,
            status=OrderStatus.WAITING_PAYMENT.value,
            subtotal_iqd=1000,
            service_fee_iqd=500,
            total_iqd=1500,
        )
        other_order = Order(
            public_id="CP-SEC-B",
            user_id=user.id,
            provider_id=provider_a.id,
            offer_id=offer.id,
            status=OrderStatus.WAITING_PAYMENT.value,
            subtotal_iqd=1000,
            service_fee_iqd=500,
            total_iqd=1500,
        )
        session.add_all([order, other_order])
        await session.flush()

        with pytest.raises(PermissionError, match="لا تخص"):
            await services.orders.set_payment_method(session, order, method_b)
        await services.orders.set_payment_method(session, order, method_a)
        assert order.payment_method_id == method_a.id

        session.add(
            PaymentProof(
                order_id=other_order.id,
                claimed_amount_iqd=1500,
                reference="DUPLICATE-REFERENCE",
                status=PaymentProofStatus.PENDING.value,
            )
        )
        await session.flush()
        with pytest.raises(ValueError, match="مستخدم في طلب آخر"):
            await services.payments.submit_proof(
                session,
                order,
                photo_file_id="photo",
                document_file_id=None,
                sender_phone="07701234567",
                claimed_amount_iqd=1500,
                reference="DUPLICATE-REFERENCE",
            )
    await engine.dispose()


async def _inventory_fingerprint_scenario():
    engine, factory = await database_bundle()
    async with factory() as session:
        category = Category(name="أمن المخزون V4")
        provider = Provider(
            name_ar="منصة مخزون آمن",
            slug="inventory-secure",
            status=ProviderStatus.ACTIVE.value,
        )
        session.add_all([category, provider])
        await session.flush()
        offer = Offer(
            provider_id=provider.id,
            category_id=category.id,
            title="كود آمن",
            price_iqd=1000,
            status="active",
        )
        session.add(offer)
        await session.flush()
        first = InventoryItem(offer_id=offer.id, encrypted_payload="one")
        second = InventoryItem(offer_id=offer.id, encrypted_payload="two")
        session.add_all([first, second])
        await session.flush()
        session.add(
            InventoryFingerprint(
                offer_id=offer.id,
                inventory_item_id=first.id,
                fingerprint="same-fingerprint",
            )
        )
        await session.flush()
        session.add(
            InventoryFingerprint(
                offer_id=offer.id,
                inventory_item_id=second.id,
                fingerprint="same-fingerprint",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
    await engine.dispose()


def test_payment_method_ownership_and_duplicate_reference():
    run(_payment_security_scenario())


def test_inventory_fingerprint_database_constraint():
    run(_inventory_fingerprint_scenario())
