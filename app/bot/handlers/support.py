from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import ai_support_result_keyboard, solved_keyboard, support_faq_keyboard, with_navigation
from app.bot.states import BotIssueStates, SupportStates
from app.bot.ui import edit_or_send, callback_notice
from app.core.config import Settings
from app.core.presentation import sender_role_label, ticket_status_label
from app.core.errors import AuthorizationError, ResourceNotFoundError
from app.core.utils import safe
from app.db.models import DistributedJob, EvidenceAsset, SupportFAQ, SupportTicket, User
from app.services.container import Services

logger = logging.getLogger(__name__)

router = Router(name="support")


async def _notify_ticket(session: AsyncSession, services: Services, ticket: SupportTicket) -> None:
    targets: set[int] = set()
    if ticket.provider_id:
        targets.update(
            await services.notifications.provider_support_ids(session, ticket.provider_id)
        )
    targets.update(services.notifications.settings.admin_ids)
    text = (
        f"🎫 <b>تذكرة جديدة</b>\n"
        f"الرقم: <code>{ticket.public_id}</code>\n"
        f"الموضوع: {safe(ticket.subject)}\n"
        f"الحالة: {ticket_status_label(ticket.status)}"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 الرد", callback_data=f"ticket:reply:{ticket.id}", style="primary"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ إغلاق", callback_data=f"ticket:close:{ticket.id}", style="success"
                )
            ],
        ]
    )
    for target in targets:
        try:
            await services.notifications.bot.send_message(target, text, reply_markup=keyboard)
        except Exception as exc:
            logger.warning("Could not notify ticket target %s: %s", target, exc)


@router.message(Command("help"))
async def help_command(message: Message, settings: Settings) -> None:
    await message.answer(settings.help_text)


@router.message(Command("support"))
async def support_command(
    message: Message, session: AsyncSession, settings: Settings, services: Services
) -> None:
    faqs = await services.support.faqs(session)
    await message.answer(
        settings.support_text, reply_markup=with_navigation(support_faq_keyboard(faqs))
    )


@router.callback_query(F.data.startswith("support:direct:"))
async def direct_provider_support_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    try:
        order_id = int((callback.data or "").rsplit(":", 1)[1])
        _actor, owned_order = await services.authorization.require_owned_order(
            session, callback.from_user.id, order_id
        )
    except (ValueError, AuthorizationError, ResourceNotFoundError):
        await callback_notice(callback, "الطلب غير موجود", show_alert=True)
        return
    await state.clear()
    await state.update_data(direct_support_order_id=owned_order.id)
    await state.set_state(SupportStates.direct_message)
    await edit_or_send(callback.message, 
        "🎧 اكتب مشكلتك بالتفصيل. سيتم تحويل رسالتك مباشرة إلى حساب مزود الخدمة "
        "مع رقم الطلب، من دون نظام نزاعات معقد. لا ترسل كلمة مرور أو رمز تحقق أو بيانات بطاقة."
    )


