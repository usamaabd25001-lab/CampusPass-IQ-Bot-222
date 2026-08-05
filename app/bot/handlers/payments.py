from __future__ import annotations

import hashlib
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import (
    manual_payment_keyboard,
    payment_confirm_keyboard,
    payment_review_keyboard,
)
from app.bot.states import PaymentProofStates, PaymentReviewStates
from app.bot.ui import edit_or_send, callback_notice
from app.core.config import Settings
from app.core.utils import normalize_phone, parse_money, safe
from app.db.models import (
    EvidenceAsset,
    FriendGroup,
    FriendGroupMember,
    OrderStatus,
    PaymentMethod,
    PaymentProofStatus,
    ProviderInboxItem,
    ProviderPaymentMethodConfig,
    ProviderOfferFulfillmentProfile,
    User,
)
from app.domain.provider_operations import ProviderInboxKind, ProviderInboxStatus
from app.services.container import Services

router = Router(name="payments")
logger = logging.getLogger(__name__)


@router.callback_query(F.data.startswith("paymethod:"))
async def choose_payment_method(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.message:
        return
    _, order_id_text, method_id_text = callback.data.split(":")
    order = await services.orders.get(session, int(order_id_text))
    method = await session.get(PaymentMethod, int(method_id_text))
    if not order or not method:
        await edit_or_send(callback.message, "طريقة الدفع أو الطلب غير موجود.")
        return
    if not callback.from_user or order.user.telegram_id != callback.from_user.id:
        await edit_or_send(callback.message, "غير مصرح.")
        return
    try:
        await services.orders.set_payment_method(session, order, method)
    except (ValueError, PermissionError) as exc:
        await edit_or_send(callback.message, str(exc))
        return
    if method.method_type == "mastercard":
        if not services.mastercard.enabled or not await services.features.enabled(
            session, "mastercard", False
        ):
            await edit_or_send(callback.message, "الدفع بالبطاقة مفعّل لكنه ينتظر إدخال بيانات بوابة الدفع من الإدارة.")
            return
        base = settings.public_base_url.rstrip("/")
        if not base:
            await edit_or_send(callback.message, "يجب إعداد PUBLIC_BASE_URL قبل تشغيل الدفع بالبطاقة.")
            return
        try:
            checkout = await services.mastercard.create_checkout(
                order.public_id,
                order.total_iqd,
                f"{base}/payments/return/{order.public_id}",
                f"{base}/webhooks/payments/mastercard",
            )
            await services.payments.register_checkout(session, order, checkout)
        except Exception as exc:
            logger.exception("Checkout creation failed: %s", exc)
            await edit_or_send(callback.message, "تعذر إنشاء جلسة الدفع. تواصل مع الدعم.")
            return
        await edit_or_send(callback.message, 
            f"💳 ادفع عبر الصفحة الآمنة للطلب <code>{order.public_id}</code>:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="فتح صفحة الدفع", url=checkout.checkout_url, style="primary"
                        )
                    ]
                ]
            ),
        )
        return
    instructions = method.instructions or settings.default_payment_instructions
    wallet_balance = await services.wallets.balance(session, "user", order.user_id)
    wallet_fee_used = max(
        0, int((order.payment_snapshot or {}).get("wallet_fee_deduction_iqd", 0) or 0)
    )
    await edit_or_send(callback.message, 
        f"💳 <b>{safe(method.name)}</b>\n\n"
        f"المستلم: <code>{safe(method.recipient)}</code>\n"
        f"سعر الخدمة: <b>{order.subtotal_iqd:,} د.ع</b>\n"
        f"رسوم البوت: <b>{order.service_fee_iqd:,} د.ع</b>\n"
        f"خصم رسوم البوت من المحفظة: <b>-{wallet_fee_used:,} د.ع</b>\n"
        f"المبلغ المطلوب تحويله: <b>{order.total_iqd:,} د.ع</b>\n"
        f"رصيد المحفظة المتبقي: <b>{wallet_balance:,} د.ع</b>\n"
        f"رقم الطلب: <code>{order.public_id}</code>\n\n"
        f"{safe(instructions, '')}\n\n"
        "إذا كانت جهة الدفع لا تسمح بالمبلغ الدقيق، يمكنك إرسال مبلغ أعلى، "
        "وسيُحفظ الفرق تلقائيًا في محفظتك بعد تأكيد الوصل. "
        "المبلغ الناقص لا يُقبل؛ المحفظة تغطي رسوم البوت كاملة فقط عند توفرها.\n\n"
        "بعد التحويل اضغط الزر وأرسل صورة الإيصال.",
        reply_markup=manual_payment_keyboard(order.id),
    )


