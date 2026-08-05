from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import (
    admin_dashboard_keyboard,
    back_keyboard,
    provider_contexts_keyboard,
    provider_dashboard_keyboard,
    platform_terms_keyboard,
    promotion_providers_keyboard,
    profile_webapp_keyboard,
    favorites_v11_keyboard,
    providers_keyboard,
    subscription_categories_keyboard,
    support_faq_keyboard,
    user_orders_keyboard,
    with_navigation,
)
from app.bot.states import MissingServiceReplyStates, MissingServiceStates
from app.bot.ui import (
    delete_safely,
    edit_or_send,
    send_inline_menu,
    send_reply_menu,
)
from app.core.config import Settings
from app.core.utils import safe
from app.db.models import (
    MenuContentType,
    MissingServiceRequest,
    OrderCoupon,
    OrderCouponType,
    PointsTransaction,
    ProviderStaff,
    SystemSetting,
    User,
    UserBenefit,
)
from app.services.container import Services
from app.services.platform_access import (
    ProviderAccessFailure,
    access_failure_message,
    resolve_provider_access,
)

router = Router(name="menu")


async def execute_custom_menu_key(
    message: Message,
    session: AsyncSession,
    services: Services,
    user,
    key: str,
    *,
    in_place: bool = False,
) -> None:
    """Render configured menu content without leaving duplicate callback views."""

    async def render(text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        if in_place:
            await edit_or_send(message, text, reply_markup=markup)
        else:
            await send_inline_menu(
                message.chat.id,
                text,
                markup,
                bot=message.bot,
                back_callback="back_to_main",
            )

    content = await services.menus.content(session, key)
    if not content:
        await render("محتوى هذا الزر غير مضبوط بعد.")
        return
    if content.content_type == MenuContentType.SUBMENU.value:
        keyboard = await services.menus.children_keyboard(session, user, key)
        await render(content.text or "اختر من القائمة:", keyboard)
        return
    if content.content_type == MenuContentType.LINK.value and content.url:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="فتح الرابط", url=content.url, style="primary")],
            ]
        )
        await render(content.text or "اضغط لفتح الرابط:", markup)
        return

    text = content.text or ""
    media_markup = with_navigation(None)
    sent: Message | None = None
    if content.content_type == MenuContentType.PHOTO.value and content.telegram_file_id:
        sent = await message.answer_photo(
            content.telegram_file_id,
            caption=text or None,
            reply_markup=ReplyKeyboardRemove(),
        )
    elif content.content_type == MenuContentType.VIDEO.value and content.telegram_file_id:
        sent = await message.answer_video(
            content.telegram_file_id,
            caption=text or None,
            reply_markup=ReplyKeyboardRemove(),
        )
    elif content.content_type == MenuContentType.DOCUMENT.value and content.telegram_file_id:
        sent = await message.answer_document(
            content.telegram_file_id,
            caption=text or None,
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await render(text or "لا يوجد محتوى في هذا الزر.")
        return
    # The final visible media message removes ReplyKeyboard first, then receives
    # its InlineKeyboard. The source is removed only after the destination exists.
    await message.bot.edit_message_reply_markup(
        chat_id=sent.chat.id,
        message_id=sent.message_id,
        reply_markup=media_markup,
    )
    if in_place and sent.message_id != message.message_id:
        await delete_safely(message)

SUPPORTED_MENU_ACTIONS = {
    "services",
    "account",
    "offers",
    "profile",
    "orders",
    "subscriptions",
    "points",
    "earn",
    "hybrid",
    "favorites",
    "missing",
    "help",
    "wallet",
    "admin_dashboard",
    "provider_dashboard",
}


async def show_profile(
    message: Message,
    session: AsyncSession,
    services: Services,
    user,
    *,
    in_place: bool = False,
) -> None:
    async def render(text: str, *, reply_markup: InlineKeyboardMarkup | None = None) -> None:
        if in_place:
            await edit_or_send(message, text, reply_markup=reply_markup)
        else:
            await send_inline_menu(
                message.chat.id,
                text,
                reply_markup,
                bot=message.bot,
                back_callback="back_to_main",
            )

    complete, missing = await services.student_commerce.profile_status(user.profile)
    webapp_url = (services.settings.public_base_url.rstrip("/") + "/webapp/student/profile") if services.settings.public_base_url else ""
    if not user.profile:
        if webapp_url:
            await render(
                "🪪 <b>معلوماتي</b>\n\nأكمل ملفك من النافذة المنظمة داخل Telegram. "
                "لن نطلب البيانات برسائل متفرقة.",
                reply_markup=profile_webapp_keyboard(webapp_url, complete=False),
            )
        else:
            await render(
                "تعذر فتح Web App لأن PUBLIC_BASE_URL غير مضبوط بعد.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(
                        text="📝 إكمال معلوماتي مؤقتاً",
                        callback_data="profile:complete",
                        style="primary",
                    )]]
                ),
            )
        return

    private = services.data_protection.profile_data(user.profile)
    wallet_balance = await services.wallets.balance(session, "user", user.id)
    status_line = "مكتمل ✅" if complete else f"ناقص: {', '.join(missing)}"
    markup = (
        profile_webapp_keyboard(webapp_url, complete=complete)
        if webapp_url
        else InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(
                text="✏️ تعديل معلوماتي مؤقتاً",
                callback_data="profile:edit",
                style="primary",
            )]]
        )
    )
    await render(
        "🪪 <b>معلوماتي</b>\n\n"
        f"الاسم: {safe(private.get('full_name'))}\n"
        f"الهاتف: {safe(private.get('phone'))}\n"
        f"المحافظة: {safe(user.profile.governorate)}\n"
        f"الجامعة: {safe(user.profile.university)}\n"
        f"الكلية: {safe(user.profile.college)}\n"
        f"القسم: {safe(user.profile.department)}\n"
        f"المرحلة: {safe(user.profile.stage)}\n"
        f"حالة الملف: <b>{safe(status_line)}</b>\n"
        f"المحفظة: <b>{wallet_balance:,} د.ع</b>\n"
        f"كود الدعوة: <code>{user.referral_code}</code>",
        reply_markup=markup,
    )