@router.message(
    SupportStates.direct_message,
    flags={"processing_immediate": True, "long_operation": True},
)
async def direct_provider_support_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    complaint = (message.text or message.caption or "").strip()
    if len(complaint) < 5:
        await message.answer("اكتب تفاصيل أوضح عن المشكلة.")
        return
    data = await state.get_data()
    try:
        order_id = int(data.get("direct_support_order_id", 0))
        user, owned_order = await services.authorization.require_owned_order(
            session, message.from_user.id, order_id
        )
        order = await services.orders.get(session, owned_order.id)
    except (ValueError, AuthorizationError, ResourceNotFoundError):
        await state.clear()
        await message.answer("تعذر العثور على الطلب. افتح الدعم من الطلب مرة أخرى.")
        return
    if not order:
        await state.clear()
        await message.answer("تعذر تحميل الطلب. حاول مرة أخرى.")
        return

    ticket, provider_targets = await services.direct_support.open(
        session, user, order, complaint
    )
    targets = set(provider_targets)
    if not targets:
        targets.update(services.settings.admin_ids)

    profile = order.user.profile
    student_name = profile.full_name if profile else order.user.telegram_name
    context_text = (
        "🎧 <b>شكوى طالب مباشرة</b>\n"
        f"التذكرة: <code>{ticket.public_id}</code>\n"
        f"الطلب: <code>{order.public_id}</code>\n"
        f"الطالب: {safe(student_name)}\n"
        f"العرض: {safe(order.offer.title)}\n"
        f"الشكوى: {safe(complaint)}"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="💬 الرد على الطالب",
                callback_data=f"ticket:reply:{ticket.id}",
                style="primary",
            )
        ]]
    )
    delivered = 0
    for target in targets:
        try:
            # Forward the original Telegram message first; fall back to copied text
            # when forwarding is restricted by Telegram privacy/protected content.
            try:
                await message.bot.forward_message(
                    chat_id=target,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                )
            except Exception:
                pass
            await message.bot.send_message(target, context_text, reply_markup=keyboard)
            delivered += 1
        except Exception as exc:
            logger.warning("Direct provider support delivery failed for %s: %s", target, type(exc).__name__)

    await state.clear()
    if delivered:
        await message.answer(
            f"✅ تم تحويل مشكلتك مباشرة إلى مزود الخدمة. رقم التذكرة: "
            f"<code>{ticket.public_id}</code>"
        )
    else:
        await message.answer(
            f"✅ تم حفظ مشكلتك كتذكرة <code>{ticket.public_id}</code>، "
            "لكن تعذر إرسال التنبيه الفوري. ستبقى ظاهرة في لوحة الدعم."
        )


@router.callback_query(F.data == "bot_issue:start")
async def bot_issue_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await state.set_state(BotIssueStates.category)
    if callback.message:
        await edit_or_send(callback.message, 
            "🐞 اختر نوع مشكلة البوت. هذا البلاغ يصل لمالك البوت فقط:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="زر لا يعمل", callback_data="bot_issue:category:button")],
                    [InlineKeyboardButton(text="الأزرار اختفت", callback_data="bot_issue:category:keyboard", style="danger")],
                    [InlineKeyboardButton(text="مشكلة طلب أو دفع", callback_data="bot_issue:category:order")],
                    [InlineKeyboardButton(text="مشكلة إيميل أو رمز", callback_data="bot_issue:category:email")],
                    [InlineKeyboardButton(text="مشكلة أخرى", callback_data="bot_issue:category:other")],
                    [InlineKeyboardButton(text="❌ إلغاء العملية", callback_data="nav:cancel", style="danger")],
                ]
            ),
        )


