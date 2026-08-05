from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import with_navigation
from app.bot.states import StudentActivationStates, TemporaryLogoutStates
from app.bot.ui import callback_notice, edit_or_send
from app.core.utils import safe
from app.db.models import (
    Order,
    ProviderInboxItem,
    StudentActivationRequest,
    StudentOperationalRestriction,
    StudentRestrictionStatus,
    TemporaryAccessSession,
    User,
)
from app.services.container import Services

router = Router(name="student_fulfillment_v11_2")


def _markup(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return with_navigation(InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("act:email:"))
async def student_activation_email_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    try:
        order_id = int((callback.data or "").split(":")[2])
    except (ValueError, IndexError):
        return
    order = await services.orders.get(session, order_id)
    if not order or order.user.telegram_id != callback.from_user.id:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    existing = await session.scalar(
        select(StudentActivationRequest)
        .where(
            StudentActivationRequest.order_id == order.id,
            StudentActivationRequest.user_id == order.user_id,
        )
        .order_by(StudentActivationRequest.created_at.desc())
        .limit(1)
    )
    if existing and existing.status not in {"failed", "cancelled"}:
        await edit_or_send(
            callback.message,
            f"تم إرسال إيميل التفعيل سابقاً: <code>{safe(existing.email_hint)}</code>\n"
            "سيصلك إشعار عند بدء المنصة بالتفعيل.",
        )
        return
    await state.clear()
    await state.update_data(activation_order_id=order.id)
    await state.set_state(StudentActivationStates.email)
    await edit_or_send(
        callback.message,
        "✉️ أرسل الإيميل الذي تريد تفعيل الخدمة عليه.\n\n"
        "تأكد من كتابته بصورة صحيحة؛ سيُشفّر داخل قاعدة البيانات.",
    )


@router.message(StudentActivationStates.email)
async def student_activation_email_submit(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    order = await services.orders.get(session, int(data.get("activation_order_id") or 0))
    if not order or order.user.telegram_id != message.from_user.id:
        await state.clear()
        await message.answer("تعذر ربط الإيميل بالطلب.")
        return
    try:
        request = await services.provider_operations.create_activation_request(
            session,
            order=order,
            student_email=message.text or "",
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    reviewers = await services.notifications.provider_support_ids(session, order.provider_id)
    for telegram_id in reviewers:
        try:
            await message.bot.send_message(
                telegram_id,
                "✉️ وصل إيميل طالب للتفعيل\n"
                f"الطلب: <code>{order.public_id}</code>\n"
                f"الإيميل: <code>{safe(request.email_hint)}</code>\n"
                "افتح بريد الطلبات والإثباتات لمعالجته.",
                reply_markup=_markup(
                    [[InlineKeyboardButton(text="📥 فتح البريد", callback_data="provider:inbox", style="primary")]]
                ),
            )
        except Exception:
            pass
    await message.answer(
        f"تم إرسال الإيميل للمنصة بأمان ✅\nالإيميل: <code>{safe(request.email_hint)}</code>"
    )


@router.callback_query(F.data.startswith("act:code:"))
async def student_activation_code_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    request_id = int((callback.data or "").split(":")[2])
    request = await session.scalar(
        select(StudentActivationRequest)
        .join(User, User.id == StudentActivationRequest.user_id)
        .where(
            StudentActivationRequest.id == request_id,
            User.telegram_id == callback.from_user.id,
            StudentActivationRequest.status == "waiting_student_code",
        )
    )
    if not request:
        await callback_notice(callback, "لا يوجد طلب رمز نشط", show_alert=True)
        return
    await state.clear()
    await state.update_data(activation_request_id=request.id)
    await state.set_state(StudentActivationStates.code)
    await edit_or_send(
        callback.message,
        "🔑 اكتب رمز التحقق الذي وصلك إلى إيميلك.\n"
        "الرمز سيُشفّر ويظهر لموظف المنصة المكلف مرة واحدة فقط.",
    )


@router.message(StudentActivationStates.code)
async def student_activation_code_submit(
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
    data = await state.get_data()
    try:
        relay = await services.provider_operations.submit_student_code(
            session,
            activation_request_id=int(data.get("activation_request_id") or 0),
            student_user_id=user.id,
            code=message.text or "",
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return
    request = await session.get(StudentActivationRequest, relay.activation_request_id)
    await state.clear()
    if request:
        reviewers = await services.notifications.provider_support_ids(session, request.provider_id)
        for telegram_id in reviewers:
            try:
                await message.bot.send_message(
                    telegram_id,
                    "🔑 وصل رمز التحقق من الطالب. افتح بريد الطلبات والإثباتات.",
                    reply_markup=_markup(
                        [[InlineKeyboardButton(text="📥 فتح البريد", callback_data="provider:inbox", style="danger")]]
                    ),
                )
            except Exception:
                pass
    await message.answer("تم إرسال الرمز للمنصة بأمان ✅")


@router.callback_query(F.data.startswith("tmp:proof:"))
async def temporary_logout_proof_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    temp_id = int((callback.data or "").split(":")[2])
    temp = await session.scalar(
        select(TemporaryAccessSession)
        .join(User, User.id == TemporaryAccessSession.user_id)
        .where(
            TemporaryAccessSession.id == temp_id,
            User.telegram_id == callback.from_user.id,
            TemporaryAccessSession.deletion_acknowledged_at.is_(None),
        )
    )
    if not temp:
        await callback_notice(callback, "جلسة الاستخدام غير موجودة أو مغلقة", show_alert=True)
        return
    await state.clear()
    await state.update_data(temporary_session_id=temp.id)
    await state.set_state(TemporaryLogoutStates.proof)
    await edit_or_send(
        callback.message,
        "📤 أرسل صورة واضحة تثبت تسجيل خروجك من الحساب.\n"
        "لن تُغلق العملية إلا بعد تأكيد صاحب المنصة.",
    )


@router.message(TemporaryLogoutStates.proof)
async def temporary_logout_proof_submit(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    if not message.photo and not message.document:
        await message.answer("أرسل صورة أو ملف إثبات واضح.")
        return
    data = await state.get_data()
    temp = await session.get(TemporaryAccessSession, int(data.get("temporary_session_id") or 0))
    user = await services.users.get(session, message.from_user.id)
    if not temp or not user or temp.user_id != user.id:
        await state.clear()
        return
    order = await session.get(Order, temp.order_id)
    if not order:
        await state.clear()
        return
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    file_type = "photo" if message.photo else "document"
    evidence = await services.evidence.register_telegram(
        session,
        user,
        file_id,
        file_type,
        "temporary_logout_proof",
        provider_id=order.provider_id,
        order_id=order.id,
        original_name=(message.document.file_name or "") if message.document else "",
        mime_type=message.document.mime_type if message.document else "image/jpeg",
        size_bytes=(message.document.file_size if message.document else message.photo[-1].file_size),
    )
    proof = await services.provider_operations.submit_logout_proof(
        session,
        temporary_session=temp,
        provider_id=order.provider_id,
        order_id=order.id,
        user_id=user.id,
        telegram_file_id=file_id,
        evidence_asset_id=evidence.id,
        student_note=message.caption or "",
    )
    await state.clear()
    await message.answer(
        "تم إرسال إثبات الخروج للمنصة ✅\n"
        "ستبقى العملية معلقة حتى يؤكد صاحب المنصة تسجيل خروجك.",
        reply_markup=_markup(
            [[InlineKeyboardButton(text="🆘 مركز المساعدة", callback_data="announcement:open:support", style="primary")]]
        ),
    )
    inbox_item = await session.scalar(
        select(ProviderInboxItem).where(
            ProviderInboxItem.source_type == "temporary_logout_proof",
            ProviderInboxItem.source_id == proof.id,
        )
    )
    reviewers = await services.notifications.provider_support_ids(session, order.provider_id)
    for telegram_id in reviewers:
        try:
            await services.evidence.send(
                session,
                evidence,
                None,
                telegram_id,
                f"🚪 إثبات تسجيل خروج للطلب <code>{order.public_id}</code>",
                reply_markup=_markup(
                    [[InlineKeyboardButton(
                        text="📥 فتح البريد",
                        callback_data=f"p:in:{inbox_item.id}" if inbox_item else "provider:inbox",
                        style="primary",
                    )]]
                ),
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("tmp:review:"))
async def temporary_restriction_review(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    restriction_id = int((callback.data or "").split(":")[2])
    restriction = await session.scalar(
        select(StudentOperationalRestriction)
        .join(User, User.id == StudentOperationalRestriction.user_id)
        .where(
            StudentOperationalRestriction.id == restriction_id,
            User.telegram_id == callback.from_user.id,
            StudentOperationalRestriction.status == StudentRestrictionStatus.ACTIVE.value,
        )
        .with_for_update()
    )
    if not restriction:
        return
    restriction.status = StudentRestrictionStatus.REVIEW.value
    restriction.review_requested_at = datetime.now(UTC)
    await edit_or_send(
        callback.message,
        "تم تسجيل طلب المراجعة. يمكنك الآن رفع إثبات الخروج أو التواصل مع مركز المساعدة.",
        reply_markup=_markup(
            [
                [InlineKeyboardButton(text="📤 رفع إثبات الخروج", callback_data=f"tmp:proof_order:{restriction.order_id}", style="success")],
                [InlineKeyboardButton(text="🆘 مركز المساعدة", callback_data="announcement:open:support", style="primary")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("tmp:proof_order:"))
async def temporary_proof_by_order(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    order_id = int((callback.data or "").split(":")[2])
    temp = await session.scalar(
        select(TemporaryAccessSession)
        .join(User, User.id == TemporaryAccessSession.user_id)
        .where(
            TemporaryAccessSession.order_id == order_id,
            User.telegram_id == callback.from_user.id,
            TemporaryAccessSession.deletion_acknowledged_at.is_(None),
        )
    )
    if not temp:
        await callback_notice(callback, "لا توجد جلسة خروج معلقة", show_alert=True)
        return
    await state.clear()
    await state.update_data(temporary_session_id=temp.id)
    await state.set_state(TemporaryLogoutStates.proof)
    await edit_or_send(callback.message, "أرسل صورة إثبات تسجيل الخروج الآن.")

@router.callback_query(F.data.startswith("tmp:review_order:"))
async def temporary_connect_or_review_by_order(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    """Record an Internet/app interruption without allowing silent expiry.

    The student remains responsible for evidence, but the provider receives an
    immediate traceable notice instead of treating the delay as unexplained.
    """
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    order_id = int((callback.data or "").split(":")[2])
    user = await services.users.get(session, callback.from_user.id)
    if not user:
        return
    order = await session.scalar(
        select(Order).where(Order.id == order_id, Order.user_id == user.id)
    )
    if not order:
        await callback_notice(callback, "الطلب غير موجود", show_alert=True)
        return
    await services.provider_operations.enqueue_inbox(
        session,
        provider_id=order.provider_id,
        kind="logout_proof",
        idempotency_key=f"temporary-connectivity:{order.id}:{user.id}",
        title="📡 الطالب أبلغ عن مشكلة اتصال",
        summary=(
            f"الطلب {order.public_id}. أبلغ الطالب أن الإنترنت أو التطبيق تعطل؛ "
            "ما زال إثبات تسجيل الخروج مطلوباً عند عودة الاتصال."
        ),
        order_id=order.id,
        user_id=user.id,
        source_type="temporary_connectivity_notice",
        source_id=order.id,
        priority="high",
    )
    await edit_or_send(
        callback.message,
        "تم إبلاغ المنصة بمشكلة الاتصال. عند عودة الإنترنت، أرسل إثبات تسجيل الخروج فوراً.",
        reply_markup=_markup(
            [
                [InlineKeyboardButton(
                    text="📤 رفع إثبات الخروج",
                    callback_data=f"tmp:proof_order:{order.id}",
                    style="success",
                )],
                [InlineKeyboardButton(
                    text="🆘 مركز المساعدة",
                    callback_data="announcement:open:support",
                    style="primary",
                )],
            ]
        ),
    )
