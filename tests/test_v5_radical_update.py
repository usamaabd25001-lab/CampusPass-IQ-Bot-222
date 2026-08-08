import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import (
    Announcement,
    AnnouncementStatus,
    Category,
    DeliveryType,
    MenuContentType,
    Offer,
    OfferStatus,
    Order,
    OrderStatus,
    Provider,
    ProviderStatus,
    Report,
    Review,
    User,
    UserRole,
)
from tests.v4_helpers import database_bundle, services_bundle


def run(coro):
    return asyncio.run(coro)


async def _announcement_scenario() -> None:
    engine, factory = await database_bundle()
    _settings, bot, _secrets, services = services_bundle()
    async with factory() as session:
        user = User(
            telegram_id=551100,
            telegram_name="طالب",
            role=UserRole.USER.value,
            referral_code="V5-ANN-1",
        )
        session.add(user)
        await session.flush()
        now = datetime.now(UTC)
        first = Announcement(
            title="تحديث أول",
            body="تم تحسين القوائم.",
            target_scope="all",
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(hours=1),
            pin_message=True,
            status=AnnouncementStatus.ACTIVE.value,
        )
        session.add(first)
        await session.flush()

        assert await services.announcements.send_active_for_user(session, user) == 1
        assert len(bot.sent) == 1
        assert len(bot.pinned) == 1
        # Refreshing /start or /menu must not duplicate the campaign.
        assert await services.announcements.send_active_for_user(session, user) == 1
        assert len(bot.sent) == 1

        second = Announcement(
            title="تحديث ثانٍ",
            body="إعلان مثبت جديد.",
            target_scope="students",
            starts_at=now,
            ends_at=now + timedelta(hours=2),
            pin_message=True,
            status=AnnouncementStatus.ACTIVE.value,
        )
        session.add(second)
        await session.flush()
        assert await services.announcements.send_active_for_user(session, user) == 2
        assert len(bot.sent) == 2
        assert bot.unpinned  # New pinned campaign replaces the previous bot pin.
        await session.commit()
    await engine.dispose()


def test_v5_active_announcements_are_delivered_once_and_replace_old_pin():
    run(_announcement_scenario())


async def _custom_menu_scenario() -> None:
    engine, factory = await database_bundle()
    _settings, _bot, _secrets, services = services_bundle()
    async with factory() as session:
        owner = User(
            telegram_id=9001,
            telegram_name="Owner",
            role=UserRole.ADMIN.value,
            referral_code="V5-OWNER",
        )
        session.add(owner)
        await session.flush()
        parent = await services.menus.create_custom_button(
            session,
            key="v5_help_menu",
            text="📂 تعليمات خاصة",
            content_type=MenuContentType.SUBMENU.value,
            roles=[UserRole.USER.value],
            surface="both",
            actor_user_id=owner.id,
        )
        child = await services.menus.create_custom_button(
            session,
            key="v5_help_text",
            text="📝 طريقة التسجيل",
            content_type=MenuContentType.TEXT.value,
            roles=[UserRole.USER.value],
            parent_key=parent.key,
            content_text="افتح الموقع ثم سجل الدخول.",
            surface="inline",
            actor_user_id=owner.id,
        )
        assert (await services.menus.get_button(session, parent.key)).surface == "both"
        assert await services.menus.content(session, child.key)
        with pytest.raises(ValueError):
            await services.menus.delete_custom_button(session, parent.key)
        assert await services.menus.delete_custom_button(session, child.key)
        assert await services.menus.delete_custom_button(session, parent.key)
        await session.commit()
    await engine.dispose()


def test_v5_owner_can_create_nested_buttons_and_delete_them_safely():
    run(_custom_menu_scenario())


async def _ratings_scenario() -> None:
    engine, factory = await database_bundle()
    _settings, _bot, _secrets, services = services_bundle()
    async with factory() as session:
        provider = Provider(
            name_ar="منصة التقييم",
            slug="ratings-provider",
            status=ProviderStatus.ACTIVE.value,
        )
        category = Category(name="اختبار", emoji="🧪")
        user1 = User(
            telegram_id=701,
            telegram_name="طالب 1",
            referral_code="V5-RATE-1",
        )
        user2 = User(
            telegram_id=702,
            telegram_name="طالب 2",
            referral_code="V5-RATE-2",
        )
        session.add_all([provider, category, user1, user2])
        await session.flush()
        offer = Offer(
            provider_id=provider.id,
            category_id=category.id,
            title="اشتراك اختباري",
            price_iqd=10_000,
            service_fee_iqd=500,
            delivery_type=DeliveryType.MANUAL.value,
            status=OfferStatus.ACTIVE.value,
            is_active=True,
        )
        session.add(offer)
        await session.flush()
        orders = []
        for index, user in enumerate((user1, user2), start=1):
            order = Order(
                public_id=f"CP-V5-R-{index}",
                user_id=user.id,
                provider_id=provider.id,
                offer_id=offer.id,
                status=OrderStatus.COMPLETED.value,
                subtotal_iqd=10_000,
                total_iqd=10_500,
            )
            session.add(order)
            orders.append(order)
        await session.flush()
        session.add_all(
            [
                Review(
                    user_id=user1.id,
                    provider_id=provider.id,
                    offer_id=offer.id,
                    order_id=orders[0].id,
                    rating=5,
                ),
                Review(
                    user_id=user2.id,
                    provider_id=provider.id,
                    offer_id=offer.id,
                    order_id=orders[1].id,
                    rating=3,
                ),
            ]
        )
        await session.flush()
        average, count = await services.reviews.provider_summary(session, provider.id)
        assert average == 4.0
        assert count == 2
        assert services.reviews.stars(average) == "⭐⭐⭐⭐☆"
        await session.commit()
    await engine.dispose()