@router.callback_query(F.data.startswith("bot_issue:category:"))
async def bot_issue_category(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    category = (callback.data or "").split(":")[-1]
    await state.update_data(bot_issue_category=category)
    await state.set_state(BotIssueStates.description)
    if callback.message:
        await edit_or_send(callback.message, 
            "اكتب المشكلة بالتفصيل. لا ترسل كلمة مرور أو رمز تحقق أو بيانات بطاقة.\n\n"
            "يمكنك ضغط 🏠 الرئيسية أو ❌ إلغاء العملية بأي وقت."
        )


@router.message(BotIssueStates.description)
async def bot_issue_description(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    description = (message.text or "").strip()
    if len(description) < 5:
        await message.answer("اكتب تفاصيل أكثر عن المشكلة.")
        return
    await state.update_data(bot_issue_description=description[:6000])
    await state.set_state(BotIssueStates.attachment)
    await message.answer(
        "أرسل صورة أو فيديو أو ملف يوضح المشكلة، أو أرسل <code>-</code> بدون مرفق."
    )


@router.message(BotIssueStates.attachment)
async def bot_issue_attachment(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    user = await services.users.get(session, message.from_user.id)
    if not user:
        await state.clear()
        return
    file_id = file_type = None
    if message.photo:
        file_id, file_type = message.photo[-1].file_id, "photo"
    elif message.video:
        file_id, file_type = message.video.file_id, "video"
    elif message.document:
        file_id, file_type = message.document.file_id, "document"
    elif (message.text or "").strip() != "-":
        await message.answer("أرسل مرفقًا أو علامة - للتخطي.")
        return
    data = await state.get_data()
    current_state = await state.get_state()
    issue = await services.issues.create(
        session,
        user=user,
        category=str(data.get("bot_issue_category") or "other"),
        description=str(data.get("bot_issue_description") or ""),
        file_id=file_id,
        file_type=file_type,
        last_action="bot_issue:start",
        conversation_state=current_state,
    )
    await state.clear()
    notification = (
        f"🐞 <b>بلاغ جديد عن البوت</b>\n"
        f"الرقم: <code>{issue.public_id}</code>\n"
        f"الفئة: {safe(issue.category)}\n"
        f"المستخدم: <code>{user.telegram_id}</code>\n\n"
        f"{safe(issue.description)}"
    )
    for admin_id in services.notifications.settings.admin_ids:
        try:
            await services.notifications.bot.send_message(
                admin_id,
                notification,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔎 فتح البلاغ", callback_data=f"admin:bot_issue:{issue.id}", style="danger")]
                    ]
                ),
            )
            if file_id:
                if file_type == "photo":
                    await services.notifications.bot.send_photo(admin_id, file_id)
                elif file_type == "video":
                    await services.notifications.bot.send_video(admin_id, file_id)
                else:
                    await services.notifications.bot.send_document(admin_id, file_id)
        except Exception as exc:
            logger.warning("Could not notify owner about issue %s: %s", issue.id, exc)
    await message.answer(
        f"✅ وصل البلاغ إلى مالك البوت فقط.\nرقم المتابعة: <code>{issue.public_id}</code>"
    )


@router.callback_query(F.data.startswith("support:order:"))
async def support_order(callback: CallbackQuery, session: AsyncSession, services: Services) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    order_id = int((callback.data or "").split(":")[2])
    try:
        await services.authorization.require_owned_order(
            session, callback.from_user.id, order_id
        )
    except (AuthorizationError, ResourceNotFoundError):
        await callback_notice(callback, "الطلب غير موجود", show_alert=True)
        return
    faqs = await services.support.faqs(session)
    await edit_or_send(callback.message, 
        "اختر المشكلة:", reply_markup=support_faq_keyboard(faqs, order_id)
    )


@router.callback_query(F.data.startswith("faq:"))
async def faq_answer(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user:
        return
    parts = (callback.data or "").split(":")
    faq = await session.get(SupportFAQ, int(parts[1]))
    order_id = int(parts[2]) if len(parts) > 2 else 0
    if order_id:
        try:
            await services.authorization.require_owned_order(
                session, callback.from_user.id, order_id
            )
        except (AuthorizationError, ResourceNotFoundError):
            await callback_notice(callback, "الطلب غير موجود", show_alert=True)
            return
    if faq and callback.message:
        await edit_or_send(callback.message, 
            f"{faq.emoji} <b>{safe(faq.question)}</b>\n\n{safe(faq.answer)}",
            reply_markup=solved_keyboard(order_id),
        )


@router.callback_query(F.data.startswith("support:custom:"))
async def support_custom_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user:
        return
    order_id = int((callback.data or "").split(":")[2])
    if order_id:
        try:
            await services.authorization.require_owned_order(
                session, callback.from_user.id, order_id
            )
        except (AuthorizationError, ResourceNotFoundError):
            await callback_notice(callback, "الطلب غير موجود", show_alert=True)
            return
    await state.clear()
    await state.update_data(support_order_id=order_id)
    await state.set_state(SupportStates.custom_question)
    if callback.message:
        await edit_or_send(callback.message, 
            "اكتب سؤالك بالتفصيل دون إرسال كلمة مرور أو رمز تحقق أو بيانات بطاقة:"
        )


@router.message(SupportStates.custom_question, flags={"processing_immediate": True, "ai": True})
async def support_custom_question(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    question = (message.text or "").strip()
    if len(question) < 5:
        await message.answer("اكتب تفاصيل أكثر.")
        return
    if len(question) > services.settings.gemini_max_question_chars:
        await message.answer(
            f"اختصر السؤال إلى أقل من {services.settings.gemini_max_question_chars} حرف."
        )
        return
    data = await state.get_data()
    order_id = int(data.get("support_order_id", 0))
    if order_id and message.from_user:
        try:
            await services.authorization.require_owned_order(
                session, message.from_user.id, order_id
            )
        except (AuthorizationError, ResourceNotFoundError):
            await state.clear()
            await message.answer("الطلب غير موجود أو لا يخص حسابك.")
            return

    user = await services.users.get(session, message.from_user.id) if message.from_user else None
    ai_enabled = await services.features.enabled(
        session, "gemini", services.settings.gemini_ready
    )
    if ai_enabled and user and user.ai_data_consent_at:
        try:
            job = await services.support.enqueue_ai_request(
                session,
                user=user,
                chat_id=message.chat.id,
                source_message_id=message.message_id,
                question=question,
                order_id=order_id,
            )
        except ValueError as exc:
            await message.answer(str(exc))
            return
        placeholder = await message.answer(
            "🤖 تم استلام سؤالك. المساعد يراجع بيانات الطلب المسموح بها الآن…\n"
            "يمكنك متابعة استخدام البوت، وسيصل الرد هنا تلقائياً."
        )
        job.payload_json = {
            **(job.payload_json or {}),
            "placeholder_message_id": int(placeholder.message_id),
        }
        await session.flush()
        await state.clear()
        return

    await state.update_data(support_question=question, support_ai_answer="")
    await state.set_state(None)
    if not ai_enabled:
        reason = "🤖 المساعد الذكي غير مفعّل حاليًا من إدارة المنصة."
    elif not user or not user.ai_data_consent_at:
        reason = "🔐 المساعد الذكي يحتاج موافقتك على استخدام السياق المنقّح من قسم الخصوصية أولًا."
    else:
        reason = "⚠️ المساعد الذكي غير متاح مؤقتاً."
    await message.answer(
        reason + "\n\nهل تريد تحويل السؤال إلى مزود الخدمة؟",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ نعم، افتح تذكرة",
                        callback_data=f"support:unresolved:{order_id}",
                        style="success",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="↩️ رجوع", callback_data=f"support:custom:{order_id}"
                    )
                ],
            ]
        ),
    )


