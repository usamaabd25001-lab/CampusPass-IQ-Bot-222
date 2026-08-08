from __future__ import annotations

from pathlib import Path

from app.core.emoji import smart_emoji

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_smart_emoji_mapper_is_deterministic_and_bilingual() -> None:
    assert smart_emoji("Netflix Premium") == "🎬"
    assert smart_emoji("تصميم منشورات Canva") == "🎨"
    assert smart_emoji("خدمات طبية للطلاب") == "🩺"
    assert smart_emoji("أدوات الذكاء الاصطناعي") == "🤖"
    assert smart_emoji("خدمة جديدة غير مصنفة") == "✨"


def test_manual_emoji_steps_are_retired_without_breaking_old_sessions() -> None:
    provider = read("app/bot/handlers/provider_catalog.py")
    admin = read("app/bot/handlers/admin/catalog.py")
    combined = provider + admin
    assert "أرسل إيموجي القسم" not in combined
    assert "أرسل إيموجي الخدمة" not in combined
    assert "أرسل إيموجي الفئة" not in combined
    assert "smart_emoji(value)" in combined
    assert "section_finish_legacy" in provider
    assert "service_finish_legacy" in provider
    assert "catalog_section_finish_legacy" in admin
    assert "catalog_service_finish_legacy" in admin


def test_stale_fsm_callbacks_do_not_replace_current_view() -> None:
    provider = read("app/bot/handlers/provider_catalog.py")
    middleware = read("app/bot/middleware.py")
    assert "Ignored stale provider wizard callback" in provider
    assert "انتهت هذه الخطوة أو تغيرت العملية" not in provider
    assert "Leave state transitions to the destination handlers" in middleware
    assert "BACK_MAP" in read("app/bot/handlers/navigation.py")


def test_student_offers_show_only_promotion_providers_and_reuse_buy_flow() -> None:
    catalog_service = read("app/services/catalog.py")
    menu = read("app/bot/handlers/menu.py")
    catalog_handler = read("app/bot/handlers/catalog.py")
    keyboards = read("app/bot/keyboards/inline.py")
    assert "async def promotion_providers" in catalog_service
    assert "async def promotion_offers" in catalog_service
    assert "self._sellable_stock_condition(now)" in catalog_service
    assert "لا توجد عروض متاحة حالياً" in menu
    assert "promotion_providers_keyboard(providers)" in menu
    assert 'callback_data=f"offer:{offer.id}:promo:{provider_id}"' in keyboards
    assert 'text="🛒 اشترك الآن", callback_data=f"buy:{offer_id}"' in keyboards
    assert "@router.callback_query(F.data.startswith(\"buy:\"))" in catalog_handler
    assert "@router.callback_query(F.data.startswith(\"promo:provider:\"))" in catalog_handler


def test_in_place_renderer_preserves_source_until_replacement_exists() -> None:
    ui = read("app/bot/ui.py")
    block = ui[ui.index("async def edit_or_send"):ui.index("async def callback_notice")]
    replacement_index = block.index("replacement = await message.answer")
    delete_index = block.index("await delete_safely(message)")
    assert replacement_index < delete_index