async def show_points(
    message: Message,
    session: AsyncSession,
    services: Services,
    user,
    *,
    in_place: bool = False,
) -> None:
    async def render(text: str, *, reply_markup: InlineKeyboardMarkup | None = None) -> None:
        if in_place:
            await edit_or_send(message, text, reply_markup=reply_markup)
        else:
            await send_inline_menu(
                message.chat.id,
                text,
                reply_markup,
                bot=message.bot,
                back_callback="back_to_main",
            )

    bot_info = await message.bot.get_me()
    username = bot_info.username or ""
    referral_link = f"https://t.me/{username}?start=ref_{user.referral_code}"
    invited_count = int(
        await session.scalar(select(func.count(User.id)).where(User.referred_by_user_id == user.id))
        or 0
    )
    successful_count = int(
        await session.scalar(
            select(func.count(PointsTransaction.id)).where(
                PointsTransaction.user_id == user.id,
                or_(
                    PointsTransaction.idempotency_key.like("referral:success:%"),
                    PointsTransaction.idempotency_key.like("referral:first-order:%:points"),
                ),
            )
        )
        or 0
    )
    reward = await services.status_rewards.summary(session, user)
    wallet_balance = await services.wallets.balance(session, "user", user.id)
    share_url = (
        "https://t.me/share/url?url="
        + quote(referral_link, safe="")
        + "&text="
        + quote("انضم إلى CampusPass IQ من رابط دعوتي", safe="")
    )
    level_labels = {
        "starter": "عضو جديد",
        "active": "عضو نشط",
        "ambassador": "سفير",
        "elite": "نخبة CampusPass",
    }
    await render(
        "🌟 <b>نظام الحالة والمكافآت</b>\n\n"
        f"حالتك الحالية: <b>{level_labels.get(reward.level, reward.level)}</b>\n"
        f"نقاط الحالة: <b>{reward.status_points}</b>\n"
        f"الدعوات المسجلة: <b>{invited_count}</b>\n"
        f"الإحالات التي أكملت شراءً: <b>{max(successful_count, reward.successful_referrals)}</b>\n"
        f"المشتريات الناجحة: <b>{reward.successful_purchases}</b>\n"
        f"مشاركات رابط الحالة: <b>{reward.status_link_shares}</b>\n"
        f"رصيد المحفظة: <b>{wallet_balance:,} د.ع</b>\n\n"
        f"المتبقي للحالة التالية: <b>{reward.next_level_points}</b> نقطة\n\n"
        "ترتفع حالتك تلقائياً عبر الدعوات الناجحة والمشتريات والنشاط المعتمد. "
        "تظهر المكافآت والعروض المتاحة من دون بطاقات إعفاء متراكمة.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(
                text="📤 مشاركة رابط الحالة والدعوة",
                url=share_url,
                style="success",
            )]]
        ),
    )


