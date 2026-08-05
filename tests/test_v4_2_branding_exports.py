import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.api.server import build_api
from app.core.context import AppContext
from app.core.database import Database
from app.core.security import SecretBox
from app.db.migrations import run_migrations
from app.db.models import (
    Category,
    EmailAccount,
    Offer,
    Order,
    OrderStatus,
    Provider,
    ProviderStatus,
    User,
)
from app.db.seed import seed_defaults
from app.services.container import Services
from tests.v4_helpers import FakeBot, settings


def run(coro):
    return asyncio.run(coro)


async def _prepare_report_context(context: AppContext) -> str:
    await context.database.create_tables()
    async with context.database.session_factory() as session:
        await run_migrations(session)
        await seed_defaults(session)
        provider = Provider(
            name_ar="منصة التقارير المميزة",
            name_en="Branded Reports",
            slug="branded-reports",
            status=ProviderStatus.ACTIVE.value,
        )
        category = Category(name="تقارير")
        user = User(telegram_id=53101, telegram_name="طالب تقارير", referral_code="REP-V42")
        session.add_all([provider, category, user])
        await session.flush()
        offer = Offer(
            provider_id=provider.id,
            category_id=category.id,
            title="اشتراك Office",
            price_iqd=5000,
            service_fee_iqd=500,
            status="active",
            delivery_type="manual",
        )
        session.add(offer)
        await session.flush()
        session.add_all(
            [
                Order(
                    public_id="CP-BRAND-1",
                    user_id=user.id,
                    provider_id=provider.id,
                    offer_id=offer.id,
                    status=OrderStatus.COMPLETED.value,
                    subtotal_iqd=5000,
                    service_fee_iqd=500,
                    management_fee_iqd=250,
                    provider_net_iqd=4750,
                    owner_net_iqd=750,
                    total_iqd=5500,
                ),
                EmailAccount(
                    provider_id=provider.id,
                    label="Hotmail 1",
                    email_provider="hotmail",
                    imap_host="outlook.office365.com",
                    username="campuspass_reports@hotmail.com",
                    encrypted_secret="x",
                    daily_limit=10,
                    used_today=2,
                    status="active",
                ),
            ]
        )
        await session.flush()
        report, token = await context.services.reports.create_provider_report(
            session,
            provider,
            datetime.now(UTC) - timedelta(days=7),
            datetime.now(UTC),
            user.id,
        )
        await session.commit()
        assert report.id
        return token


async def _prepare_render_context():
    config = settings(PUBLIC_BASE_URL="https://campuspass.example")
    database = Database(config)
    bot = FakeBot()
    secrets = SecretBox(config)
    services = Services(bot, config, secrets)
    context = AppContext(config, database, secrets, services, bot)
    token = await _prepare_report_context(context)
    return context, token


def test_report_template_uses_branding_and_download_endpoints(tmp_path):
    config = settings(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'branding.db'}",
        PUBLIC_BASE_URL="https://campuspass.example",
        API_ADMIN_TOKEN="a" * 40,
    )
    database = Database(config)
    bot = FakeBot()
    secrets = SecretBox(config)
    services = Services(bot, config, secrets)
    context = AppContext(config, database, secrets, services, bot)
    token = run(_prepare_report_context(context))

    with TestClient(build_api(context)) as client:
        html_response = client.get(f"/reports/{token}")
        assert html_response.status_code == 200
        assert "مكان شعار المنصة" in html_response.text
        assert "CampusPass IQ" in html_response.text
        assert "تنزيل CSV" in html_response.text
        assert "data:image/png;base64" in html_response.text

        downloadable = client.get(f"/reports/{token}/download/html")
        assert downloadable.status_code == 200
        assert "attachment; filename=" in downloadable.headers["content-disposition"]
        assert "CampusPass IQ" in downloadable.text

        csv_response = client.get(f"/reports/{token}/download/csv")
        assert csv_response.status_code == 200
        assert "attachment; filename=" in csv_response.headers["content-disposition"]
        assert "CampusPass IQ,Operational & Financial Report" in csv_response.text
        assert "ca***s@hotmail.com" in csv_response.text

    run(database.close())


def test_report_service_export_csv_and_report_links():
    context, token = run(_prepare_render_context())

    async def scenario() -> None:
        async with context.database.session_factory() as session:
            report = await context.services.reports.resolve_report(session, token)
            assert report is not None
            verification_url = context.services.reports.report_url(token)
            rendered = context.services.reports.render(report, verification_url=verification_url)
            csv_payload = context.services.reports.export_csv(report)
            await session.commit()
            assert context.services.reports.report_download_url(token, "csv").endswith(
                "/download/csv"
            )
            assert "Access. Services. Success." in rendered
            assert "مكان شعار المنصة" in rendered
            assert "Provider" in csv_payload
            assert "Branded Reports" in csv_payload

    run(scenario())
    run(context.database.close())
