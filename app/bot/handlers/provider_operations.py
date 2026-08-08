from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.provider import _staff, _staff_for_provider
from app.bot.keyboards.inline import with_navigation
from app.bot.states import ProviderWorkingHoursStates
from app.bot.ui import callback_notice, edit_or_send
from app.core.utils import safe
from app.db.models import (
    ActivationRequestStatus,
    ProviderInboxItem,
    ProviderInboxItemStatus,
    ProviderWorkingHour,
    StudentActivationRequest,
    StudentCodeRelay,
    TemporaryLogoutProof,
    User,
)
from app.domain.provider_operations import (
    ProviderInboxKind,
    ProviderInboxStatus,
    format_clock_minutes,
    parse_clock_minutes,
    provider_working_status,
)
from app.services.container import Services

router = Router(name="provider_operations_v11_2")

_WEEKDAYS = (
    "الاثنين",
    "الثلاثاء",
    "الأربعاء",
    "الخميس",
    "الجمعة",
    "السبت",
    "الأحد",
)


def _markup(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return with_navigation(InlineKeyboardMarkup(inline_keyboard=rows))


async def _authorized_staff(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    *,
    permission: str,
):
    if not callback.from_user or not callback.message:
        return None, None
    user, staff = await _staff(session, services, callback.from_user.id)
    if not staff or not getattr(staff, permission, False):
        await callback_notice(callback, "لا تملك الصلاحية المطلوبة", show_alert=True)
        return user, None
    return user, staff


async def _render_working_hours(
    message: Message,
    session: AsyncSession,
    *,
    provider_id: int,
) -> None:
    rows = list(
        (
            await session.scalars(
                select(ProviderWorkingHour)
                .where(ProviderWorkingHour.provider_id == provider_id)
                .order_by(ProviderWorkingHour.weekday)
            )
        ).all()
    )
    by_day = {row.weekday: row for row in rows}
    lines = ["🕒 <b>ساعات العمل</b>\n"]
    buttons: list[list[InlineKeyboardButton]] = []
    now = datetime.now(ZoneInfo("Asia/Baghdad"))
    for weekday, label in enumerate(_WEEKDAYS):
        row = by_day.get(weekday)
        if row is None:
            opens, closes, closed = 600, 1380, False
        else:
            opens, closes, closed = row.opens_minute, row.closes_minute, row.is_closed
        if closed:
            description = "مغلق"
        else:
            description = f"{format_clock_minutes(opens)}–{format_clock_minutes(closes)}"
        lines.append(f"• {label}: <b>{description}</b>")
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{label} — {description}",
                    callback_data=f"p:wh:{weekday}",
                    style="primary",
                )
            ]
        )
    today = by_day.get(now.weekday())
    if today:
        public = provider_working_status(
            now=now,
            weekday=now.weekday(),
            opens_minute=today.opens_minute,
            closes_minute=today.closes_minute,
            is_closed=today.is_closed,
        )
        lines.extend(["", f"الحالة الحالية للطلاب: <b>{public.message}</b>"])
    buttons.append(
        [InlineKeyboardButton(text="↩️ لوحة المنصة", callback_data=f"provider:select:{provider_id}")]
    )
    await edit_or_send(message, "\n".join(lines), reply_markup=_markup(buttons))