@router.message(MissingServiceStates.name)
async def missing_name(message: Message, state: FSMContext) -> None:
    value = " ".join((message.text or "").split())
    if len(value) < 3:
        await message.answer("اكتب اسم الخدمة أو المنصة بصورة أوضح.")
        return
    await state.update_data(service_name=value)
    await state.set_state(MissingServiceStates.details)
    await message.answer("اكتب تفاصيل ما تحتاجه، أو اكتب: لا يوجد")


@router.message(MissingServiceStates.details)
async def missing_details(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    user = await services.users.get(session, message.from_user.id)
    if not user:
        return
    data = await state.get_data()
    request = MissingServiceRequest(
        user_id=user.id,
        service_name=str(data.get("service_name") or "")[:255],
        details=(message.text or "").strip()[:6000],
    )
    session.add(request)
    await session.flush()
    request_code = f"MSR-{request.id}"
    profile = user.profile
    student_name = profile.full_name if profile else user.telegram_name
    admin_text = (
        "🧩 <b>طلب خدمة غير موجودة</b>\n\n"
        f"المعرّف: <code>{request_code}</code>\n"
        f"الطالب: {safe(student_name)}\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n"
        f"الخدمة: <b>{safe(request.service_name)}</b>\n"
        f"التفاصيل: {safe(request.details, 'لا توجد')}"
    )
    quick_reply = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="💬 رد سريع على الطالب",
                callback_data=f"missing:reply:{request.id}",
                style="primary",
            )
        ]]
    )
    delivered = 0
    for admin_id in services.settings.admin_ids:
        try:
            await message.bot.send_message(admin_id, admin_text, reply_markup=quick_reply)
            delivered += 1
        except Exception:
            continue
    await state.clear()
    delivery_note = "وتم تنبيه الإدارة فورًا" if delivered else "وسيظهر في لوحة الإدارة"
    await message.answer(
        f"تم تسجيل طلبك ✅ {delivery_note}.\n"
        f"رقم المتابعة: <code>{request_code}</code>"
    )


@router.callback_query(F.data.regexp(r"^missing:reply:\d+$"))
async def missing_service_reply_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    if not settings.is_admin(callback.from_user.id):
        await edit_or_send(callback.message, "غير مصرح.")
        return
    request_id = int((callback.data or "").rsplit(":", 1)[1])
    request = await session.get(MissingServiceRequest, request_id)
    if not request:
        await edit_or_send(callback.message, "طلب الخدمة غير موجود أو حُذف.")
        return
    await state.clear()
    await state.update_data(missing_reply_request_id=request.id)
    await state.set_state(MissingServiceReplyStates.text)
    await edit_or_send(
        callback.message,
        f"اكتب الرد السريع للطالب بخصوص الطلب <code>MSR-{request.id}</code>:",
    )


