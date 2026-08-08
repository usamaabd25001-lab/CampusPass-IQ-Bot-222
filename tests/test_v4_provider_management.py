import asyncio

from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select

from app.bot.handlers import build_router, provider_catalog
from app.bot.keyboards.inline import provider_dashboard_keyboard
from app.db.models import (
    CatalogSection,
    CatalogServiceItem,
    Category,
    DeliveryType,
    Offer,
    OfferCatalogPlacement,
    OfferStatus,
    OfferValidityPolicy,
    PaymentMethod,
    Provider,
    ProviderStatus,
    SubscriptionStartTrigger,
    ValidityType,
)
from tests.v4_helpers import database_bundle, services_bundle


def run(coro):
    return asyncio.run(coro)


def _callbacks(markup: InlineKeyboardMarkup) -> set[str]:
    return {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    }


def test_provider_dashboard_exposes_v4_management_modules():
    callbacks = _callbacks(provider_dashboard_keyboard())
    assert {
        "provider:catalog",
        "provider:inventory",
        "provider:payment_methods",
    } <= callbacks
    assert all(len(value.encode("utf-8")) <= 64 for value in callbacks)
    assert provider_catalog.router is not None
    assert build_router() is not None


async def _provider_catalog_records_are_data_driven():
    engine, factory = await database_bundle()
    _settings, _bot, _secrets, services = services_bundle()
    async with factory() as session:
        provider = Provider(
            name_ar="منصة الإدارة الذاتية",
            slug="provider-self-management",
            status=ProviderStatus.ACTIVE.value,
        )
        category = Category(name="فئة الإدارة الذاتية", emoji="🛍")
        session.add_all([provider, category])
        await session.flush()
        section = CatalogSection(provider_id=provider.id, name="أدوات الذكاء الاصطناعي", emoji="🤖")
        session.add(section)
        await session.flush()
        service = CatalogServiceItem(
            provider_id=provider.id, section_id=section.id, name="Gemini", emoji="✨"
        )
        session.add(service)
        await session.flush()
        offer = Offer(
            provider_id=provider.id,
            category_id=category.id,
            title="Gemini شهر",
            price_iqd=10000,
            service_fee_iqd=500,
            delivery_type=DeliveryType.INVENTORY_ACCOUNT.value,
            status=OfferStatus.ACTIVE.value,
            is_active=True,
        )
        session.add(offer)
        await session.flush()
        session.add_all(
            [
                OfferCatalogPlacement(
                    offer_id=offer.id,
                    provider_id=provider.id,
                    section_id=section.id,
                    service_id=service.id,
                ),
                OfferValidityPolicy(
                    offer_id=offer.id,
                    validity_type=ValidityType.MONTHS_FROM_ACTIVATION.value,
                    duration_value=1,
                    start_trigger=SubscriptionStartTrigger.USER_ACTIVATED.value,
                ),
                PaymentMethod(
                    provider_id=provider.id,
                    name="تحويل إلى بطاقة المنصة",
                    method_type="card_transfer",
                    recipient="1234 5678 9012 3456",
                    instructions="أرسل صورة التحويل ورقم العملية",
                ),
            ]
        )
        await session.flush()
        assert await services.catalog.providers(session) == [provider]
        assert await services.catalog.sections(session, provider.id) == [section]
        assert await services.catalog.services(session, provider.id, section.id) == [service]
        assert await services.catalog.offers_for_service(session, provider.id, service.id) == [
            offer
        ]
        policy = await session.scalar(
            select(OfferValidityPolicy).where(OfferValidityPolicy.offer_id == offer.id)
        )
        assert policy and policy.duration_value == 1
        await session.commit()
    await engine.dispose()


def test_provider_can_own_catalog_offer_validity_and_payment_records():
    run(_provider_catalog_records_are_data_driven())