@router.callback_query(F.data.startswith("proof:guide:"))
async def proof_guide(
    callback: CallbackQuery, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    order_id = int((callback.data or "").split(":")[2])
    order = await services.orders.get(session, order_id)
    if not order or order.user.telegram_id != callback.from_user.id:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    config = None
    if order.payment_method_id:
        config = await session.scalar(
            select(ProviderPaymentMethodConfig).where(
                ProviderPaymentMethodConfig.payment_method_id == order.payment_method_id
            )
        )
    text = (
        config.proof_guide_text
        if config and config.proof_guide_text
        else "بعد نجاح التحويل افتح تفاصيل العملية أو رسالة النجاح وخذ لقطة شاشة واضحة يظهر فيها المبلغ والرقم أو المرجع."
    )
    if config and config.proof_guide_file_id:
        try:
            await callback.message.answer_photo(
                config.proof_guide_file_id,
                caption=f"❓ <b>كيف أستخرج الوصل؟</b>\n\n{safe(text)}",
            )
            return
        except Exception:
            logger.debug("Could not send payment proof guide image", exc_info=True)
    await edit_or_send(
        callback.message,
        f"❓ <b>كيف أستخرج الوصل؟</b>\n\n{safe(text)}",
        reply_markup=manual_payment_keyboard(order.id),
    )


@router.callback_query(F.data.startswith("proof:start:"))
async def proof_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, services: Services
) -> None:
    await callback.answer()
    order = await services.orders.get(session, int(callback.data.split(":")[2]))
    if not order or not callback.from_user or order.user.telegram_id != callback.from_user.id:
        await callback_notice(callback, "غير مصرح", show_alert=True)
        return
    method = order.payment_method
    allow_text = bool(method and method.method_type in {"balance", "mobile_credit", "credit"})
    await state.clear()
    await state.update_data(proof_order_id=order.id, proof_allow_text=allow_text)
    await state.set_state(PaymentProofStates.proof_file)
    if callback.message:
        prompt = "أرسل صورة التحويل أو ملف الإيصال الآن:"
        if allow_text:
            prompt += "\nيمكنك أيضًا كتابة تفاصيل التحويل إذا لم تتوفر صورة."
        await edit_or_send(callback.message, prompt)


@router.message(PaymentProofStates.proof_file)
async def proof_file(message: Message, state: FSMContext, settings: Settings) -> None:
    data = await state.get_data()
    if not data.get("proof_order_id"):
        await state.clear()
        await message.answer("انتهت جلسة رفع الوصل. افتح الطلب واضغط «رفعت التحويل» من جديد.")
        return
    photo_file_id = message.photo[-1].file_id if message.photo else None
    document_file_id = message.document.file_id if message.document else None
    file_unique_id = (
        message.photo[-1].file_unique_id
        if message.photo
        else message.document.file_unique_id
        if message.document
        else ""
    )
    file_fingerprint = (
        hashlib.sha256(f"telegram:{file_unique_id}".encode("utf-8")).hexdigest()
        if file_unique_id
        else None
    )
    text_note = (message.text or message.caption or "").strip()
    document_mime = (message.document.mime_type or "").lower() if message.document else ""
    document_size = int(message.document.file_size or 0) if message.document else 0
    photo_size = int(message.photo[-1].file_size or 0) if message.photo else 0
    size_bytes = document_size or photo_size
    allowed_document = bool(
        message.document
        and (
            document_mime.startswith("image/")
            or document_mime == "application/pdf"
        )
    )
    if message.document and not allowed_document:
        await message.answer("الملف غير مدعوم. أرسل صورة JPG/PNG/WebP أو ملف PDF للوصل.")
        return
    if size_bytes and size_bytes > int(settings.payment_proof_max_bytes):
        await message.answer(
            f"حجم الوصل كبير جدًا. الحد الأقصى {int(settings.payment_proof_max_bytes) // 1_000_000} MB."
        )
        return
    if (
        not photo_file_id
        and not (document_file_id and allowed_document)
        and not (data.get("proof_allow_text") and text_note)
    ):
        await message.answer("أرسل صورة واضحة للوصل. في دفع الرصيد فقط يمكن كتابة تفاصيل التحويل.")
        return
    await state.update_data(
        photo_file_id=photo_file_id,
        document_file_id=document_file_id if allowed_document else None,
        proof_file_type="photo" if photo_file_id else ("document" if document_file_id else None),
        proof_original_name=(message.document.file_name or "")[:255] if message.document else "",
        proof_mime_type=document_mime or ("image/jpeg" if message.photo else None),
        proof_size_bytes=size_bytes or None,
        proof_file_fingerprint=file_fingerprint,
        proof_note=text_note[:1000] if text_note else "",
    )
    await state.set_state(PaymentProofStates.sender_phone)
    await message.answer("اكتب رقم الهاتف أو الحساب الذي حولت منه:")