@router.callback_query(F.data == "support:solved")
async def support_solved(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback_notice(callback, "سعداء بحل المشكلة ✅")


@router.callback_query(F.data.startswith("support:aiunresolved:"))
async def support_ai_unresolved(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    try:
        job_id = int((callback.data or "").rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await callback_notice(callback, "طلب الدعم غير صالح", show_alert=True)
        return
    job = await session.get(DistributedJob, job_id)
    payload = dict(job.payload_json or {}) if job else {}
    if (
        job is None
        or job.queue_name != services.support.AI_QUEUE
        or job.job_type != services.support.AI_JOB_TYPE
        or int(payload.get("telegram_id", 0) or 0) != callback.from_user.id
    ):
        await callback_notice(callback, "طلب الدعم غير موجود", show_alert=True)
        return
    user = await services.users.get(session, callback.from_user.id)
    if user is None:
        await callback_notice(callback, "الحساب غير موجود", show_alert=True)
        return
    order_id = int(payload.get("order_id", 0) or 0)
    order = None
    if order_id:
        try:
            _actor, owned_order = await services.authorization.require_owned_order(
                session, callback.from_user.id, order_id
            )
        except (AuthorizationError, ResourceNotFoundError):
            await callback_notice(callback, "الطلب غير موجود", show_alert=True)
            return
        order = await services.orders.get(session, owned_order.id)
    result = dict(job.result_json or {})
    ticket = await services.support.create_ticket(
        session,
        user,
        subject="طلب مساعدة بعد رد المساعد الذكي",
        message=str(payload.get("question") or "المشكلة لم تُحل")[:4000],
        category="order" if order else "general",
        provider_id=order.provider_id if order else None,
        order_id=order.id if order else None,
        ai_answer=str(result.get("answer") or "")[:4000] or None,
    )
    await _notify_ticket(session, services, ticket)
    await edit_or_send(
        callback.message,
        f"تم إنشاء التذكرة <code>{ticket.public_id}</code> ✅\n"
        "سيتم التواصل معك داخل البوت دون كشف معرفات الأطراف.",
    )


@router.callback_query(F.data.startswith("support:unresolved:"))
async def support_unresolved(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get(session, callback.from_user.id)
    if not user:
        return
    order_id = int((callback.data or "").split(":")[2]) or None
    order = None
    if order_id:
        try:
            _actor, owned_order = await services.authorization.require_owned_order(
                session, callback.from_user.id, order_id
            )
        except (AuthorizationError, ResourceNotFoundError):
            await callback_notice(callback, "الطلب غير موجود", show_alert=True)
            return
        order = await services.orders.get(session, owned_order.id)
    data = await state.get_data()
    question = data.get("support_question") or "المشكلة لم تُحل من الإجابة المقترحة"
    ticket = await services.support.create_ticket(
        session,
        user,
        subject="طلب مساعدة من مزود الخدمة",
        message=question,
        category="order" if order else "general",
        provider_id=order.provider_id if order else None,
        order_id=order.id if order else None,
        ai_answer=data.get("support_ai_answer") or None,
    )
    await state.clear()
    await _notify_ticket(session, services, ticket)
    await edit_or_send(callback.message, 
        f"تم إنشاء التذكرة <code>{ticket.public_id}</code> ✅\n"
        "سيتم التواصل معك داخل البوت دون كشف معرفات الأطراف."
    )


@router.callback_query(F.data.startswith("tickets:mine"))
async def my_tickets(callback: CallbackQuery, session: AsyncSession, services: Services) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    user = await services.users.get(session, callback.from_user.id)
    if not user:
        return
    parts = (callback.data or "tickets:mine:0").split(":")
    try:
        page = max(0, int(parts[2])) if len(parts) > 2 else 0
    except ValueError:
        page = 0
    tickets, total = await services.support.user_tickets_page(
        session, user, page=page, page_size=8
    )
    if not tickets:
        await edit_or_send(callback.message, "لا توجد تذاكر في هذه الصفحة.")
        return
    rows = []
    for ticket in tickets:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{ticket.public_id} — {ticket_status_label(ticket.status)}",
                    callback_data=f"ticket:view:{ticket.id}:0",
                )
            ]
        )
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ الأحدث", callback_data=f"tickets:mine:{page - 1}"))
    if (page + 1) * 8 < total:
        nav.append(InlineKeyboardButton(text="الأقدم ▶️", callback_data=f"tickets:mine:{page + 1}"))
    if nav:
        rows.append(nav)
    await edit_or_send(callback.message, 
        f"🎫 <b>تذاكري</b> — {total} تذكرة",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.message(Command("ticket"))
async def find_ticket_by_public_id(
    message: Message, session: AsyncSession, services: Services
) -> None:
    if not message.from_user:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("اكتب رقم التذكرة بعد الأمر، مثال: <code>/ticket TKT-XXXX</code>")
        return
    public_id = parts[1].strip().upper()
    user = await services.users.get(session, message.from_user.id)
    ticket = await session.scalar(
        select(SupportTicket).where(SupportTicket.public_id == public_id)
    )
    if not user or not ticket or ticket.user_id != user.id:
        await message.answer("لم أجد تذكرة بهذا الرقم ضمن حسابك.")
        return
    messages, total = await services.support.ticket_messages_page(
        session, ticket.id, page=0, page_size=15
    )
    lines = [
        f"🎫 <b>{ticket.public_id}</b> — {ticket_status_label(ticket.status)}",
        f"\nالموضوع: {safe(ticket.subject)}",
    ]
    for item in messages:
        lines.append(f"\n<b>{safe(sender_role_label(item.sender_role))}:</b> {safe(item.text)}")
    await message.answer("".join(lines) + f"\n\nالرسائل المعروضة: {len(messages)} من {total}")


@router.callback_query(F.data.startswith("ticket:view:"))
async def ticket_view(callback: CallbackQuery, session: AsyncSession, services: Services) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    parts = (callback.data or "").split(":")
    ticket_id = int(parts[2])
    try:
        page = max(0, int(parts[3])) if len(parts) > 3 else 0
    except ValueError:
        page = 0
    ticket = await services.support.get_ticket(session, ticket_id)
    if not ticket:
        await callback_notice(callback, "التذكرة غير موجودة", show_alert=True)
        return
    try:
        await services.authorization.ticket_actor(session, callback.from_user.id, ticket)
    except (AuthorizationError, ResourceNotFoundError):
        await callback_notice(callback, "التذكرة غير موجودة", show_alert=True)
        return
    messages, total = await services.support.ticket_messages_page(
        session, ticket.id, page=page, page_size=15
    )
    lines = [
        f"🎫 <b>{ticket.public_id}</b> — {ticket_status_label(ticket.status)}",
        f"\nالموضوع: {safe(ticket.subject)}",
    ]
    for item in messages:
        lines.append(f"\n<b>{safe(sender_role_label(item.sender_role))}:</b> {safe(item.text)}")
    lines.append(f"\n\nالرسائل المعروضة: {len(messages)} من {total}")
    buttons = [
        [
            InlineKeyboardButton(
                text="💬 إضافة رد",
                callback_data=f"ticket:reply:{ticket.id}",
                style="primary",
            )
        ]
    ]
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀️ الرسائل الأحدث",
                callback_data=f"ticket:view:{ticket.id}:{page - 1}",
            )
        )
    if (page + 1) * 15 < total:
        nav.append(
            InlineKeyboardButton(
                text="رسائل أقدم ▶️",
                callback_data=f"ticket:view:{ticket.id}:{page + 1}",
            )
        )
    if nav:
        buttons.append(nav)
    if ticket.status != "closed":
        buttons.append(
            [
                InlineKeyboardButton(
                    text="✅ إغلاق",
                    callback_data=f"ticket:close:{ticket.id}",
                    style="success",
                )
            ]
        )
    buttons.append([InlineKeyboardButton(text="↩️ تذاكري", callback_data="tickets:mine:0")])
    await edit_or_send(callback.message, 
        "".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("ticket:attachment:"))
