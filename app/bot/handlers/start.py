from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import terms_keyboard
from app.bot.states import RegistrationStates
from app.bot.ui import (
    callback_notice,
    edit_or_send,
    send_inline_menu,
    send_reply_menu,
)
from app.core.config import Settings
from app.core.utils import normalize_phone, validate_full_name
from app.db.models import SystemSetting
from app.services.container import Services

router = Router(name="start")
logger = logging.getLogger(__name__)


async def send_home(
    message: Message,
    session: AsyncSession,
    services: Services,
    user,
    *,
    in_place: bool = False,
    intro_text: str | None = None,
) -> Message | None:
    """Render one deterministic main menu.

    The visible Home message owns the persistent ReplyKeyboard.  Inline-only
    presentation is used only when no ReplyKeyboard is configured, so Telegram
    clients never show competing main-menu surfaces.
    """

    reply_keyboard = await services.menus.reply_keyboard(
        session, user, include_inline_surfaces=True
    )
    inline_keyboard = None if reply_keyboard else await services.menus.inline_keyboard(session, user)
    title = "🏠 <b>القائمة الرئيسية</b>"
    home_text = f"{intro_text.strip()}\n\n{title}" if intro_text and intro_text.strip() else title
    rendered_message: Message | None = None

    if reply_keyboard is not None:
        text = f"{home_text}\nاستخدم الأزرار في الكيبورد السفلي."
        if in_place:
            rendered_message = await send_reply_menu(
                message,
                text,
                reply_keyboard,
                source_message=message,
                actor_id=int(user.telegram_id),
            )
        else:
            rendered_message = await message.answer(text, reply_markup=reply_keyboard)
    elif inline_keyboard is not None:
        if in_place:
            rendered_message = await edit_or_send(
                message,
                home_text,
                reply_markup=inline_keyboard,
                ensure_navigation=False,
            )
        else:
            rendered_message = await send_inline_menu(
                message.chat.id,
                home_text,
                inline_keyboard,
                bot=message.bot,
                actor_id=int(user.telegram_id),
                ensure_navigation=False,
            )
    elif in_place:
        rendered_message = await edit_or_send(
            message, "لا توجد أزرار مفعلة حاليًا.", ensure_navigation=False
        )
    else:
        rendered_message = await message.answer("لا توجد أزرار مفعلة حاليًا.")

    try:
        await services.announcements.send_active_for_user(session, user)
    except Exception as exc:
        logger.warning("Could not deliver active announcements: %s", type(exc).__name__)
    return rendered_message


@router.message(CommandStart())
async def start_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await state.clear()
    if not message.from_user:
        return
    args = (message.text or "").split(maxsplit=1)
    start_ref = args[1].strip() if len(args) == 2 else None
    friend_token = (
        start_ref[len("friends_") :]
        if start_ref and start_ref.startswith("friends_")
        else None
    )
    if friend_token:
        await state.update_data(pending_friend_token=friend_token)
    user = await services.users.get_or_create(
        session,
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
        start_ref,
    )
    welcome_text = await services.templates.welcome_text(session, settings.welcome_text)
    if settings.maintenance_mode and not settings.is_admin(message.from_user.id):
        await message.answer("🔧 البوت في وضع الصيانة مؤقتًا. حاول لاحقًا.")
        return
    if user.terms_accepted_at is None:
        text = f"{welcome_text}\n\nقبل التسجيل، راجع الشروط والخصوصية."
        if settings.welcome_photo:
            try:
                photo_message = await message.answer_photo(
                    settings.welcome_photo,
                    caption=text,
                    reply_markup=ReplyKeyboardRemove(),
                )
                await message.bot.edit_message_reply_markup(
                    chat_id=photo_message.chat.id,
                    message_id=photo_message.message_id,
                    reply_markup=terms_keyboard(),
                )
                return
            except Exception as exc:
                logger.warning("Welcome photo failed: %s", exc)
        await send_inline_menu(
            message.chat.id,
            text,
            terms_keyboard(),
            bot=message.bot,
            ensure_navigation=False,
        )
        return
    if friend_token:
        from app.bot.handlers.friends_warranty import render_friend_invitation

        await render_friend_invitation(
            message, token=friend_token, session=session, services=services
        )
        return
    if not user.profile:
        await send_home(
            message,
            session,
            services,
            user,
            intro_text=(
                welcome_text
                + "\n\n👋 يمكنك دخول القائمة الرئيسية مباشرة. عند فتح الاشتراكات أو حسابك "
                "سيطلب منك البوت إكمال ملف الطالب المنظم داخل Web App مرة واحدة."
            ),
        )
        return
    await send_home(
        message,
        session,
        services,
        user,
        intro_text=welcome_text,
    )


