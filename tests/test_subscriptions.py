import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, CouponKind, Provider, ProviderCoupon
from app.db.seed import seed_defaults
from app.services.subscriptions import SubscriptionService


def run(coro):
    return asyncio.run(coro)


async def _scenario():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        await seed_defaults(session)
        provider = Provider(
            name_ar="منصة اختبار",
            name_en="Test Provider",
            slug="test-provider",
            status="active",
        )
        session.add(provider)
        await session.flush()
        service = SubscriptionService()
        subscription = await service.ensure_subscription(session, provider)
        assert subscription.plan.code == "free"
        assert await service.feature_enabled(session, provider.id, "reports.basic") is True
        assert await service.feature_enabled(session, provider.id, "reports.advanced") is False

        await service.grant_trial(session, provider, 7, None, plan_code="pro")
        assert await service.feature_enabled(session, provider.id, "reports.advanced") is True
        assert (await service.effective_entitlement(session, provider.id, "offers.max")).limit == -1

        await service.set_feature_override(
            session, provider, "reports.advanced", False, None, reason="test"
        )
        assert await service.feature_enabled(session, provider.id, "reports.advanced") is False

        await service.set_commission_override(session, provider, 0, 7, None)
        assert await service.effective_management_percent(session, provider) == 0

        coupon = ProviderCoupon(
            code="FREE14",
            kind=CouponKind.TRIAL.value,
            value_int=14,
            valid_until=datetime.now(UTC) + timedelta(days=30),
        )
        session.add(coupon)
        await session.flush()
        message = await service.redeem_coupon(session, provider, "free14", None)
        assert "14" in message
        assert coupon.used_count == 1

        custom_plan = await service.create_plan(
            session,
            code="custom-plus",
            name_ar="مخصصة",
            price_iqd=7500,
            billing_days=30,
            grace_days=4,
        )
        assert custom_plan.code == "custom-plus"
        await service.set_plan_feature(session, custom_plan, "reports.advanced", True)
        await service.set_plan_limit(session, custom_plan, "reports.monthly", 8)
        await service.set_feature_override(
            session, provider, "reports.advanced", None, None, reason="inherit"
        )
        await service.assign_plan(session, provider, "custom-plus", None)
        assert await service.feature_enabled(session, provider.id, "reports.advanced") is True
        assert (
            await service.effective_entitlement(session, provider.id, "reports.monthly")
        ).limit == 8

        discount_coupon = ProviderCoupon(
            code="HALF",
            kind=CouponKind.PERCENT_DISCOUNT.value,
            value_int=50,
            valid_until=datetime.now(UTC) + timedelta(days=30),
        )
        session.add(discount_coupon)
        await session.flush()
        await service.redeem_coupon(session, provider, "half", None)
        current = await service.get_subscription(session, provider.id)
        assert current.custom_price_iqd == 3750
        await session.commit()
    await engine.dispose()


def test_subscription_entitlements_and_coupon():
    run(_scenario())
