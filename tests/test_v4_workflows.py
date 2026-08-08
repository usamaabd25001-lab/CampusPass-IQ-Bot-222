import asyncio

import pytest
from sqlalchemy import select

from app.db.models import (
    Category,
    DeliveryType,
    Offer,
    OfferStatus,
    OfferWorkflow,
    Order,
    OrderStatus,
    Provider,
    ProviderStatus,
    User,
)
from app.services.workflows import WORKFLOW_VERSION, WorkflowService
from tests.v4_helpers import database_bundle


def run(coro):
    return asyncio.run(coro)


async def _scenario():
    engine, factory = await database_bundle()
    async with factory() as session:
        category = Category(name="قسم سير العمل", emoji="🧪")
        provider = Provider(
            name_ar="منصة سير العمل",
            name_en="Workflow",
            slug="workflow-provider",
            status=ProviderStatus.ACTIVE.value,
        )
        user = User(
            telegram_id=1101,
            telegram_name="طالب",
            referral_code="WF-USER",
        )
        session.add_all([category, provider, user])
        await session.flush()
        offer = Offer(
            provider_id=provider.id,
            category_id=category.id,
            title="حساب تجريبي",
            price_iqd=10000,
            service_fee_iqd=500,
            delivery_type=DeliveryType.INVENTORY_ACCOUNT.value,
            status=OfferStatus.ACTIVE.value,
        )
        session.add(offer)
        await session.flush()
        order = Order(
            public_id="CP-WORKFLOW",
            user_id=user.id,
            provider_id=provider.id,
            offer_id=offer.id,
            status=OrderStatus.WAITING_PAYMENT.value,
        )
        session.add(order)
        await session.flush()

        service = WorkflowService()
        workflow = await service.ensure_offer(session, offer)
        state = await service.ensure_order(session, order)
        assert workflow.version == WORKFLOW_VERSION
        assert state.current_status == OrderStatus.WAITING_PAYMENT.value

        with pytest.raises(ValueError, match="انتقال حالة غير مسموح"):
            await service.assert_transition(session, order, OrderStatus.COMPLETED.value)

        # Simulate an old workflow left in the database by a previous V4 build.
        workflow.version = 1
        workflow.allowed_transitions = {}
        await session.flush()
        refreshed = await service.ensure_offer(session, offer)
        assert refreshed.version == WORKFLOW_VERSION
        assert (
            OrderStatus.PAYMENT_REVIEW.value
            in refreshed.allowed_transitions[OrderStatus.WAITING_PAYMENT.value]
        )

        order.status = OrderStatus.PAYMENT_REVIEW.value
        await service.record_transition(session, order, order.status)
        state = await service.ensure_order(session, order)
        assert state.workflow_version == WORKFLOW_VERSION
        assert state.current_step_key == "review"
        timeline = await service.timeline(session, order)
        assert any(step["current"] and step["status"] == order.status for step in timeline)

        stored = await session.scalar(
            select(OfferWorkflow).where(OfferWorkflow.offer_id == offer.id)
        )
        assert stored is workflow
        await session.commit()
    await engine.dispose()


def test_v4_workflow_transitions_and_refresh():
    run(_scenario())