@router.message(PaymentProofStates.sender_phone)
async def proof_sender(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    normalized = normalize_phone(value)
    if not normalized and len(value) < 5:
        await message.answer("اكتب رقمًا أو معرف حساب واضحًا.")
        return
    await state.update_data(sender_phone=normalized or value[:30])
    await state.set_state(PaymentProofStates.amount)
    await message.answer("اكتب المبلغ الذي حولته بالدينار العراقي:")


@router.message(PaymentProofStates.amount)
async def proof_amount(message: Message, state: FSMContext) -> None:
    amount = parse_money(message.text or "")
    if not amount:
        await message.answer("اكتب مبلغًا صحيحًا بالأرقام.")
        return
    await state.update_data(claimed_amount_iqd=amount)
    await state.set_state(PaymentProofStates.reference)
    await message.answer("اكتب رقم العملية، أو اكتب: لا يوجد")


@router.message(PaymentProofStates.reference)
async def proof_reference(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    try:
        proof_order_id = int(data.get("proof_order_id") or 0)
    except (TypeError, ValueError):
        proof_order_id = 0
    order = await services.orders.get(session, proof_order_id) if proof_order_id else None
    if not order or order.user.telegram_id != message.from_user.id:
        await state.clear()
        await message.answer("تعذر ربط الوصل بالطلب. افتح الطلب وابدأ رفع الوصل من جديد.")
        return
    required_fields = ("sender_phone", "claimed_amount_iqd")
    if any(data.get(key) in {None, ""} for key in required_fields):
        await state.clear()
        await message.answer("بيانات الوصل غير مكتملة. افتح الطلب وابدأ العملية من جديد.")
        return
    reference_text = (message.text or "").strip()
    reference = None if reference_text in {"لا يوجد", "لايوجد", "-"} else reference_text[:120]
    try:
        proof = await services.payments.submit_proof(
            session,
            order,
            data.get("photo_file_id"),
            data.get("document_file_id"),
            data["sender_phone"],
            int(data["claimed_amount_iqd"]),
            reference,
            data.get("proof_note", ""),
            file_fingerprint=data.get("proof_file_fingerprint"),
        )
        evidence_asset = None
        file_id = data.get("photo_file_id") or data.get("document_file_id")
        if file_id:
            evidence_asset = await services.evidence.register_telegram(
                session,
                order.user,
                str(file_id),
                str(data.get("proof_file_type") or "document"),
                "payment_proof",
                provider_id=order.provider_id,
                order_id=order.id,
                original_name=str(data.get("proof_original_name") or ""),
                mime_type=data.get("proof_mime_type"),
                size_bytes=data.get("proof_size_bytes"),
            )
            proof.evidence_asset_id = evidence_asset.id
            proof.photo_file_id = None
            proof.document_file_id = None
            await session.flush()
        await services.provider_operations.enqueue_inbox(
            session,
            provider_id=order.provider_id,
            kind=ProviderInboxKind.PAYMENT_PROOF.value,
            idempotency_key=f"payment-proof:{proof.id}",
            title=f"وصل دفع للطلب {order.public_id}",
            summary=(
                f"المطلوب {order.total_iqd:,} د.ع — صرّح الطالب بتحويل "
                f"{proof.claimed_amount_iqd:,} د.ع"
            ),
            order_id=order.id,
            user_id=order.user_id,
            source_type="payment_proof",
            source_id=proof.id,
            file_id=str(file_id) if file_id else None,
            amount_iqd=proof.claimed_amount_iqd,
            priority="high",
        )
    except ValueError as exc:
        await message.answer(str(exc))
        await state.clear()
        return
    await state.clear()
    received_text = await services.templates.render(
        session, "payment.received", {"order_id": order.public_id}
    )
    await message.answer(received_text)
    profile = order.user.profile
    reviewer_text = (
        "💳 <b>طلب دفع جديد</b>\n\n"
        f"رقم الطلب: <code>{order.public_id}</code>\n"
        f"الطالب: {safe(profile.full_name if profile else order.user.telegram_name)}\n"
        f"العرض: {safe(order.offer.title)}\n"
        f"المطلوب: {order.total_iqd:,} د.ع\n"
        f"المبلغ المصرح: {proof.claimed_amount_iqd:,} د.ع\n"
        f"المحول: <code>{safe(proof.sender_phone)}</code>\n"
        f"المرجع: <code>{safe(proof.reference, 'لا يوجد')}</code>"
    )
    reviewers = await services.notifications.provider_reviewer_ids(session, order.provider_id)
    targets = set(reviewers) | set(settings.admin_ids)
    for target in targets:
        try:
            if evidence_asset:
                await services.evidence.send(
                    session,
                    evidence_asset,
                    None,
                    target,
                    reviewer_text,
                    reply_markup=payment_review_keyboard(order.id, proof.claimed_amount_iqd),
                )
            else:
                await message.bot.send_message(
                    target,
                    reviewer_text + f"\n\nتفاصيل كتابية: {safe(proof.note, 'لا توجد')}",
                    reply_markup=payment_review_keyboard(order.id, proof.claimed_amount_iqd),
                )
        except Exception as exc:
            logger.warning("Could not notify reviewer %s: %s", target, exc)


@router.callback_query(F.data.startswith("review:confirm:"))
async def review_confirm_prompt(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    try:
        order_id = int((callback.data or "").split(":")[2])
    except (ValueError, IndexError):
        await callback_notice(callback, "بيانات الطلب غير صحيحة", show_alert=True)
        return
    order = await services.orders.get(session, order_id)
    actor = await services.users.get_or_create(
        session,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name or "Telegram User",
    )
    if not order or not await services.payments.can_review(
        session, actor, order, settings.is_admin(callback.from_user.id)
    ):
        await callback_notice(callback, "غير مصرح بمراجعة هذا الدفع", show_alert=True)
        return
    proof = await services.payments.latest_proof(session, order_id)
    if not proof or proof.status != PaymentProofStatus.PENDING.value:
        await callback_notice(callback, "تمت معالجة الوصل أو لم يعد متاحاً", show_alert=True)
        return
    amount = int(proof.claimed_amount_iqd)
    await edit_or_send(
        callback.message,
        "هل راجعت الحساب المستلم وتأكدت من وصول المبلغ الفعلي؟",
        reply_markup=payment_confirm_keyboard(order_id, amount),
    )


@router.callback_query(F.data.startswith("review:final:"))
async def review_confirm_final(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    actor = await services.users.get_or_create(
        session,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name,
    )
    order_id = int(callback.data.split(":")[2])
    proof = await services.payments.latest_proof(session, order_id)
    try:
        order, _payment = await services.payments.confirm(
            session, order_id, actor, settings.is_admin(callback.from_user.id)
        )
        friend_member = await services.friend_packages.member_for_order(
            session, order.id
        )
        fulfillment_profile = await session.scalar(
            select(ProviderOfferFulfillmentProfile).where(
                ProviderOfferFulfillmentProfile.offer_id == order.offer_id
            )
        )
        if friend_member is not None:
            group = await session.get(FriendGroup, friend_member.group_id)
            progress = await services.friend_packages.progress(session, friend_member.group_id)
            await services.notifications.send_user(
                session,
                order.user,
                "تم تأكيد دفعتك في باقة الأصدقاء ✅",
                (
                    f"{progress.status_text}\n"
                    "سيُرسل الحساب تلقائياً لجميع الأعضاء بعد اكتمال العدد."
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="👥 تحديث حالة الأصدقاء",
                        callback_data=f"friend:progress:{friend_member.group_id}",
                        style="primary",
                    )
                ]]),
                idempotency_key=f"friend-payment-confirmed:{friend_member.id}",
            )
        elif fulfillment_profile and fulfillment_profile.student_email_required:
            await services.orders.change_status(
                session,
                order,
                OrderStatus.WAITING_FULFILLMENT.value,
                actor_user_id=actor.id,
                note="بانتظار إيميل الطالب للتفعيل",
            )
            await services.notifications.send_user(
                session,
                order.user,
                "أرسل إيميل التفعيل",
                "تم تأكيد الدفع. أرسل الإيميل الذي تريد تفعيل الخدمة عليه.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[
                        InlineKeyboardButton(
                            text="✉️ إرسال إيميل التفعيل",
                            callback_data=f"act:email:{order.id}",
                            style="primary",
                        )
                    ]]
                ),
                idempotency_key=f"activation-email-prompt:{order.id}",
            )
        else:
            await services.fulfillment.fulfill(session, order)
        if proof is not None:
            inbox_item = await session.scalar(
                select(ProviderInboxItem).where(
                    ProviderInboxItem.provider_id == order.provider_id,
                    ProviderInboxItem.source_type == "payment_proof",
                    ProviderInboxItem.source_id == proof.id,
                )
            )
            if inbox_item is not None:
                await services.provider_operations.transition_inbox(
                    session,
                    item_id=inbox_item.id,
                    provider_id=order.provider_id,
                    actor_user_id=actor.id,
                    target_status=ProviderInboxStatus.RESOLVED.value,
                    note="تم تأكيد استلام المبلغ",
                )
    except (ValueError, PermissionError) as exc:
        await edit_or_send(callback.message, f"تعذر التأكيد: {exc}")
        return
    approved_text = await services.templates.render(
        session, "payment.approved", {"order_id": order.public_id}
    )
    wallet_used = int((_payment.raw_payload or {}).get("wallet_used_iqd", 0) or 0)
    wallet_credit = int((_payment.raw_payload or {}).get("wallet_credit_iqd", 0) or 0)
    wallet_note = ""
    if wallet_credit:
        wallet_note = (
            f"\n\n💰 دفعت مبلغًا أعلى من المطلوب. تم حفظ <b>{wallet_credit:,} د.ع</b> "
            "في محفظتك داخل قسم حسابك لاستخدامه في الاشتراكات القادمة."
        )
    elif wallet_used:
        wallet_note = (
            f"\n\n💰 تم استخدام <b>{wallet_used:,} د.ع</b> من محفظتك لتغطية رسوم البوت تلقائياً."
        )
    open_callback = (
        f"admin:order:{order.id}"
        if settings.is_admin(callback.from_user.id)
        else f"provider:order:{order.id}"
    )
    await edit_or_send(
        callback.message,
        approved_text + wallet_note,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="🔎 فتح الطلب",
                    callback_data=open_callback,
                    style="primary",
                )
            ]]
        ),
    )


