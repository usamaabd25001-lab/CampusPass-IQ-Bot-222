import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.handlers.menu import SUPPORTED_MENU_ACTIONS
from app.core.config import Settings
from app.db.models import Base, Provider, ProviderStaff, User, UserRole
from app.db.seed import DEFAULT_MENU, seed_defaults
from app.services.features import FeatureService
from app.services.menus import MenuService


def run(coro):
    return asyncio.run(coro)


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789",
        ADMIN_IDS="9001",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        ENVIRONMENT="development",
    )


async def _menu_scenario() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await seed_defaults(session)
        user = User(
            telegram_id=100,
            telegram_name="Tester",
            role=UserRole.USER.value,
            referral_code="STU-TEST01",
        )
        admin_user = User(
            telegram_id=9001,
            telegram_name="Owner",
            role=UserRole.ADMIN.value,
            referral_code="STU-ADMIN1",
        )
        provider_user = User(
            telegram_id=200,
            telegram_name="Provider",
            role=UserRole.USER.value,
            referral_code="STU-PROV01",
        )
        provider = Provider(name_ar="منصة", name_en="Provider", slug="provider-test")
        session.add_all([user, admin_user, provider_user, provider])
        await session.flush()
        session.add(ProviderStaff(provider_id=provider.id, user_id=provider_user.id))
        await session.flush()

        menus = MenuService(build_settings(), FeatureService())
        buttons = await menus.list_buttons(session)
        assert len(buttons) == len(DEFAULT_MENU)
        assert all(item.surface == "reply" for item in buttons)

        reply = await menus.reply_keyboard(session, user)
        inline = await menus.inline_keyboard(session, user)
        assert reply is not None
        assert inline is None
        reply_texts = [button.text for row in reply.keyboard for button in row]
        assert "👤 معلوماتي" in reply_texts
        assert "🛡 لوحة الإدارة" not in reply_texts
        assert "🏢 لوحة المنصة" not in reply_texts

        admin_reply = await menus.reply_keyboard(session, admin_user)
        provider_reply = await menus.reply_keyboard(session, provider_user)
        assert admin_reply is not None and provider_reply is not None
        admin_texts = [button.text for row in admin_reply.keyboard for button in row]
        provider_texts = [button.text for row in provider_reply.keyboard for button in row]
        assert "🛡 لوحة الإدارة" in admin_texts
        assert "🏢 لوحة المنصة" in admin_texts
        assert "🏢 لوحة المنصة" in provider_texts
        assert "🛡 لوحة الإدارة" not in provider_texts

        assert await menus.set_surface(session, "profile", "inline") is True
        reply = await menus.reply_keyboard(session, user)
        inline = await menus.inline_keyboard(session, user)
        assert reply is not None and inline is not None
        reply_texts = [button.text for row in reply.keyboard for button in row]
        inline_data = [button.callback_data for row in inline.inline_keyboard for button in row]
        assert "👤 معلوماتي" not in reply_texts
        assert "menu:open:profile" in inline_data
        assert await menus.resolve_action_by_key(session, "profile", "user") == "profile"
        assert await menus.resolve_action(session, "👤 معلوماتي", "user") == "profile"

        assert await menus.set_surface(session, "profile", "both") is True
        assert await menus.resolve_action(session, "👤 معلوماتي", "user") == "profile"
        assert await menus.resolve_action_by_key(session, "profile", "user") == "profile"

        old_text = "🛍 الاشتراكات والخدمات"
        new_text = "🛒 متجر الطالب"
        assert await menus.set_text(session, "services", new_text) is True
        assert await menus.resolve_action(session, new_text, "user") == "services"
        # Old keyboards already shown on users' phones keep working after a rename.
        assert await menus.resolve_action(session, old_text, "user") == "services"
        # Duplicate labels are rejected to avoid ambiguous reply-keyboard routing.
        assert await menus.set_text(session, "profile", new_text) is False

        before = await menus.get_button(session, "orders")
        assert before is not None
        assert await menus.set_position(session, "profile", 9, 2) is True
        moved = await menus.get_button(session, "profile")
        unchanged = await menus.get_button(session, "orders")
        assert moved is not None and (moved.row_number, moved.position) == (9, 2)
        assert unchanged is not None
        assert (unchanged.row_number, unchanged.position) == (
            before.row_number,
            before.position,
        )

        assert await menus.set_style(session, "profile", "danger") is True
        styled = await menus.get_button(session, "profile")
        assert styled is not None and styled.style == "danger"

        assert await menus.set_surface(session, "profile", "hidden") is True
        assert await menus.resolve_action(session, "👤 معلوماتي", "user") is None
        assert await menus.resolve_action_by_key(session, "profile", "user") is None
        assert await menus.set_surface(session, "profile", "both") is True

        assert await menus.set_enabled(session, "help", False) is True
        reply = await menus.reply_keyboard(session, user)
        inline = await menus.inline_keyboard(session, user)
        visible_texts = []
        if reply:
            visible_texts.extend(button.text for row in reply.keyboard for button in row)
        if inline:
            visible_texts.extend(button.text for row in inline.inline_keyboard for button in row)
        assert "💬 مركز المساعدة" not in visible_texts

        changed = await menus.set_all_surfaces(session, "inline")
        assert changed == len(DEFAULT_MENU)
        safety = await menus.reply_keyboard(session, user)
        assert safety is not None
        safety_texts = [button.text for row in safety.keyboard for button in row]
        assert safety_texts == ["🏠 الرئيسية", "❌ إلغاء العملية"]
        assert await menus.inline_keyboard(session, user) is not None

        await session.commit()
    await engine.dispose()


def test_menu_admin_changes_are_isolated_and_backward_compatible():
    run(_menu_scenario())


def test_every_seeded_menu_action_has_a_handler():
    seeded_actions = {row[2] for row in DEFAULT_MENU}
    assert seeded_actions <= SUPPORTED_MENU_ACTIONS