@router.message(MissingServiceReplyStates.text)
async def missing_service_reply_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not message.from_user or not settings.is_admin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()
    if len(text) < 2:
        await message.answer("اكتب ردًا واضحًا.")
        return
    data = await state.get_data()
    request_id = int(data.get("missing_reply_request_id") or 0)
    request = await session.scalar(
        select(MissingServiceRequest)
        .where(MissingServiceRequest.id == request_id)
        .with_for_update()
    )
    if not request:
        await state.clear()
        await message.answer("طلب الخدمة غير موجود.")
        return
    target = await services.users.get_by_id(session, request.user_id)
    if not target:
        await state.clear()
        await message.answer("حساب الطالب غير موجود.")
        return
    actor = await services.users.get_or_create(
        session,
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
    )
    sent = await services.notifications.send_user(
        session,
        target,
        f"رد الإدارة على طلب MSR-{request.id}",
        safe(text),
        idempotency_key=f"missing-service:{request.id}:reply:{actor.id}",
    )
    request.status = "replied" if sent else "reply_pending"
    request.response_text = text[:6000]
    request.responded_by_user_id = actor.id
    request.responded_at = datetime.now(UTC)
    await session.flush()
    await state.clear()
    await message.answer(
        "تم إرسال الرد إلى الطالب ✅" if sent else "تم حفظ الرد، لكن تعذر إرساله لحظيًا."
    )