@router.callback_query(F.data == "terms:view")
async def terms_view(callback: CallbackQuery, settings: Settings) -> None:
    await callback.answer()
    if callback.message:
        await edit_or_send(
            callback.message,
            f"📄 <b>شروط الاستخدام</b>\n{settings.terms_text}\n\n"
            f"🔐 <b>سياسة الخصوصية</b>\n{settings.privacy_text}",
            reply_markup=terms_keyboard(),
            ensure_navigation=False,
        )


@router.callback_query(F.data == "terms:accept")
async def terms_accept(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
    settings: Settings,
) -> None:
    await callback.answer()
    if not callback.from_user:
        return
    user = await services.users.get_or_create(
        session,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name,
    )
    await services.users.accept_terms(session, user)
    state_data = await state.get_data()
    pending_friend_token = state_data.get("pending_friend_token")
    await state.clear()
    if callback.message:
        if pending_friend_token:
            from app.bot.handlers.friends_warranty import render_friend_invitation

            await render_friend_invitation(
                callback.message,
                token=str(pending_friend_token),
                session=session,
                services=services,
            )
            return
        await edit_or_send(callback.message, 
            "تم قبول الشروط ✅\nتقدر تتصفح الخدمات الآن، ولن نطلب معلوماتك الأساسية إلا عند الشراء."
        )
        await send_home(callback.message, session, services, user, in_place=True)


@router.callback_query(F.data == "profile:complete")
async def profile_complete_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get_or_create(
        session,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name or "Telegram User",
    )
    await state.clear()
    await state.update_data(profile_complete_mode=True)
    if user.profile:
        private = services.data_protection.profile_data(user.profile)
        academic_values = [
            private.get("governorate"),
            private.get("university"),
            private.get("college"),
            private.get("department"),
            private.get("stage"),
        ]
        incomplete = any(
            not value or "يُستكمل" in str(value) or str(value).strip() in {"غير محدد", "-"}
            for value in academic_values
        )
        if not incomplete:
            await callback_notice(callback, 
                "ملفك مكتمل. استخدم زر تعديل معلوماتي للتغيير.",
                show_alert=True,
            )
            return
        await state.update_data(
            full_name=private.get("full_name") or callback.from_user.full_name,
            phone=private.get("phone") or "",
        )
        await state.set_state(RegistrationStates.governorate)
        await edit_or_send(callback.message, "اكتب اسم المحافظة لإكمال ملفك الدراسي:")
        return
    await state.set_state(RegistrationStates.full_name)
    await edit_or_send(callback.message, "اكتب اسمك الثلاثي باللغة العربية.\nمثال: علي محمد حسن")


@router.callback_query(F.data == "profile:edit")
async def profile_edit_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get(session, callback.from_user.id)
    if not user or not user.profile:
        await callback_notice(callback, "أكمل التسجيل أولًا", show_alert=True)
        return
    raw_limit = await session.scalar(select(SystemSetting.value).where(SystemSetting.key == "profile_edit_limit"))
    try:
        limit = max(0, int(raw_limit or "3"))
    except ValueError:
        limit = 3
    if user.profile.edit_count >= limit:
        await callback_notice(callback, "انتهت مرات التعديل المسموحة. راجع الدعم أو مالك البوت.", show_alert=True)
        return
    await state.clear()
    await state.update_data(profile_edit_mode=True)
    await state.set_state(RegistrationStates.full_name)
    await edit_or_send(callback.message, 
        f"✏️ تعديل المعلومات — المتبقي بعد هذا التعديل: {max(0, limit-user.profile.edit_count-1)}\n\n"
        "اكتب اسمك الثلاثي باللغة العربية. للإلغاء أرسل /cancel"
    )


@router.message(RegistrationStates.full_name)
async def registration_name(message: Message, state: FSMContext) -> None:
    value = validate_full_name(message.text or "")
    if not value:
        await message.answer("الاسم غير صحيح. اكتب ثلاثة أسماء عربية حقيقية بدون أرقام أو رموز.")
        return
    await state.update_data(full_name=value)
    await state.set_state(RegistrationStates.phone)
    await message.answer("اكتب رقم هاتفك كتابيًا.\nمثال: 07701234567")