@router.callback_query(F.data == "provider:working_hours")
async def provider_working_hours(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    _user, staff = await _authorized_staff(
        callback, session, services, permission="can_manage_offers"
    )
    if not staff or not callback.message:
        return
    await _render_working_hours(callback.message, session, provider_id=staff.provider_id)


@router.callback_query(F.data.startswith("p:wh:"))
async def provider_working_day(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    _user, staff = await _authorized_staff(
        callback, session, services, permission="can_manage_offers"
    )
    if not staff or not callback.message:
        return
    try:
        weekday = int((callback.data or "").split(":")[2])
    except (ValueError, IndexError):
        return
    if weekday not in range(7):
        return
    row = await session.scalar(
        select(ProviderWorkingHour).where(
            ProviderWorkingHour.provider_id == staff.provider_id,
            ProviderWorkingHour.weekday == weekday,
        )
    )
    opens = row.opens_minute if row else 600
    closes = row.closes_minute if row else 1380
    closed = row.is_closed if row else False
    await state.clear()
    await state.update_data(provider_id=staff.provider_id, working_weekday=weekday)
    await edit_or_send(
        callback.message,
        f"🕒 <b>{_WEEKDAYS[weekday]}</b>\n\n"
        f"الحالة: {'مغلق' if closed else 'مفتوح'}\n"
        f"الوقت: {format_clock_minutes(opens)}–{format_clock_minutes(closes)}",
        reply_markup=_markup(
            [
                [
                    InlineKeyboardButton(
                        text="✏️ تعديل وقت الدوام",
                        callback_data=f"p:whe:{weekday}",
                        style="primary",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="✅ فتح هذا اليوم" if closed else "⛔ إغلاق هذا اليوم",
                        callback_data=f"p:whc:{weekday}:{0 if closed else 1}",
                        style="success" if closed else "danger",
                    )
                ],
                [InlineKeyboardButton(text="↩️ ساعات العمل", callback_data="provider:working_hours")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("p:whe:"))
async def provider_working_edit(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    _user, staff = await _authorized_staff(
        callback, session, services, permission="can_manage_offers"
    )
    if not staff or not callback.message:
        return
    weekday = int((callback.data or "").split(":")[2])
    await state.clear()
    await state.update_data(provider_id=staff.provider_id, working_weekday=weekday)
    await state.set_state(ProviderWorkingHoursStates.opens_at)
    await edit_or_send(callback.message, "اكتب وقت بداية الدوام بصيغة 24 ساعة، مثال: <code>10:00</code>")


@router.message(ProviderWorkingHoursStates.opens_at)
async def provider_working_open_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    _user, staff = await _staff_for_provider(
        session, services, message.from_user.id, int(data.get("provider_id") or 0)
    )
    if not staff or not staff.can_manage_offers:
        await state.clear()
        return
    try:
        opens = parse_clock_minutes(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(working_opens=opens)
    await state.set_state(ProviderWorkingHoursStates.closes_at)
    await message.answer("اكتب وقت نهاية الدوام، مثال: <code>23:00</code>")


@router.message(ProviderWorkingHoursStates.closes_at)
async def provider_working_close_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    services: Services,
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    _user, staff = await _staff_for_provider(
        session, services, message.from_user.id, int(data.get("provider_id") or 0)
    )
    if not staff or not staff.can_manage_offers:
        await state.clear()
        return
    try:
        closes = parse_clock_minutes(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await services.provider_operations.set_working_day(
        session,
        provider_id=staff.provider_id,
        weekday=int(data["working_weekday"]),
        opens_minute=int(data["working_opens"]),
        closes_minute=closes,
        is_closed=False,
    )
    await state.clear()
    await message.answer(
        "تم تحديث ساعات العمل ✅",
        reply_markup=_markup(
            [[InlineKeyboardButton(text="🕒 ساعات العمل", callback_data="provider:working_hours")]]
        ),
    )


@router.callback_query(F.data.startswith("p:whc:"))
async def provider_working_toggle_closed(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    _user, staff = await _authorized_staff(
        callback, session, services, permission="can_manage_offers"
    )
    if not staff or not callback.message:
        return
    _, _, weekday_text, closed_text = (callback.data or "").split(":")
    weekday, closed = int(weekday_text), bool(int(closed_text))
    current = await session.scalar(
        select(ProviderWorkingHour).where(
            ProviderWorkingHour.provider_id == staff.provider_id,
            ProviderWorkingHour.weekday == weekday,
        )
    )
    await services.provider_operations.set_working_day(
        session,
        provider_id=staff.provider_id,
        weekday=weekday,
        opens_minute=current.opens_minute if current else 600,
        closes_minute=current.closes_minute if current else 1380,
        is_closed=closed,
    )
    await _render_working_hours(callback.message, session, provider_id=staff.provider_id)


_KIND_LABELS = {
    ProviderInboxKind.PAYMENT_PROOF.value: "💳 وصل دفع",
    ProviderInboxKind.STUDENT_ACTIVATION_EMAIL.value: "✉️ إيميل تفعيل",
    ProviderInboxKind.STUDENT_CODE_RELAY.value: "🔑 رمز من الطالب",
    ProviderInboxKind.LOGOUT_PROOF.value: "🚪 إثبات خروج",
    ProviderInboxKind.WARRANTY.value: "🛠 ضمان",
    ProviderInboxKind.OTP_MANUAL_REVIEW.value: "🔐 OTP يدوي",
}


async def _render_inbox(
    message: Message,
    session: AsyncSession,
    *,
    provider_id: int,
) -> None:
    items = list(
        (
            await session.scalars(
                select(ProviderInboxItem)
                .where(
                    ProviderInboxItem.provider_id == provider_id,
                    ProviderInboxItem.status.in_(
                        [
                            ProviderInboxItemStatus.NEW.value,
                            ProviderInboxItemStatus.OPENED.value,
                            ProviderInboxItemStatus.IN_PROGRESS.value,
                            ProviderInboxItemStatus.ESCALATED.value,
                        ]
                    ),
                )
                .order_by(ProviderInboxItem.created_at.desc())
                .limit(30)
            )
        ).all()
    )
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        label = _KIND_LABELS.get(item.kind, "📨 طلب")
        urgent = "⚠️ " if item.priority in {"urgent", "high"} else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{urgent}{label} #{item.id}",
                    callback_data=f"p:in:{item.id}",
                    style="danger" if urgent else "primary",
                )
            ]
        )
    if not rows:
        rows.append([InlineKeyboardButton(text="✅ لا توجد عناصر معلقة", callback_data="provider:inbox")])
    rows.append([InlineKeyboardButton(text="↩️ لوحة المنصة", callback_data=f"provider:select:{provider_id}")])
    await edit_or_send(
        message,
        "📥 <b>مركز المعالجة</b>\n\n"
        f"العناصر النشطة: <b>{len(items)}</b>\n"
        "تختفي العناصر من البريد النشط بعد معالجتها وتبقى محفوظة في السجل.",
        reply_markup=_markup(rows),
    )


@router.callback_query(F.data == "provider:inbox")
async def provider_inbox(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    _user, staff = await _authorized_staff(callback, session, services, permission="can_support")
    if not staff or not callback.message:
        return
    await _render_inbox(callback.message, session, provider_id=staff.provider_id)


@router.callback_query(F.data.startswith("p:in:"))
async def provider_inbox_item(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    user, staff = await _authorized_staff(callback, session, services, permission="can_support")
    if not staff or not callback.message or not user:
        return
    item = await session.get(ProviderInboxItem, int((callback.data or "").split(":")[2]))
    if not item or item.provider_id != staff.provider_id:
        await callback_notice(callback, "عنصر غير موجود أو غير مصرح", show_alert=True)
        return
    if item.status == ProviderInboxStatus.NEW.value:
        await services.provider_operations.transition_inbox(
            session,
            item_id=item.id,
            provider_id=staff.provider_id,
            actor_user_id=user.id,
            target_status=ProviderInboxStatus.OPENED.value,
        )
    rows: list[list[InlineKeyboardButton]] = []
    if item.file_id:
        rows.append([InlineKeyboardButton(text="🖼 عرض المرفق", callback_data=f"p:inf:{item.id}")])
    if item.kind == ProviderInboxKind.STUDENT_ACTIVATION_EMAIL.value:
        rows.extend(
            [
                [InlineKeyboardButton(text="🔑 طلب رمز من الطالب", callback_data=f"p:incr:{item.id}", style="primary")],
                [InlineKeyboardButton(text="✅ تم التفعيل بنجاح", callback_data=f"p:inac:{item.id}", style="success")],
            ]
        )
    elif item.kind == ProviderInboxKind.STUDENT_CODE_RELAY.value:
        rows.append([InlineKeyboardButton(text="👁 عرض الرمز مرة واحدة", callback_data=f"p:incs:{item.id}", style="danger")])
    elif item.kind == ProviderInboxKind.LOGOUT_PROOF.value:
        rows.extend(
            [
                [InlineKeyboardButton(text="✅ تأكيد تسجيل الخروج", callback_data=f"p:inlo:{item.id}:1", style="success")],
                [InlineKeyboardButton(text="❌ الإثبات غير كافٍ", callback_data=f"p:inlo:{item.id}:0", style="danger")],
            ]
        )
    elif item.kind == ProviderInboxKind.WARRANTY.value and item.source_id:
        rows.extend(
            [
                [InlineKeyboardButton(text="✅ السماح بسحب كود جديد", callback_data=f"p:warotp:{item.source_id}", style="success")],
                [InlineKeyboardButton(text="🔄 تعويض بحساب جديد", callback_data=f"p:warrep:{item.source_id}", style="primary")],
                [InlineKeyboardButton(text="💬 رد نصي للمستخدم", callback_data=f"p:wartext:{item.source_id}", style="primary")],
            ]
        )
    if item.kind != ProviderInboxKind.WARRANTY.value:
        rows.extend(
            [
                [InlineKeyboardButton(text="✅ معالجة وإغلاق", callback_data=f"p:inrs:{item.id}", style="success")],
                [InlineKeyboardButton(text="❌ رفض/مشكلة", callback_data=f"p:inrj:{item.id}", style="danger")],
            ]
        )
    else:
        rows.append(
            [InlineKeyboardButton(
                text="⏳ تبقى مفتوحة حتى تأكيد الطالب",
                callback_data="noop",
            )]
        )
    rows.append([InlineKeyboardButton(text="↩️ البريد", callback_data="provider:inbox")])
    await edit_or_send(
        callback.message,
        f"{_KIND_LABELS.get(item.kind, '📨 طلب')}\n\n"
        f"الرقم: <code>#{item.id}</code>\n"
        f"العنوان: <b>{safe(item.title)}</b>\n"
        f"الحالة: <b>{safe(item.status)}</b>\n"
        f"الملخص: {safe(item.summary)}",
        reply_markup=_markup(rows),
    )


@router.callback_query(F.data.startswith("p:inf:"))
async def provider_inbox_file(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    _user, staff = await _authorized_staff(callback, session, services, permission="can_support")
    if not staff or not callback.message:
        return
    item = await session.get(ProviderInboxItem, int((callback.data or "").split(":")[2]))
    if not item or item.provider_id != staff.provider_id or not item.file_id:
        return
    try:
        await callback.message.answer_photo(item.file_id, caption=f"مرفق عنصر البريد #{item.id}")
    except Exception:
        await callback.message.answer_document(item.file_id, caption=f"مرفق عنصر البريد #{item.id}")


async def _generic_transition(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
    *,
    target: str,
) -> None:
    user, staff = await _authorized_staff(callback, session, services, permission="can_support")
    if not staff or not callback.message or not user:
        return
    item_id = int((callback.data or "").split(":")[2])
    try:
        await services.provider_operations.transition_inbox(
            session,
            item_id=item_id,
            provider_id=staff.provider_id,
            actor_user_id=user.id,
            target_status=target,
        )
    except ValueError as exc:
        await callback_notice(callback, str(exc), show_alert=True)
        return
    await _render_inbox(callback.message, session, provider_id=staff.provider_id)


@router.callback_query(F.data.startswith("p:inrs:"))
async def provider_inbox_resolve(callback: CallbackQuery, session: AsyncSession, services: Services) -> None:
    await callback.answer()
    await _generic_transition(callback, session, services, target=ProviderInboxStatus.RESOLVED.value)


@router.callback_query(F.data.startswith("p:inrj:"))
async def provider_inbox_reject(callback: CallbackQuery, session: AsyncSession, services: Services) -> None:
    await callback.answer()
    await _generic_transition(callback, session, services, target=ProviderInboxStatus.REJECTED.value)


@router.callback_query(F.data.startswith("p:incr:"))
async def provider_request_student_code(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    user, staff = await _authorized_staff(callback, session, services, permission="can_manage_inventory")
    if not staff or not callback.message or not user:
        return
    item = await session.get(ProviderInboxItem, int((callback.data or "").split(":")[2]))
    if not item or item.provider_id != staff.provider_id or not item.source_id:
        return
    request = await services.provider_operations.request_student_code(
        session,
        activation_request_id=item.source_id,
        provider_id=staff.provider_id,
        actor_user_id=user.id,
    )
    student = await session.get(User, request.user_id)
    if student:
        await services.notifications.send_user(
            session,
            student,
            "مطلوب رمز التفعيل",
            "تم إرسال رمز إلى إيميلك. أرسله داخل البوت لإكمال التفعيل.",
            reply_markup=_markup(
                [[InlineKeyboardButton(text="✉️ إرسال الرمز", callback_data=f"act:code:{request.id}", style="primary")]]
            ),
            idempotency_key=f"activation-code-request:{request.id}:{request.code_requested_at.isoformat()}",
        )
    await callback_notice(callback, "تم طلب الرمز من الطالب", show_alert=True)


@router.callback_query(F.data.startswith("p:inac:"))
async def provider_activation_completed(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    user, staff = await _authorized_staff(callback, session, services, permission="can_manage_inventory")
    if not staff or not callback.message or not user:
        return
    item = await session.get(ProviderInboxItem, int((callback.data or "").split(":")[2]))
    if not item or item.provider_id != staff.provider_id or not item.source_id:
        return
    request = await session.scalar(
        select(StudentActivationRequest).where(
            StudentActivationRequest.id == item.source_id,
            StudentActivationRequest.provider_id == staff.provider_id,
        ).with_for_update()
    )
    if not request:
        return
    request.status = ActivationRequestStatus.ACTIVATED.value
    request.activated_at = datetime.now(UTC)
    request.completed_by_user_id = user.id
    await services.provider_operations.transition_inbox(
        session,
        item_id=item.id,
        provider_id=staff.provider_id,
        actor_user_id=user.id,
        target_status=ProviderInboxStatus.RESOLVED.value,
    )
    student = await session.get(User, request.user_id)
    if student:
        await services.notifications.send_user(
            session,
            student,
            "تم تفعيل الخدمة ✅",
            "تم تفعيل الخدمة على إيميلك، يمكنك الدخول الآن!",
            idempotency_key=f"activation-complete:{request.id}",
        )
    await _render_inbox(callback.message, session, provider_id=staff.provider_id)


@router.callback_query(F.data.startswith("p:incs:"))
async def provider_consume_student_code(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    user, staff = await _authorized_staff(callback, session, services, permission="can_manage_inventory")
    if not staff or not user:
        return
    item = await session.get(ProviderInboxItem, int((callback.data or "").split(":")[2]))
    if not item or item.provider_id != staff.provider_id or not item.source_id:
        return
    try:
        code = await services.provider_operations.consume_student_code(
            session, relay_id=item.source_id, provider_id=staff.provider_id
        )
        await services.provider_operations.transition_inbox(
            session,
            item_id=item.id,
            provider_id=staff.provider_id,
            actor_user_id=user.id,
            target_status=ProviderInboxStatus.RESOLVED.value,
            note="تم عرض الرمز للموظف مرة واحدة",
        )
    except ValueError as exc:
        await callback_notice(callback, str(exc), show_alert=True)
        return
    await callback_notice(callback, f"رمز الطالب: {code}", show_alert=True)


@router.callback_query(F.data.startswith("p:inlo:"))
async def provider_confirm_logout(
    callback: CallbackQuery,
    session: AsyncSession,
    services: Services,
) -> None:
    await callback.answer()
    user, staff = await _authorized_staff(callback, session, services, permission="can_manage_inventory")
    if not staff or not callback.message or not user:
        return
    parts = (callback.data or "").split(":")
    item = await session.get(ProviderInboxItem, int(parts[2]))
    accepted = bool(int(parts[3]))
    if not item or item.provider_id != staff.provider_id or not item.source_id:
        return
    await services.provider_operations.confirm_logout_proof(
        session,
        proof_id=item.source_id,
        provider_id=staff.provider_id,
        actor_user_id=user.id,
        accepted=accepted,
    )
    await services.provider_operations.transition_inbox(
        session,
        item_id=item.id,
        provider_id=staff.provider_id,
        actor_user_id=user.id,
        target_status=(
            ProviderInboxStatus.RESOLVED.value if accepted else ProviderInboxStatus.REJECTED.value
        ),
    )
    await _render_inbox(callback.message, session, provider_id=staff.provider_id)
