from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import payment_methods_keyboard, with_navigation
from app.bot.states import FriendPackageStates, WarrantyClaimStates
from app.bot.ui import callback_notice, edit_or_send
from app.core.config import Settings
from app.core.utils import safe
from app.db.models import (
    FriendGroup,
    FriendGroupMember,
    FriendPackageConfig,
    FriendGroupStatus,
    Offer,
    ProviderInboxItem,
    ProviderInboxItemKind,
    StudentSubscription,
    User,
    WarrantyClaim,
    WarrantyClaimStatus,
    WarrantyPolicy,
)
from app.services.container import Services
from app.services.platform_access import resolve_provider_access

router = Router(name="friends_warranty_v11_3")


def _markup(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return with_navigation(InlineKeyboardMarkup(inline_keyboard=rows))


async def _require_complete_profile(callback: CallbackQuery, services: Services, session: AsyncSession):
    if not callback.from_user:
        return None
    user = await services.users.get_or_create(
        session,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name or "Telegram User",
    )
    complete, _missing = await services.student_commerce.profile_status(user.profile)
    if not complete:
        await callback_notice(
            callback,
            "أكمل معلوماتك أولاً من زر معلوماتي ثم افتح رابط المجموعة مجدداً.",
            show_alert=True,
        )
        return None
    return user


async def render_friend_invitation(
    message: Message,
    *,
    token: str,
    session: AsyncSession,
    services: Services,
) -> None:
    try:
        from app.domain.friend_packages import hash_join_token

        group = await session.scalar(
            select(FriendGroup).where(FriendGroup.join_token_hash == hash_join_token(token))
        )
    except ValueError:
        group = None
    if not group or group.status != FriendGroupStatus.OPEN.value or group.expires_at <= datetime.now(UTC):
        await edit_or_send(message, "رابط باقة الأصدقاء غير صالح أو انتهت مهلته.")
        return
    offer = await session.get(Offer, group.offer_id)
    progress = await services.friend_packages.progress(session, group.id)
    await edit_or_send(
        message,
        "🤝 <b>دعوة إلى حساب الأصدقاء</b>\n\n"
        "صديقك دعاك لمشاركته في حساب الأصدقاء.\n"
        f"الخدمة: <b>{safe(offer.title if offer else 'الخدمة')}</b>\n"
        f"العدد المطلوب: {group.required_members}\n"
        f"دفع حتى الآن: {progress.paid_members}\n"
        f"المتبقي: {progress.remaining_members}\n\n"
        "يجب اكتمال العدد كاملاً قبل إرسال بيانات الحساب للجميع.",
        reply_markup=_markup(
            [[InlineKeyboardButton(text="💳 دفع حصتي", callback_data=f"friend:join:{token}", style="success")]]
        ),
    )


@router.callback_query(F.data.startswith("friend:create:"))
async def friend_create(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.message:
        return
    user = await _require_complete_profile(callback, services, session)
    if not user:
        return
    offer = await services.catalog.get_offer(session, int((callback.data or "").split(":")[2]))
    if not offer:
        await callback_notice(callback, "العرض غير موجود", show_alert=True)
        return
    try:
        result = await services.friend_packages.open_group(
            session, creator=user, offer=offer
        )
    except (ValueError, PermissionError) as exc:
        await callback_notice(callback, str(exc), show_alert=True)
        return
    token = result.join_token
    bot_info = await callback.message.bot.get_me()
    invite_url = (
        f"https://t.me/{bot_info.username}?start=friends_{token}" if token else ""
    )
    methods = await services.orders.payment_methods(session, offer.provider_id)
    progress = await services.friend_packages.progress(session, result.group.id)
    await edit_or_send(
        callback.message,
        "🤝 <b>تم حجز حساب لباقة أصدقائي فقط</b>\n\n"
        f"حصتك من الخدمة: {result.member.service_share_iqd:,} د.ع\n"
        f"رسوم البوت الكاملة: {result.member.bot_fee_iqd:,} د.ع\n"
        f"المطلوب دفعه الآن: <b>{result.member.cash_due_iqd:,} د.ع</b>\n"
        f"الحالة: {progress.status_text}\n"
        f"تنتهي مهلة التجميع: {result.group.expires_at:%Y-%m-%d %H:%M} UTC\n\n"
        + (f"رابط الدعوة:\n<code>{safe(invite_url)}</code>" if invite_url else "افتح المجموعة الحالية لإظهار حالتها."),
        reply_markup=payment_methods_keyboard(methods, result.order.id),
    )


@router.callback_query(F.data.startswith("friend:join:"))
async def friend_join(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.message:
        return
    user = await _require_complete_profile(callback, services, session)
    if not user:
        return
    token = (callback.data or "").split(":", 2)[2]
    try:
        result = await services.friend_packages.join(session, token=token, user=user)
    except (ValueError, PermissionError) as exc:
        await callback_notice(callback, str(exc), show_alert=True)
        return
    methods = await services.orders.payment_methods(session, result.group.provider_id)
    progress = await services.friend_packages.progress(session, result.group.id)
    await edit_or_send(
        callback.message,
        "🤝 <b>تم حجز مقعدك في حساب الأصدقاء</b>\n\n"
        f"حصتك: {result.member.service_share_iqd:,} د.ع\n"
        f"رسوم البوت الكاملة: {result.member.bot_fee_iqd:,} د.ع\n"
        f"الإجمالي المطلوب: <b>{result.member.cash_due_iqd:,} د.ع</b>\n\n"
        f"{progress.status_text}\n"
        "بعد دفعك انتظر اكتمال عدد الأصدقاء، ثم يرسل الحساب تلقائياً للجميع.",
        reply_markup=payment_methods_keyboard(methods, result.order.id),
    )


@router.callback_query(F.data.startswith("friend:progress:"))
async def friend_progress(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    group_id = int((callback.data or "").split(":")[2])
    user = await services.users.get(session, callback.from_user.id)
    member = await session.scalar(
        select(FriendGroupMember).where(
            FriendGroupMember.group_id == group_id,
            FriendGroupMember.user_id == (user.id if user else -1),
        )
    )
    if not member:
        await callback_notice(callback, "أنت لست عضواً في هذه المجموعة", show_alert=True)
        return
    progress = await services.friend_packages.progress(session, group_id)
    await edit_or_send(callback.message, f"🤝 <b>حالة المجموعة</b>\n\n{progress.status_text}")


@router.callback_query(F.data.startswith("provider:friends:"))
async def provider_friend_settings(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    offer_id = int((callback.data or "").split(":")[2])
    offer = await session.get(Offer, offer_id)
    if not offer:
        return
    access = await resolve_provider_access(
        session,
        settings,
        callback.from_user.id,
        provider_id=offer.provider_id,
        permission="can_manage_offers",
        require_terms=True,
    )
    if not access.allowed:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    config = await session.scalar(
        select(FriendPackageConfig).where(FriendPackageConfig.offer_id == offer.id)
    )
    enabled = bool(config and config.is_enabled)
    count = config.required_members if config else 2
    rows = [
        [InlineKeyboardButton(text=f"{'✅' if enabled else '❌'} الحالة الحالية", callback_data="noop")],
        [InlineKeyboardButton(text="2 أصدقاء", callback_data=f"p:fren:{offer.id}:2", style="primary"), InlineKeyboardButton(text="3 أصدقاء", callback_data=f"p:fren:{offer.id}:3", style="primary")],
        [InlineKeyboardButton(text="4 أصدقاء", callback_data=f"p:fren:{offer.id}:4", style="primary"), InlineKeyboardButton(text="5 أصدقاء", callback_data=f"p:fren:{offer.id}:5", style="primary")],
        [InlineKeyboardButton(text="6 أصدقاء", callback_data=f"p:fren:{offer.id}:6", style="primary"), InlineKeyboardButton(text="8 أصدقاء", callback_data=f"p:fren:{offer.id}:8", style="primary")],
        [InlineKeyboardButton(text="🔢 عدد مخصص", callback_data=f"p:frcustom:{offer.id}", style="primary")],
        [InlineKeyboardButton(text="❌ تعطيل الميزة", callback_data=f"p:froff:{offer.id}", style="danger")],
        [InlineKeyboardButton(text="↩️ العرض", callback_data=f"provider:offer_manage:{offer.id}")],
    ]
    await edit_or_send(
        callback.message,
        "🤝 <b>باقة أصدقائي فقط</b>\n\n"
        "الميزة مغلقة افتراضياً. عند تفعيلها يُحجز حساب واحد لمدة 24 ساعة، "
        "ويجب اكتمال العدد كاملاً. كل عضو يدفع رسوم البوت كاملة.\n\n"
        f"الحالة: {'مفعلة' if enabled else 'مغلقة'}\nالعدد الحالي: {count}",
        reply_markup=_markup(rows),
    )


@router.callback_query(F.data.startswith("p:frcustom:"))
async def provider_friend_custom_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    offer = await session.get(Offer, int((callback.data or "").split(":")[2]))
    if not offer:
        return
    access = await resolve_provider_access(
        session, settings, callback.from_user.id, provider_id=offer.provider_id,
        permission="can_manage_offers", require_terms=True,
    )
    if not access.allowed:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    await state.clear()
    await state.update_data(friend_offer_id=offer.id)
    await state.set_state(FriendPackageStates.custom_members)
    await edit_or_send(callback.message, "اكتب عدد الأصدقاء المطلوب من 2 إلى 50.")


@router.message(FriendPackageStates.custom_members)
async def provider_friend_custom_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    if not message.from_user:
        return
    raw = (message.text or "").translate(
        str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    ).strip()
    if not raw.isdigit() or not 2 <= int(raw) <= 50:
        await message.answer("أرسل رقماً صحيحاً من 2 إلى 50.")
        return
    data = await state.get_data()
    offer = await session.get(Offer, int(data.get("friend_offer_id") or 0))
    if not offer:
        await state.clear()
        return
    access = await resolve_provider_access(
        session, settings, message.from_user.id, provider_id=offer.provider_id,
        permission="can_manage_offers", require_terms=True,
    )
    if not access.allowed or not access.actor:
        await state.clear()
        return
    await services.friend_packages.configure(
        session, provider_id=offer.provider_id, offer_id=offer.id,
        actor_user_id=access.actor.user_id, enabled=True, required_members=int(raw),
    )
    await state.clear()
    await message.answer(f"✅ تم تفعيل باقة أصدقائي فقط لعدد {int(raw)} أصدقاء.")


@router.callback_query(F.data.regexp(r"^p:fren:\d+:\d+$"))
async def provider_friend_enable(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user:
        return
    _, _, offer_text, count_text = (callback.data or "").split(":")
    offer = await session.get(Offer, int(offer_text))
    if not offer:
        return
    access = await resolve_provider_access(
        session, settings, callback.from_user.id, provider_id=offer.provider_id,
        permission="can_manage_offers", require_terms=True,
    )
    if not access.allowed or not access.actor:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    await services.friend_packages.configure(
        session,
        provider_id=offer.provider_id,
        offer_id=offer.id,
        actor_user_id=access.actor.user_id,
        enabled=True,
        required_members=int(count_text),
    )
    await callback_notice(callback, "تم تفعيل باقة أصدقائي فقط ✅", show_alert=True)
    if callback.message:
        await edit_or_send(
            callback.message,
            f"✅ تم تفعيل باقة أصدقائي فقط لعدد {int(count_text)} أصدقاء.",
            reply_markup=_markup([[InlineKeyboardButton(
                text="↩️ إعدادات الباقة",
                callback_data=f"provider:friends:{offer.id}",
            )]]),
        )


@router.callback_query(F.data.startswith("p:froff:"))
async def provider_friend_disable(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user:
        return
    offer = await session.get(Offer, int((callback.data or "").split(":")[2]))
    if not offer:
        return
    access = await resolve_provider_access(
        session, settings, callback.from_user.id, provider_id=offer.provider_id,
        permission="can_manage_offers", require_terms=True,
    )
    if not access.allowed or not access.actor:
        return
    await services.friend_packages.configure(
        session,
        provider_id=offer.provider_id,
        offer_id=offer.id,
        actor_user_id=access.actor.user_id,
        enabled=False,
        required_members=2,
    )
    await callback_notice(callback, "تم تعطيل الميزة", show_alert=True)


@router.callback_query(F.data.startswith("provider:warranty:"))
async def provider_warranty_settings(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    offer = await session.get(Offer, int((callback.data or "").split(":")[2]))
    if not offer:
        return
    access = await resolve_provider_access(
        session, settings, callback.from_user.id, provider_id=offer.provider_id,
        permission="can_manage_offers", require_terms=True,
    )
    if not access.allowed:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    policy = await session.scalar(select(WarrantyPolicy).where(WarrantyPolicy.offer_id == offer.id))
    enabled = bool(policy and policy.is_enabled)
    await edit_or_send(
        callback.message,
        "🛡️ <b>ضمان الاشتراك</b>\n\n"
        "عند التفعيل يغطي الضمان كامل مدة الاشتراك، ويظهر زر المطالبة داخل اشتراكاتي فقط.",
        reply_markup=_markup([
            [InlineKeyboardButton(text="✅ تفعيل الضمان", callback_data=f"p:waron:{offer.id}", style="success")],
            [InlineKeyboardButton(text="❌ تعطيل الضمان", callback_data=f"p:waroff:{offer.id}", style="danger")],
            [InlineKeyboardButton(text=f"الحالة: {'مفعل' if enabled else 'غير مفعل'}", callback_data="noop")],
        ]),
    )


@router.callback_query(F.data.regexp(r"^p:war(on|off):\d+$"))
async def provider_warranty_toggle(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user:
        return
    parts = (callback.data or "").split(":")
    enabled = parts[1] == "waron"
    offer = await session.get(Offer, int(parts[2]))
    if not offer:
        return
    access = await resolve_provider_access(
        session, settings, callback.from_user.id, provider_id=offer.provider_id,
        permission="can_manage_offers", require_terms=True,
    )
    if not access.allowed:
        return
    await services.warranties.configure(
        session, provider_id=offer.provider_id, offer_id=offer.id, enabled=enabled
    )
    await callback_notice(callback, "تم تحديث الضمان ✅", show_alert=True)


@router.callback_query(F.data.startswith("warranty:start:"))
async def warranty_start(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    user = await services.users.get(session, callback.from_user.id)
    subscription = await services.student_subscriptions.get_for_user(
        session, int((callback.data or "").split(":")[2]), user
    ) if user else None
    if not user or not subscription:
        return
    eligible = await services.warranties.eligibility(
        session, subscription=subscription, user=user
    )
    if not eligible.allowed:
        await callback_notice(callback, eligible.reason, show_alert=True)
        return
    await edit_or_send(
        callback.message,
        "عزيزي الطالب، نأسف لمواجهتك مشكلة. يرجى تحديد نوع الخلل بدقة:",
        reply_markup=_markup([
            [InlineKeyboardButton(text="🔑 الحساب يطلب كود تحقق", callback_data=f"warranty:type:{subscription.id}:otp", style="primary")],
            [InlineKeyboardButton(text="🚫 تم تسجيل خروجي / الباسورد خطأ", callback_data=f"warranty:type:{subscription.id}:logged_out", style="danger")],
            [InlineKeyboardButton(text="❓ مشكلة أخرى", callback_data=f"warranty:type:{subscription.id}:other", style="primary")],
        ]),
    )


@router.callback_query(F.data.startswith("warranty:type:"))
async def warranty_type(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    parts = (callback.data or "").split(":")
    subscription_id, category = int(parts[2]), parts[3]
    user = await services.users.get(session, callback.from_user.id)
    subscription = await services.student_subscriptions.get_for_user(
        session, subscription_id, user
    ) if user else None
    if not user or not subscription:
        return
    eligible = await services.warranties.eligibility(
        session, subscription=subscription, user=user
    )
    if not eligible.allowed:
        await callback_notice(callback, eligible.reason, show_alert=True)
        return
    await state.clear()
    await state.update_data(warranty_subscription_id=subscription.id, warranty_category=category)
    await state.set_state(WarrantyClaimStates.screenshot)
    await edit_or_send(callback.message, "📸 أرسل لقطة شاشة واضحة للمشكلة.")


@router.message(WarrantyClaimStates.screenshot)
async def warranty_screenshot(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    file_id = message.photo[-1].file_id if message.photo else (
        message.document.file_id if message.document and (message.document.mime_type or "").startswith("image/") else None
    )
    if not file_id:
        await message.answer("أرسل صورة أو ملف صورة فقط.")
        return
    data = await state.get_data()
    user = await services.users.get(session, message.from_user.id)
    subscription = await services.student_subscriptions.get_for_user(
        session, int(data.get("warranty_subscription_id") or 0), user
    ) if user else None
    if not user or not subscription:
        await state.clear()
        return
    try:
        claim = await services.warranties.open_claim(
            session,
            subscription=subscription,
            user=user,
            category=str(data.get("warranty_category") or "other"),
            screenshot_file_id=file_id,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(
        f"تم فتح مطالبة الضمان <code>{claim.public_id}</code> ✅\n"
        "أُرسلت مباشرة إلى بريد المنصة للمعالجة."
    )


@router.callback_query(F.data.startswith("warranty:confirm:"))
async def warranty_confirm(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get(session, callback.from_user.id)
    if not user:
        return
    try:
        await services.warranties.student_confirm_success(
            session, claim_id=int((callback.data or "").split(":")[2]), user=user
        )
    except ValueError as exc:
        await callback_notice(callback, str(exc), show_alert=True)
        return
    await edit_or_send(callback.message, "✅ تم تأكيد نجاح التفعيل وإغلاق مطالبة الضمان.")


@router.callback_query(F.data.startswith("warranty:problem:"))
async def warranty_problem(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get(session, callback.from_user.id)
    if not user:
        return
    try:
        await services.warranties.student_reports_problem(
            session, claim_id=int((callback.data or "").split(":")[2]), user=user,
            note="ما زالت المشكلة مستمرة بعد إجراء المنصة",
        )
    except ValueError as exc:
        await callback_notice(callback, str(exc), show_alert=True)
        return
    await edit_or_send(callback.message, "تمت إعادة المطالبة إلى المنصة للمتابعة.")


@router.callback_query(F.data.startswith("p:warotp:"))
async def provider_warranty_otp(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    claim = await session.get(WarrantyClaim, int((callback.data or "").split(":")[2]))
    if not claim:
        return
    access = await resolve_provider_access(
        session, settings, callback.from_user.id, provider_id=claim.provider_id,
        permission="can_support", require_terms=True,
    )
    if not access.allowed or not access.actor:
        return
    claim = await services.warranties.allow_new_otp(
        session, claim_id=claim.id, provider_id=claim.provider_id,
        actor_user_id=access.actor.user_id,
    )
    student = await session.get(User, claim.user_id)
    if student:
        await services.notifications.send_user(
            session, student, "تمت الموافقة على طلبك",
            "يمكنك سحب الكود الجديد الآن.",
            reply_markup=_markup([[InlineKeyboardButton(text="🔑 سحب الكود الآن", callback_data=f"subscription:code_claim:{claim.id}", style="success")]]),
            idempotency_key=f"warranty:{claim.id}:otp-approved",
        )
    await callback_notice(callback, "تم السماح بسحب كود جديد", show_alert=True)


@router.callback_query(F.data.startswith("p:wartext:"))
async def provider_warranty_text_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    claim = await session.get(WarrantyClaim, int((callback.data or "").split(":")[2]))
    if not claim:
        return
    access = await resolve_provider_access(
        session, settings, callback.from_user.id, provider_id=claim.provider_id,
        permission="can_support", require_terms=True,
    )
    if not access.allowed:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    await state.clear()
    await state.update_data(warranty_provider_claim_id=claim.id)
    await state.set_state(WarrantyClaimStates.note)
    await edit_or_send(callback.message, "اكتب الرد الذي تريد إرساله للطالب.")


@router.message(WarrantyClaimStates.note)
async def provider_warranty_text_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    if not message.from_user:
        return
    note = (message.text or "").strip()
    if len(note) < 2:
        await message.answer("اكتب رداً واضحاً.")
        return
    data = await state.get_data()
    claim = await session.get(WarrantyClaim, int(data.get("warranty_provider_claim_id") or 0))
    if not claim:
        await state.clear()
        return
    access = await resolve_provider_access(
        session, settings, message.from_user.id, provider_id=claim.provider_id,
        permission="can_support", require_terms=True,
    )
    if not access.allowed or not access.actor:
        await state.clear()
        return
    claim = await services.warranties.provider_text_response(
        session, claim_id=claim.id, provider_id=claim.provider_id,
        actor_user_id=access.actor.user_id, note=note,
    )
    student = await session.get(User, claim.user_id)
    if student:
        await services.notifications.send_user(
            session, student, "رد المنصة على مطالبة الضمان", safe(note),
            reply_markup=_markup([
                [InlineKeyboardButton(text="✅ تم حل المشكلة", callback_data=f"warranty:confirm:{claim.id}", style="success")],
                [InlineKeyboardButton(text="❌ ما زالت المشكلة موجودة", callback_data=f"warranty:problem:{claim.id}", style="danger")],
            ]),
            idempotency_key=f"warranty:{claim.id}:provider-text:{claim.updated_at.isoformat() if claim.updated_at else claim.id}",
        )
    await state.clear()
    await message.answer("✅ تم إرسال الرد للطالب، وتبقى المطالبة مفتوحة حتى يؤكد الحل.")


@router.callback_query(F.data.startswith("p:warrep:"))
async def provider_warranty_replacement(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    claim = await session.get(WarrantyClaim, int((callback.data or "").split(":")[2]))
    if not claim:
        return
    access = await resolve_provider_access(
        session, settings, callback.from_user.id, provider_id=claim.provider_id,
        permission="can_manage_inventory", require_terms=True,
    )
    if not access.allowed or not access.actor:
        return
    try:
        claim = await services.warranties.allocate_replacement(
            session, claim_id=claim.id, provider_id=claim.provider_id,
            actor_user_id=access.actor.user_id,
        )
    except ValueError as exc:
        await callback_notice(callback, str(exc), show_alert=True)
        return
    student = await session.get(User, claim.user_id)
    if student:
        await services.notifications.send_user(
            session, student, "تم تفعيل الضمان وتعويضك بحساب جديد",
            "سيصل الحساب البديل عبر مسار التسليم الآمن. لا تُغلق المطالبة حتى تجرب التفعيل.",
            idempotency_key=f"warranty:{claim.id}:replacement-approved",
        )
    await callback_notice(callback, "تم حجز حساب بديل وبدء التسليم", show_alert=True)
