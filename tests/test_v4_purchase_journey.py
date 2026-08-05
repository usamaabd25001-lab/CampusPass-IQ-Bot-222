import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import (
    CatalogSection,
    CatalogServiceItem,
    Category,
    DeliveryJob,
    DeliveryJobStatus,
    DeliveryType,
    InventoryItem,
    InventoryStatus,
    LedgerEntry,
    Offer,
    OfferCatalogPlacement,
    OfferStatus,
    OfferValidityPolicy,
    OrderStatus,
    PaymentMethod,
    Provider,
    ProviderStaff,
    ProviderStatus,
    PurchaseReservation,
    ReceiptSnapshot,
    StudentSubscription,
    StudentSubscriptionStatus,
    SubscriptionStartTrigger,
    User,
    ValidityType,
)
from tests.v4_helpers import database_bundle, services_bundle


def run(coro):
    return asyncio.run(coro)


async def _scenario():
    engine, factory = await database_bundle()
    settings, bot, secrets, services = services_bundle()
    async with factory() as session:
        provider = Provider(
            name_ar="متجر العراق الرقمي",
            name_en="Iraq Digital Store",
            slug="iraq-digital-store",
            status=ProviderStatus.ACTIVE.value,
            management_percent=5,
        )
        category = Category(name="ذكاء اصطناعي V4", emoji="🤖")
        student = User(
            telegram_id=70001,
            telegram_name="اسامة وسام ميثم",
            referral_code="STU-V4-1",
        )
        manager = User(
            telegram_id=9001,
            telegram_name="مدير المنصة",
            role="provider",
            referral_code="MGR-V4-1",
        )
        session.add_all([provider, category, student, manager])
        await session.flush()
        session.add(
            ProviderStaff(
                provider_id=provider.id,
                user_id=manager.id,
                can_review_payments=True,
                can_manage_offers=True,
                can_manage_inventory=True,
            )
        )
        section = CatalogSection(
            provider_id=provider.id,
            name="أدوات الذكاء الاصطناعي",
            emoji="🤖",
        )
        session.add(section)
        await session.flush()
        service_item = CatalogServiceItem(
            provider_id=provider.id,
            section_id=section.id,
            name="Gemini",
            emoji="✨",
        )
        session.add(service_item)
        await session.flush()
        offer = Offer(
            provider_id=provider.id,
            category_id=category.id,
            title="Gemini Advanced — 30 يومًا",
            description="حساب مع تعليمات تفعيل",
            price_iqd=10000,
            service_fee_iqd=500,
            delivery_type=DeliveryType.INVENTORY_ACCOUNT.value,
            status=OfferStatus.ACTIVE.value,
            terms="للاستخدام الشخصي فقط",
        )
        session.add(offer)
        await session.flush()
        session.add(
            OfferCatalogPlacement(
                offer_id=offer.id,
                provider_id=provider.id,
                section_id=section.id,
                service_id=service_item.id,
            )
        )
        session.add(
            OfferValidityPolicy(
                offer_id=offer.id,
                validity_type=ValidityType.DAYS_FROM_ACTIVATION.value,
                duration_value=30,
                start_trigger=SubscriptionStartTrigger.DELIVERY.value,
                warranty_hours=24,
                objection_hours=24,
            )
        )
        method = PaymentMethod(
            provider_id=provider.id,
            name="تحويل إلى بطاقة المنصة",
            method_type="card_transfer",
            recipient="1234 5678 9012 3456",
            instructions="أرسل صورة التحويل وآخر أربعة أرقام",
        )
        session.add(method)
        payload = json.dumps(
            {
                "login_email": "student-account@example.com",
                "login_password": "secret-login-password",
                "instructions": "سجل الدخول ثم أكد نجاح التفعيل.",
                "imap_password": "must-never-be-exposed",
            }
        )
        inventory = InventoryItem(
            offer_id=offer.id,
            item_kind="account",
            label="حساب Gemini",
            encrypted_payload=secrets.encrypt(payload),
            status=InventoryStatus.AVAILABLE.value,
            expires_at=datetime.now(UTC) + timedelta(days=45),
            created_by_user_id=manager.id,
        )
        session.add(inventory)
        await session.flush()

        providers = await services.catalog.providers(session)
        assert providers == [provider]
        sections = await services.catalog.sections(session, provider.id)
        assert section in sections
        catalog_services = await services.catalog.services(session, provider.id, section.id)
        assert service_item in catalog_services
        offers = await services.catalog.offers_for_service(session, provider.id, service_item.id)
        assert offer in offers

        order = await services.orders.create(session, student, offer, {"student_note": "test"})
        await services.orders.set_payment_method(session, order, method)
        reservation = await services.orders.reservation(session, order.id)
        assert reservation and reservation.inventory_item_id == inventory.id
        assert inventory.status == InventoryStatus.RESERVED.value
        assert order.status == OrderStatus.WAITING_PAYMENT.value

        proof = await services.payments.submit_proof(
            session,
            order,
            photo_file_id="telegram-photo-id",
            document_file_id=None,
            sender_phone="07701234567",
            claimed_amount_iqd=10500,
            reference="TX-V4-0001",
            note="دفع يدوي",
        )
        assert proof.order_id == order.id
        assert order.status == OrderStatus.PAYMENT_REVIEW.value

        confirmed_order, payment = await services.payments.confirm(
            session, order.id, manager, is_admin=False
        )
        assert confirmed_order.status == OrderStatus.PAID.value
        assert payment.amount_iqd == 10500

        await services.fulfillment.fulfill(session, confirmed_order)
        job = await session.scalar(
            select(DeliveryJob).where(DeliveryJob.order_id == confirmed_order.id)
        )
        assert job and job.status == DeliveryJobStatus.PENDING.value
        assert confirmed_order.status == OrderStatus.WAITING_FULFILLMENT.value

        processed = await services.fulfillment.process_next_delivery(session)
        assert processed is True
        refreshed = await services.orders.get(session, confirmed_order.id)
        assert refreshed and refreshed.status == OrderStatus.DELIVERED.value
        assert inventory.status == InventoryStatus.DELIVERED.value
        assert any("student-account@example.com" in text for _, text, _ in bot.sent)
        assert not any("must-never-be-exposed" in text for _, text, _ in bot.sent)

        subscription = await session.scalar(
            select(StudentSubscription).where(StudentSubscription.order_id == order.id)
        )
        assert subscription
        assert subscription.status == StudentSubscriptionStatus.ACTIVE.value
        assert subscription.starts_at and subscription.ends_at
        duration = subscription.ends_at - subscription.starts_at
        assert 29 <= duration.days <= 30
        receipt = await session.scalar(
            select(ReceiptSnapshot).where(ReceiptSnapshot.order_id == order.id)
        )
        assert receipt and receipt.snapshot["provider"] == provider.name_ar

        await services.student_subscriptions.activate(session, refreshed)
        await services.finance.finalize_order(session, refreshed, student.id)
        assert refreshed.status == OrderStatus.COMPLETED.value
        ledger_count = int(
            await session.scalar(
                select(func.count())
                .select_from(LedgerEntry)
                .where(LedgerEntry.order_id == order.id)
            )
            or 0
        )
        assert ledger_count >= 2
        assert student.points == 5
        reservation = await session.scalar(
            select(PurchaseReservation).where(PurchaseReservation.order_id == order.id)
        )
        assert reservation and reservation.status == "confirmed"
        await session.commit()
    await engine.dispose()


def test_complete_v4_provider_catalog_payment_delivery_subscription_journey():
    run(_scenario())
