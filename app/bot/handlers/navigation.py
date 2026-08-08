from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.states import (
    AdminOfferStates,
    AdminProviderStates,
    MissingServiceStates,
    PaymentProofStates,
    ProviderCatalogEditStates,
    ProviderOfferStates,
    RegistrationStates,
    SupportStates,
)
from app.bot.keyboards.inline import platform_terms_keyboard, provider_dashboard_keyboard
from app.bot.ui import edit_or_send, send_inline_menu
from app.core.config import Settings
from app.services.container import Services
from app.services.platform_access import (
    ProviderAccessFailure,
    access_failure_message,
    resolve_provider_access,
)

router = Router(name="navigation")

HOME_TEXTS = {"🏠 الرئيسية", "الرئيسية", "القائمة الرئيسية"}
CANCEL_TEXTS = {"❌ إلغاء العملية", "إلغاء", "الغاء", "إلغاء العملية"}
BACK_TEXTS = {"⬅️ رجوع", "↩️ رجوع", "رجوع"}

# Inline buttons do not become message text, but they can still leave an old
# text-entry state active.  These prefixes represent a deliberate jump to a
# different top-level page.  Wizard callbacks (price confirmation, guide steps,
# payment proof, etc.) are intentionally not included.
NAVIGATION_CALLBACK_PREFIXES = (
    "nav:",
    "back_to_main",
    "back_to_platform",
    "menu:open:",
    "store:providers",
    "store:provider:",
    "orders:list",
    "subscriptions:list",
    "subscriptions:categories",
    "tickets:mine",
    "profile:",
    "favorites:list",
    "support:home",
    "provider:select:",
    "provider:home",
    "provider:choose",
    "provider:catalog",
    "provider:inventory",
    "p:cs",
    "p:oa",
    "p:oe",
    "admin:providers",
    "promo:root",
    "promo:provider:",
    "admin:home",
)

# State -> (previous state, prompt). Values remain in FSM data, so returning one
# step does not erase earlier answers.
BACK_MAP: dict[str, tuple[str | None, str]] = {
    RegistrationStates.phone.state: (RegistrationStates.full_name.state, "اكتب اسمك الثلاثي:"),
    RegistrationStates.governorate.state: (RegistrationStates.phone.state, "اكتب رقم هاتفك:"),
    RegistrationStates.university.state: (RegistrationStates.governorate.state, "اكتب المحافظة:"),
    RegistrationStates.college.state: (RegistrationStates.university.state, "اكتب الجامعة أو المعهد:"),
    RegistrationStates.department.state: (RegistrationStates.college.state, "اكتب الكلية:"),
    RegistrationStates.stage.state: (RegistrationStates.department.state, "اكتب القسم أو التخصص:"),
    MissingServiceStates.details.state: (MissingServiceStates.name.state, "اكتب اسم الخدمة:"),
    PaymentProofStates.sender_phone.state: (PaymentProofStates.proof_file.state, "أرسل صورة أو ملف إثبات الدفع:"),
    PaymentProofStates.amount.state: (PaymentProofStates.sender_phone.state, "اكتب رقم هاتف المرسل:"),
    PaymentProofStates.reference.state: (PaymentProofStates.amount.state, "اكتب المبلغ كاملًا بالأرقام:"),
    SupportStates.ticket_message.state: (None, "تم الرجوع إلى مركز المساعدة."),
    ProviderOfferStates.description.state: (ProviderOfferStates.title.state, "اكتب اسم العرض:"),
    ProviderOfferStates.price.state: (ProviderOfferStates.description.state, "اكتب وصف العرض، أو -:"),
    ProviderOfferStates.service_fee.state: (ProviderOfferStates.price.state, "اكتب سعر العرض كاملًا، مثال: 10000:"),
    ProviderOfferStates.promotion_type.state: (ProviderOfferStates.price.state, "اكتب السعر الطبيعي كاملًا، مثال: 10000:"),
    ProviderOfferStates.promotion_price.state: (ProviderOfferStates.promotion_type.state, "اختر اشتراكًا عاديًا أو عرضًا مؤقتًا."),
    ProviderOfferStates.promotion_end.state: (ProviderOfferStates.promotion_price.state, "اكتب سعر العرض بعد الخصم:"),
    ProviderOfferStates.delivery_type.state: (ProviderOfferStates.promotion_type.state, "اختر نوع السعر من جديد."),
    ProviderOfferStates.validity_type.state: (ProviderOfferStates.delivery_type.state, "اختر طريقة التفعيل من جديد."),
    ProviderOfferStates.validity_value.state: (ProviderOfferStates.validity_type.state, "اختر طريقة حساب الصلاحية من جديد."),
    ProviderOfferStates.start_trigger.state: (ProviderOfferStates.validity_type.state, "اختر طريقة حساب الصلاحية من جديد."),
    ProviderOfferStates.daily_limit.state: (ProviderOfferStates.start_trigger.state, "اختر وقت بداية الاشتراك من جديد."),
    ProviderOfferStates.terms.state: (ProviderOfferStates.daily_limit.state, "اكتب الحد اليومي أو -:"),
    ProviderCatalogEditStates.section_name.state: (None, "تم إلغاء تعديل اسم القسم."),
    ProviderCatalogEditStates.service_name.state: (None, "تم إلغاء تعديل اسم الخدمة."),
    ProviderCatalogEditStates.offer_price.state: (None, "تم إلغاء تعديل سعر العرض."),
    ProviderCatalogEditStates.offer_price_confirm.state: (
        ProviderCatalogEditStates.offer_price.state,
        "اكتب سعر العرض من جديد كاملًا، مثال: 10000:",
    ),
    AdminProviderStates.name_en.state: (AdminProviderStates.name_ar.state, "اكتب اسم المنصة بالعربي:"),
    AdminProviderStates.slug.state: (AdminProviderStates.name_en.state, "اكتب اسم المنصة بالإنجليزي أو -:"),
    AdminProviderStates.description.state: (AdminProviderStates.slug.state, "اكتب معرفًا قصيرًا للمنصة:"),
    AdminProviderStates.contact.state: (AdminProviderStates.description.state, "اكتب وصف المنصة:"),
    AdminProviderStates.commission.state: (AdminProviderStates.contact.state, "اكتب وسيلة التواصل:"),
    AdminOfferStates.description.state: (AdminOfferStates.title.state, "اكتب اسم العرض:"),
    AdminOfferStates.price.state: (AdminOfferStates.description.state, "اكتب وصف العرض:"),
    AdminOfferStates.service_fee.state: (AdminOfferStates.price.state, "اكتب السعر كاملًا، مثال: 10000:"),
    AdminOfferStates.delivery_type.state: (AdminOfferStates.price.state, "اكتب السعر كاملًا، مثال: 10000:"),
}