async def execute_menu_action(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
    user,
    action: str,
    *,
    in_place: bool = False,
) -> None:
    """Execute a stable menu action independently from button text or placement.

    Every inline-triggered branch uses the same in-place renderer.  This avoids
    the historical split where some actions edited the current menu while
    others appended a new message.
    """

    async def render(text: str, *, reply_markup: InlineKeyboardMarkup | None = None) -> None:
        if in_place:
            await edit_or_send(message, text, reply_markup=reply_markup)
        else:
            await send_inline_menu(
                message.chat.id,
                text,
                reply_markup,
                bot=message.bot,
                back_callback="back_to_main",
            )

    if action == "services":
        complete, _missing = await services.student_commerce.profile_status(user.profile)
        if not complete and services.settings.public_base_url:
            await render(
                "🪪 أكمل معلوماتك أولاً لفتح الاشتراكات والخدمات بصورة منظمة.",
                reply_markup=profile_webapp_keyboard(
                    services.settings.public_base_url.rstrip("/") + "/webapp/student/profile",
                    complete=False,
                ),
            )
            return
        providers = await services.catalog.providers(session)
        await render(
            "اختر المنصة التي تريدها:" if providers else "لا توجد منصات لديها عروض فعالة حاليًا.",
            reply_markup=providers_keyboard(providers) if providers else back_keyboard("back_to_main"),
        )
    elif action == "offers":
        providers = await services.catalog.promotion_providers(session)
        await render(
            "🔥 <b>العروض الطلابية</b>\nاختر منصة لعرض التخفيضات المتاحة فقط:"
            if providers
            else "لا توجد عروض متاحة حالياً",
            reply_markup=(
                InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📦 الباقات المدمجة والهجينة", callback_data="hybrid:list", style="success")],
                    *(promotion_providers_keyboard(providers).inline_keyboard if providers else []),
                ])
                if providers
                else InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📦 الباقات المدمجة والهجينة", callback_data="hybrid:list", style="success")],
                ])
            ),
        )
    elif action == "account":
        complete, _missing = await services.student_commerce.profile_status(user.profile)
        if not complete and services.settings.public_base_url:
            await render(
                "🪪 أكمل معلوماتك أولاً لفتح حسابك ومتابعة الطلبات والاشتراكات.",
                reply_markup=profile_webapp_keyboard(
                    services.settings.public_base_url.rstrip("/") + "/webapp/student/profile",
                    complete=False,
                ),
            )
            return
        wallet_balance = await services.wallets.balance(session, "user", user.id)
        if in_place:
            keyboard = await services.menus.inline_keyboard(session, user, parent_key="account")
            await render(
                "👤 <b>حسابي</b>\n\n"
                f"💰 رصيد المحفظة: <b>{wallet_balance:,} د.ع</b>\n"
                "اختر القسم المطلوب:",
                reply_markup=keyboard,
            )
        else:
            reply_keyboard = await services.menus.reply_keyboard(
                session, user, parent_key="account"
            )
            account_text = (
                "👤 <b>حسابي</b>\n\n"
                f"💰 رصيد المحفظة: <b>{wallet_balance:,} د.ع</b>\n"
                "اختر القسم المطلوب من لوحة الكيبورد بالأسفل."
            )
            if reply_keyboard:
                await send_reply_menu(
                    message,
                    account_text,
                    reply_keyboard,
                    actor_id=int(user.telegram_id),
                )
            else:
                await message.answer(account_text)
    elif action == "profile":
        await show_profile(message, session, services, user, in_place=in_place)
    elif action == "wallet":
        balance = await services.wallets.balance(session, "user", user.id)
        await render(
            "💰 <b>محفظتي</b>\n\n"
            f"الرصيد المتاح: <b>{balance:,} د.ع</b>\n\n"
            "يُحفظ هنا فائض الدفع المؤكد، ويمكن استخدامه في الطلبات القادمة. "
            "لا يُخصم أي مبلغ من المحفظة إلا ضمن عملية شراء موثقة."
        )
    elif action == "orders":
        orders, total = await services.orders.user_orders_page(
            session, user, page=0, page_size=8
        )
        await render(
            f"📦 <b>طلباتي</b> — {total} طلب\nاختر طلبًا لعرض حالته وخطواته:"
            if orders
            else "لا توجد طلبات حتى الآن.",
            reply_markup=user_orders_keyboard(orders, page=0, total=total) if orders else None,
        )
    elif action == "subscriptions":
        complete, _missing = await services.student_commerce.profile_status(user.profile)
        if not complete and services.settings.public_base_url:
            await render(
                "🪪 أكمل معلوماتك أولاً لفتح اشتراكاتك وضمان ربطها بحسابك.",
                reply_markup=profile_webapp_keyboard(
                    services.settings.public_base_url.rstrip("/") + "/webapp/student/profile",
                    complete=False,
                ),
            )
            return
        counts = await services.student_subscriptions.user_subscription_counts(session, user)
        await render(
            "📅 <b>اشتراكاتي</b>\nاختر القسم:"
            if counts.get("all")
            else "لا توجد اشتراكات محفوظة حتى الآن.",
            reply_markup=subscription_categories_keyboard(counts) if counts.get("all") else None,
        )
    elif action == "points":
        await show_points(message, session, services, user, in_place=in_place)
    elif action == "earn":
        if not await services.features.enabled(session, "reward_tasks", default=False):
            await render("نظام المهام والمكافآت غير متاح حالياً.")
            return
        from app.db.models import RewardTaskCampaign, RewardTaskCompletion, RewardTaskStatus
        completed = set((await session.scalars(
            select(RewardTaskCompletion.campaign_id).where(RewardTaskCompletion.user_id == user.id)
        )).all())
        campaigns = list((await session.scalars(
            select(RewardTaskCampaign).where(RewardTaskCampaign.status == RewardTaskStatus.ACTIVE.value)
            .order_by(RewardTaskCampaign.id)
        )).all())
        rows = [[InlineKeyboardButton(
            text=f"💰 {campaign.reward_iqd:,} د.ع • {campaign.title[:25]}",
            callback_data=f"reward:task:{campaign.id}", style="success"
        )] for campaign in campaigns if campaign.id not in completed]
        await render(
            "💰 <b>اكسب رصيداً مجانياً</b>\n\nنفذ مهمة موثوقة ثم تحقق منها:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
    elif action == "hybrid":
        await render(
            "📦 <b>الباقات المدمجة والهجينة</b>\nاختر لعرض الباقات المتاحة:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="فتح الباقات", callback_data="hybrid:list", style="success")
            ]]),
        )
    elif action == "favorites":
        favorites = await services.student_commerce.favorites(session, user=user)
        total_favorites = sum(len(items) for items in favorites.values())
        await render(
            f"❤️ <b>مفضلاتي</b> — {total_favorites} عنصر\n"
            "تضم المنصات والأقسام والعروض التي حفظتها.",
            reply_markup=favorites_v11_keyboard(favorites),
        )
    elif action == "missing":
        await state.set_state(MissingServiceStates.name)
        await render("اكتب اسم الخدمة أو المنصة التي لم تجدها:")
    elif action == "help":
        faqs = await services.support.faqs(session)
        await render(settings.support_text, reply_markup=support_faq_keyboard(faqs))
    elif action == "admin_dashboard":
        if not settings.is_admin(int(user.telegram_id)):
            await render("غير مصرح.")
            return
        await render("🛡 <b>لوحة الإدارة</b>", reply_markup=admin_dashboard_keyboard())
    elif action == "provider_dashboard":
        telegram_id = int(user.telegram_id)
        context = await resolve_provider_access(
            session,
            settings,
            telegram_id,
            require_terms=True,
            allow_paused_provider=False,
        )
        if context.failure_reason is ProviderAccessFailure.TERMS_REQUIRED:
            terms_text = (
                "📄 <b>شروط استخدام لوحة المنصة والخصوصية</b>\n\n"
                f"{settings.terms_text}\n\n"
                f"🔐 <b>الخصوصية</b>\n{settings.privacy_text}\n\n"
                "يجب الموافقة مرة واحدة قبل فتح أدوات إدارة المنصة."
            )
            if in_place:
                await edit_or_send(
                    message,
                    terms_text,
                    reply_markup=platform_terms_keyboard(),
                    ensure_navigation=False,
                )
            else:
                await send_inline_menu(
                    message.chat.id,
                    terms_text,
                    platform_terms_keyboard(),
                    bot=message.bot,
                    actor_id=telegram_id,
                    ensure_navigation=False,
                )
            return
        if context.failure_reason is ProviderAccessFailure.SELECTION_REQUIRED:
            await render(
                "لديك أكثر من منصة. اختر المنصة التي تريد إدارتها:",
                reply_markup=provider_contexts_keyboard(context.selectable_memberships),
            )
            return
        if not context.allowed or context.active_provider is None:
            await render(access_failure_message(context))
            return
        await state.update_data(
            navigation_parent="platform",
            active_provider_id=context.active_provider.provider_id,
        )
        await render(
            f"🏢 <b>لوحة {safe(context.active_provider.provider_name)}</b>",
            reply_markup=provider_dashboard_keyboard(context),
        )
    else:
        await render("هذه الوظيفة غير متاحة في الإصدار الحالي.")


