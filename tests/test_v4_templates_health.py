import asyncio

from sqlalchemy import select

from app.db.models import MessageTemplate, ModuleRecord
from tests.v4_helpers import database_bundle, services_bundle


def run(coro):
    return asyncio.run(coro)


async def _scenario():
    engine, factory = await database_bundle()
    _settings, _bot, _secrets, services = services_bundle()
    async with factory() as session:
        rendered = await services.templates.render(
            session, "payment.received", {"order_id": "CP-100"}
        )
        assert "CP-100" in rendered

        await services.templates.update(
            session,
            "payment.received",
            "طلبك {order_id} قيد التدقيق — {optional}",
        )
        rendered = await services.templates.render(
            session, "payment.received", {"order_id": "CP-101"}
        )
        assert "CP-101" in rendered
        assert "{optional}" in rendered

        snapshot = await services.health.snapshot(session)
        assert snapshot["database"]["ok"] is True
        assert snapshot["version"]
        assert any(row["key"] == "workflow" for row in snapshot["modules"])
        assert await session.scalar(select(MessageTemplate.id).limit(1))
        assert await session.scalar(select(ModuleRecord.id).limit(1))
        await session.commit()
    await engine.dispose()


def test_v4_templates_and_health_registry():
    run(_scenario())