@router.message(RegistrationStates.phone)
async def registration_phone(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    value = normalize_phone(message.text or "")
    if not value:
        await message.answer("الرقم غير صحيح. اكتب رقمًا عراقيًا مثل 07701234567.")
        return
    await state.update_data(phone=value)
    data = await state.get_data()
    if data.get("quick_registration"):
        if not message.from_user:
            return
        user = await services.users.get(session, message.from_user.id)
        if not user:
            await state.clear()
            await message.answer("استخدم /start من جديد.")
            return
        await services.users.save_profile(
            session,
            user,
            {
                "full_name": str(data.get("full_name") or message.from_user.full_name),
                "phone": value,
                "governorate": "يُستكمل لاحقاً",
                "university": "يُستكمل لاحقاً",
                "college": "يُستكمل لاحقاً",
                "department": "يُستكمل لاحقاً",
                "stage": "يُستكمل لاحقاً",
            },
            count_edit=False,
        )
        offer_id = int(data.get("pending_purchase_offer_id") or 0)
        await state.clear()
        keyboard = (
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🛒 متابعة شراء العرض",
                            callback_data=f"buy:{offer_id}",
                            style="success",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="🎓 إكمال معلومات الدراسة لاحقاً",
                            callback_data="profile:complete",
                        )
                    ],
                ]
            )
            if offer_id
            else None
        )
        await message.answer(
            "تم حفظ المعلومات الأساسية بأمان ✅\n"
            "تقدر تكمل معلومات الجامعة لاحقاً من «معلوماتي».",
            reply_markup=keyboard,
        )
        return
    await state.set_state(RegistrationStates.governorate)
    await message.answer("اكتب اسم المحافظة:")


async def _text_step(
    message: Message,
    state: FSMContext,
    key: str,
    next_state,
    prompt: str,
) -> bool:
    value = " ".join((message.text or "").split())
    if len(value) < 2 or len(value) > 180:
        await message.answer("القيمة غير صحيحة. أعد الكتابة بصورة واضحة.")
        return False
    await state.update_data(**{key: value})
    await state.set_state(next_state)
    await message.answer(prompt)
    return True


@router.message(RegistrationStates.governorate)
async def registration_governorate(message: Message, state: FSMContext) -> None:
    await _text_step(
        message, state, "governorate", RegistrationStates.university, "اكتب اسم الجامعة أو المعهد:"
    )


@router.message(RegistrationStates.university)
async def registration_university(message: Message, state: FSMContext) -> None:
    await _text_step(message, state, "university", RegistrationStates.college, "اكتب اسم الكلية:")


@router.message(RegistrationStates.college)
async def registration_college(message: Message, state: FSMContext) -> None:
    await _text_step(message, state, "college", RegistrationStates.department, "اكتب اسم القسم:")


@router.message(RegistrationStates.department)
async def registration_department(message: Message, state: FSMContext) -> None:
    await _text_step(
        message,
        state,
        "department",
        RegistrationStates.stage,
        "اكتب المرحلة الدراسية، مثال: الثانية:",
    )


@router.message(RegistrationStates.stage)
async def registration_stage(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    value = " ".join((message.text or "").split())
    if len(value) < 2 or len(value) > 80:
        await message.answer("اكتب المرحلة بصورة صحيحة.")
        return
    await state.update_data(stage=value)
    if not message.from_user:
        return
    user = await services.users.get(session, message.from_user.id)
    if not user:
        await message.answer("استخدم /start من جديد.")
        return
    data = await state.get_data()
    edit_mode = bool(data.get("profile_edit_mode"))
    await services.users.save_profile(
        session,
        user,
        {
            "full_name": data["full_name"],
            "phone": data["phone"],
            "governorate": data["governorate"],
            "university": data["university"],
            "college": data["college"],
            "department": data["department"],
            "stage": data["stage"],
        },
        count_edit=edit_mode,
    )
    await state.clear()
    complete_mode = bool(data.get("profile_complete_mode"))
    if edit_mode:
        result_text = "تم تعديل معلوماتك بنجاح ✅"
    elif complete_mode:
        result_text = "تم إكمال ملفك الدراسي بنجاح ✅"
    else:
        result_text = "تم تسجيل معلوماتك بنجاح ✅"
    await message.answer(result_text)
    await send_home(message, session, services, user)


@router.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("تم إلغاء العملية. استخدم /start للعودة.")