def test_v5_completed_order_reviews_roll_up_to_provider_rating():
    run(_ratings_scenario())


def _report_snapshot() -> dict:
    ranking = [{"name": "جامعة بغداد", "count": 10}]
    return {
        "provider": {
            "id": 1,
            "name_ar": "منصة الاختبار",
            "name_en": "Test Platform",
            "logo_url": "",
            "logo_file_id": None,
        },
        "summary": {
            "orders": 12,
            "sales": 120_000,
            "service_fees": 6_000,
            "management_fees": 3_000,
            "provider_net": 111_000,
            "owner_net": 9_000,
            "completed": 10,
            "refunded": 1,
            "support": 1,
            "rating_average": 4.2,
            "rating_count": 100,
            "withdrawals_paid": 20_000,
            "available_balance": 91_000,
        },
        "statuses": {"completed": 10, "needs_support": 1},
        "top_offers": [{"title": "Microsoft 365", "count": 8, "sales": 80_000}],
        "emails": [],
        "report_meta": {
            "type": "ratings",
            "title": "تقرير التقييمات ورضا الطلاب",
            "tier": "pro",
            "tier_label": "Pro",
        },
        "students": {
            "total": 10,
            "new": 2,
            "top_university": ranking[0],
            "top_college": {"name": "كلية الهندسة", "count": 6},
            "top_department": {"name": "هندسة الحاسوب", "count": 5},
            "top_stage": {"name": "الثالثة", "count": 4},
            "top_governorate": {"name": "بغداد", "count": 7},
        },
        "profile_rankings": {
            "universities": ranking,
            "colleges": [{"name": "كلية الهندسة", "count": 6}],
            "departments": [{"name": "هندسة الحاسوب", "count": 5}],
            "stages": [{"name": "الثالثة", "count": 4}],
            "governorates": [{"name": "بغداد", "count": 7}],
        },
        "trend": [],
        "rating_distribution": {"5": 60, "4": 25, "3": 10, "2": 3, "1": 2},
        "withdrawals": [],
    }


def test_v5_report_renders_as_independent_a4_html_with_both_logos():
    _settings, _bot, _secrets, services = services_bundle()
    now = datetime.now(UTC)
    report = Report(
        id=55,
        provider_id=1,
        report_type="ratings",
        period_start=now - timedelta(days=30),
        period_end=now,
        snapshot=_report_snapshot(),
        plan="pro",
        created_at=now,
        expires_at=now + timedelta(days=7),
    )
    html = services.reports.render(report, "https://example.test/reports/token")
    assert "@page { size: A4 portrait" in html
    assert "تقرير التقييمات ورضا الطلاب" in html
    assert "CampusPass IQ" in html
    assert "مكان شعار المنصة" in html
    assert "من 100 تقييمًا" in html
    assert "تنزيل HTML" in html

async def _price_audit_scenario() -> None:
    from sqlalchemy import select

    from app.db.models import PriceChangeLog

    engine, factory = await database_bundle()
    _settings, _bot, _secrets, services = services_bundle()
    async with factory() as session:
        owner = User(
            telegram_id=9001,
            telegram_name="Owner",
            role=UserRole.ADMIN.value,
            referral_code="V5-PRICE-OWNER",
        )
        session.add(owner)
        await session.flush()
        result = await services.pricing.validate_offer_price(session, "10")
        assert result.suspiciously_low is True
        assert result.suggested_value == 10_000
        await services.pricing.log_price_change(
            session,
            key="provider.1.offer.1.price_iqd",
            old_value=12_000,
            new_value=10_000,
            actor=owner,
            reason="test",
        )
        row = await session.scalar(
            select(PriceChangeLog).where(
                PriceChangeLog.price_key == "provider.1.offer.1.price_iqd"
            )
        )
        assert row is not None
        assert row.old_value_iqd == 12_000
        assert row.new_value_iqd == 10_000
        assert row.actor_user_id == owner.id
        await session.commit()
    await engine.dispose()


def test_v5_low_prices_are_flagged_and_price_changes_are_audited():
    run(_price_audit_scenario())