async def _ensure_actor_user(message: Message, services: Services, session: AsyncSession, *, telegram_id: int, username: str | None = None, full_name: str = ""):
    """Self-heal a Telegram actor record instead of asking for /start manually."""

    user = await services.users.get(session, int(telegram_id))
    if user is not None:
        return user
    return await services.users.get_or_create(
        session,
        int(telegram_id),
        username,
        full_name or "Telegram User",
    )


async def _home(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
    *,
    in_place: bool = False,
    telegram_id: int | None = None,
    username: str | None = None,
    full_name: str = "",
) -> Message | None:
    actor_id = telegram_id
    if actor_id is None and message.from_user is not None:
        actor_id = message.from_user.id
        username = message.from_user.username
        full_name = message.from_user.full_name
    if actor_id is None:
        return
    user = await _ensure_actor_user(
        message,
        services,
        session,
        telegram_id=actor_id,
        username=username,
        full_name=full_name,
    )
    from app.bot.handlers.start import send_home

    return await send_home(message, session, services, user, in_place=in_place)


@router.message(Command("menu", "home"))
@router.message(F.text.in_(HOME_TEXTS))
async def go_home(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    rendered = await _home(message, state, session, services)
    if rendered is not None:
        await state.clear()


@router.callback_query(F.data.in_({"back_to_main", "nav:home"}))
async def callback_home(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    """Legacy-compatible Home route; the old screen is deleted only after Home exists."""

    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    rendered = await _home(
        callback.message,
        state,
        session,
        services,
        in_place=True,
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
    )
    if rendered is not None:
        await state.clear()


@router.callback_query(F.data.startswith("nav:back"))
async def callback_back(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    """Move one level up without destroying wizard data."""

    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    current = await state.get_state()
    previous = BACK_MAP.get(str(current)) if current else None
    if previous:
        previous_state, prompt = previous
        if previous_state is None:
            # The current sub-flow ended, but collected data is retained until its
            # parent route is rendered successfully.
            await state.set_state(None)
        else:
            await state.set_state(previous_state)
        await edit_or_send(callback.message, prompt, ensure_navigation=False)
        return

    route = (callback.data or "nav:back").split(":", 2)[2] if (callback.data or "").count(":") >= 2 else ""
    data = await state.get_data()
    route = route or str(data.get("navigation_parent") or "home")
    if route in {"platform", "provider"}:
        # Redispatch is avoided; use the same provider coordinator directly.
        await _render_platform_home(callback, state, session, services, settings, clear_state=False)
        return
    if route == "admin" and settings.is_admin(callback.from_user.id):
        from app.bot.handlers.admin.common import show_admin_home

        await show_admin_home(callback)
        return
    # No parent context means the safe parent is Home, not an error page.
    await _home(
        callback.message,
        state,
        session,
        services,
        in_place=True,
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
    )


async def _render_platform_home(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
    settings: Settings,
    *,
    clear_state: bool,
) -> None:
    if not callback.message or not callback.from_user:
        return
    user = await _ensure_actor_user(
        callback.message,
        services,
        session,
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
    )
    context = await resolve_provider_access(
        session,
        settings,
        callback.from_user.id,
        require_terms=True,
        allow_paused_provider=False,
    )
    if context.failure_reason is ProviderAccessFailure.TERMS_REQUIRED:
        await send_inline_menu(
            callback.message.chat.id,
            "📄 <b>شروط استخدام لوحة المنصة والخصوصية</b>\n\n"
            f"{settings.terms_text}\n\n"
            f"🔐 <b>الخصوصية</b>\n{settings.privacy_text}\n\n"
            "يجب الموافقة مرة واحدة قبل فتح أدوات إدارة المنصة.",
            platform_terms_keyboard(),
            bot=callback.bot,
            source_message=callback.message,
            actor_id=callback.from_user.id,
            ensure_navigation=False,
        )
        if clear_state:
            await state.clear()
        return
    if context.failure_reason is ProviderAccessFailure.SELECTION_REQUIRED:
        from app.bot.keyboards.inline import provider_contexts_keyboard

        await send_inline_menu(
            callback.message.chat.id,
            "لديك أكثر من منصة. اختر المنصة التي تريد إدارتها:",
            provider_contexts_keyboard(context.selectable_memberships),
            bot=callback.bot,
            source_message=callback.message,
            actor_id=callback.from_user.id,
            back_callback="back_to_main",
        )
        if clear_state:
            await state.clear()
        return
    if not context.allowed:
        await edit_or_send(
            callback.message,
            access_failure_message(context),
            back_callback="back_to_main",
        )
        if clear_state:
            await state.clear()
        return
    await send_inline_menu(
        callback.message.chat.id,
        f"🏢 <b>لوحة {context.active_provider.provider_name}</b>",
        provider_dashboard_keyboard(context),
        bot=callback.bot,
        source_message=callback.message,
        actor_id=callback.from_user.id,
        back_callback="back_to_main",
    )
    if clear_state:
        await state.clear()


@router.callback_query(F.data.in_({"back_to_platform", "provider:home"}))
async def callback_platform_home(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    await _render_platform_home(
        callback,
        state,
        session,
        services,
        settings,
        clear_state=(callback.data == "provider:home"),
    )


@router.message(Command("cancel"))
@router.message(F.text.in_(CANCEL_TEXTS))
async def cancel_any(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    current = await state.get_state()
    await state.clear()
    await message.answer("تم إلغاء العملية ✅" if current else "لا توجد عملية معلقة.")
    if message.from_user:
        user = await services.users.get(session, message.from_user.id)
        if user:
            from app.bot.handlers.start import send_home

            await send_home(message, session, services, user)


@router.callback_query(F.data == "nav:cancel")
async def callback_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    await state.clear()
    if not callback.message or not callback.from_user:
        return
    await _home(
        callback.message,
        state,
        session,
        services,
        in_place=True,
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
    )


@router.message(StateFilter("*"), F.text.in_(BACK_TEXTS))
async def go_back(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    current = await state.get_state()
    previous = BACK_MAP.get(str(current))
    if not previous:
        # Outside a data-entry wizard, Back means one safe level up to Home.
        await _home(message, state, session, services)
        return
    previous_state, prompt = previous
    if previous_state is None:
        await state.clear()
    else:
        await state.set_state(previous_state)
    await message.answer(prompt)


# The reply keyboard sends button labels as ordinary text. This guard is placed
# before all state-specific handlers. If the text is a configured menu button,
# the old state is cancelled and the requested section opens instead of being
# stored as an answer to the previous question.
@router.message(StateFilter("*"), F.text, ~F.text.startswith("/"))
async def active_state_menu_interrupt(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not message.from_user:
        return
    user = await services.users.get(session, message.from_user.id)
    if not user:
        return
    role = await services.menus.effective_role(session, user)
    action = await services.menus.resolve_action(
        session, message.text or "", role, user
    )
    if not action:
        # Returning here would consume the update. Re-feed a non-menu input to the
        # current state handler by raising SkipHandler when aiogram is available.
        from aiogram.dispatcher.event.bases import SkipHandler

        raise SkipHandler
    await state.clear()
    from app.bot.handlers.menu import execute_menu_action

    # Silent state handoff: navigation should feel like opening a new section, not an error.
    await execute_menu_action(message, state, session, settings, services, user, action)