@router.callback_query(F.data.startswith("review:reject:"))
async def review_reject_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    try:
        order_id = int((callback.data or "").split(":")[2])
    except (ValueError, IndexError):
        await callback_notice(callback, "بيانات الطلب غير صحيحة", show_alert=True)
        return
    order = await services.orders.get(session, order_id)
    actor = await services.users.get_or_create(
        session,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name or "Telegram User",
    )
    if not order or not await services.payments.can_review(
        session, actor, order, settings.is_admin(callback.from_user.id)
    ):
        await callback_notice(callback, "غير مصرح بمراجعة هذا الدفع", show_alert=True)
        return
    if order.status != OrderStatus.PAYMENT_REVIEW.value:
        await callback_notice(callback, "تمت معالجة هذا الطلب سابقاً", show_alert=True)
        return
    await state.clear()
    await state.update_data(reject_order_id=order_id)
    await state.set_state(PaymentReviewStates.reject_reason)
    await edit_or_send(callback.message, "اكتب سبب رفض الدفع، مثال: المبلغ غير مطابق:")


@router.message(PaymentReviewStates.reject_reason)
async def review_reject_reason(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not message.from_user:
        return
    reason = (message.text or "").strip()
    if len(reason) < 3:
        await message.answer("اكتب سببًا واضحًا.")
        return
    actor = await services.users.get_or_create(
        session,
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
    )
    data = await state.get_data()
    reject_order_id = int(data["reject_order_id"])
    proof = await services.payments.latest_proof(session, reject_order_id)
    try:
        order = await services.payments.reject(
            session,
            reject_order_id,
            actor,
            settings.is_admin(message.from_user.id),
            reason,
        )
    except (ValueError, PermissionError) as exc:
        await message.answer(str(exc))
        await state.clear()
        return
    if proof is not None:
        inbox_item = await session.scalar(
            select(ProviderInboxItem).where(
                ProviderInboxItem.provider_id == order.provider_id,
                ProviderInboxItem.source_type == "payment_proof",
                ProviderInboxItem.source_id == proof.id,
            )
        )
        if inbox_item is not None:
            await services.provider_operations.transition_inbox(
                session,
                item_id=inbox_item.id,
                provider_id=order.provider_id,
                actor_user_id=actor.id,
                target_status=ProviderInboxStatus.REJECTED.value,
                note=reason,
            )
    await state.clear()
    user = await session.get(User, order.user_id)
    if user:
        await services.notifications.send_user(
            session,
            user,
            "تم رفض إثبات الدفع",
            f"الطلب: <code>{order.public_id}</code>\nالسبب: {safe(reason)}",
        )
    await message.answer("تم رفض الإثبات وإبلاغ المستخدم.")