@router.callback_query(F.data.startswith("announcement:open:"))
async def announcement_internal_action_handler(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    """Open a supported bot section directly from an announcement button.

    Clearing the FSM first prevents the announcement click from being captured as
    an answer to an older form such as support, registration, or offer creation.
    """
    await callback.answer()
    await state.clear()
    if not callback.message or not callback.from_user:
        return
    user = await services.users.get_or_create(
        session,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name or "Telegram User",
    )
    action = (callback.data or "").split(":", 2)[2]
    if action not in SUPPORTED_MENU_ACTIONS or action in {"admin_dashboard", "provider_dashboard", "missing"}:
        await edit_or_send(callback.message, "هذا القسم غير متاح من الإعلان.")
        return
    await execute_menu_action(
        callback.message,
        state,
        session,
        settings,
        services,
        user,
        action,
        in_place=True,
    )


@router.callback_query(F.data.startswith("menu:open:"))
async def dynamic_inline_menu_handler(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    await state.clear()
    if not callback.message or not callback.from_user:
        return
    user = await services.users.get_or_create(
        session,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name or "Telegram User",
    )
    role = await services.menus.effective_role(session, user)
    token = (callback.data or "").split(":", 2)[2]
    item = await services.menus.resolve_button_token(session, token)
    key = item.key if item else ""
    action = (
        await services.menus.resolve_action_by_key(session, key, role, user)
        if key
        else None
    )
    if not action:
        await edit_or_send(callback.message, "هذا الزر غير متاح أو تم تغيير نوعه.")
        return
    if action == "custom_content":
        await execute_custom_menu_key(
            callback.message, session, services, user, key, in_place=True
        )
        return
    await execute_menu_action(
        callback.message,
        state,
        session,
        settings,
        services,
        user,
        action,
        in_place=True,
    )


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def dynamic_menu_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not message.from_user or (message.text or "").startswith("/"):
        return
    user = await services.users.get(session, message.from_user.id)
    if not user:
        return
    role = await services.menus.effective_role(session, user)
    action = await services.menus.resolve_action(
        session, message.text or "", role, user
    )
    if not action:
        return
    if action == "custom_content":
        button = await services.menus.get_button_by_text(session, message.text or "")
        if button:
            await execute_custom_menu_key(message, session, services, user, button.key)
        return
    await execute_menu_action(message, state, session, settings, services, user, action)