async def ticket_attachment(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    from app.db.models import TicketMessage

    item = await session.get(TicketMessage, int((callback.data or "").split(":")[2]))
    if not item or not item.evidence_asset_id:
        await callback_notice(callback, "المرفق غير موجود", show_alert=True)
        return
    ticket = await services.support.get_ticket(session, item.ticket_id)
    if not ticket:
        await callback_notice(callback, "التذكرة غير موجودة", show_alert=True)
        return
    try:
        actor = await services.authorization.ticket_actor(session, callback.from_user.id, ticket)
    except (AuthorizationError, ResourceNotFoundError):
        await callback_notice(callback, "المرفق غير موجود", show_alert=True)
        return
    asset = await session.get(EvidenceAsset, item.evidence_asset_id)
    if not asset:
        await callback_notice(callback, "المرفق غير موجود", show_alert=True)
        return
    await callback_notice(callback, "جاري تحميل المرفق...")
    await services.evidence.send(
        session,
        asset,
        actor.user,
        callback.message.chat.id,
        f"📎 مرفق التذكرة {ticket.public_id}",
    )


@router.callback_query(F.data.startswith("ticket:reply:"))
async def ticket_reply_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user:
        return
    ticket = await services.support.get_ticket(session, int((callback.data or "").split(":")[2]))
    if not ticket:
        await callback_notice(callback, "التذكرة غير موجودة", show_alert=True)
        return
    try:
        await services.authorization.ticket_actor(session, callback.from_user.id, ticket)
    except (AuthorizationError, ResourceNotFoundError):
        await callback_notice(callback, "التذكرة غير موجودة", show_alert=True)
        return
    if ticket.status == "closed":
        await callback_notice(callback, "التذكرة مغلقة", show_alert=True)
        return
    await state.clear()
    await state.update_data(ticket_id=ticket.id)
    await state.set_state(SupportStates.ticket_message)
    if callback.message:
        await edit_or_send(callback.message, "اكتب ردك الآن:")


@router.message(SupportStates.ticket_message)
async def ticket_reply_message(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    text = (message.text or message.caption or "").strip()
    if len(text) < 2:
        await message.answer("اكتب ردًا واضحًا.")
        return
    data = await state.get_data()
    ticket = await services.support.get_ticket(session, int(data["ticket_id"]))
    if not ticket:
        await state.clear()
        return
    try:
        actor = await services.authorization.ticket_actor(
            session, message.from_user.id, ticket
        )
    except (AuthorizationError, ResourceNotFoundError):
        await state.clear()
        await message.answer("لم تعد تملك صلاحية الرد على هذه التذكرة.")
        return
    sender = actor.user
    role = actor.ticket_role.value if actor.ticket_role else "user"
    file_id = (
        message.photo[-1].file_id
        if message.photo
        else (message.document.file_id if message.document else None)
    )
    file_type = "photo" if message.photo else ("document" if message.document else None)
    evidence_asset = None
    if file_id:
        evidence_asset = await services.evidence.register_telegram(
            session,
            sender,
            file_id,
            file_type or "document",
            "support_attachment",
            provider_id=ticket.provider_id,
            order_id=ticket.order_id,
            ticket_id=ticket.id,
            original_name=(message.document.file_name or "")[:255] if message.document else "",
            mime_type=message.document.mime_type if message.document else "image/jpeg" if message.photo else None,
            size_bytes=message.document.file_size if message.document else (message.photo[-1].file_size if message.photo else None),
        )
    await services.support.add_message(
        session,
        ticket,
        sender,
        role,
        text,
        None,
        file_type,
        evidence_asset_id=evidence_asset.id if evidence_asset else None,
    )
    await state.clear()
    if role == "user":
        await _notify_ticket(session, services, ticket)
    else:
        target = await session.get(User, ticket.user_id)
        if target:
            await services.notifications.send_user(
                session,
                target,
                f"رد على التذكرة {ticket.public_id}",
                safe(text),
            )
    await message.answer("تم إرسال الرد ✅")


@router.callback_query(F.data.startswith("ticket:close:"))
async def ticket_close(callback: CallbackQuery, session: AsyncSession, services: Services) -> None:
    await callback.answer()
    if not callback.from_user:
        return
    ticket = await services.support.get_ticket(session, int((callback.data or "").split(":")[2]))
    if not ticket:
        await callback_notice(callback, "التذكرة غير موجودة", show_alert=True)
        return
    try:
        actor = await services.authorization.ticket_actor(
            session, callback.from_user.id, ticket
        )
    except (AuthorizationError, ResourceNotFoundError):
        await callback_notice(callback, "التذكرة غير موجودة", show_alert=True)
        return
    await services.support.close_ticket(session, ticket, actor.user)
    await callback_notice(callback, "تم الإغلاق")
    if callback.message:
        await edit_or_send(callback.message, "تم إغلاق التذكرة وتسجيل منفذ العملية ✅")
