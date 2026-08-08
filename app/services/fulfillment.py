from __future__ import annotations

import json
import logging
import os
import socket
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import order_actions_keyboard
from app.core.config import Settings
from app.core.security import SecretBox
from app.db.models import (
    DeliveryJob,
    DeliveryJobStatus,
    DeliveryType,
    EmailAccount,
    FriendGroup,
    FriendGroupMember,
    FriendGroupStatus,
    FriendMemberStatus,
    InventoryItem,
    InventoryStatus,
    Offer,
    Order,
    OrderStatus,
    PurchaseReservation,
    ReservationStatus,
    User,
    WarrantyClaim,
    WarrantyClaimStatus,
    WarrantyReplacement,
)
from app.services.activation_guides import ActivationGuideService
from app.services.email_codes import EmailCodeService
from app.services.features import FeatureService
from app.services.notifications import NotificationService
from app.services.orders import OrderService
from app.services.student_subscriptions import StudentSubscriptionService

logger = logging.getLogger(__name__)


class FulfillmentService:
    def __init__(
        self,
        settings: Settings,
        secrets: SecretBox,
        orders: OrderService,
        emails: EmailCodeService,
        features: FeatureService,
        notifications: NotificationService,
        student_subscriptions: StudentSubscriptionService,
        activation_guides: ActivationGuideService,
    ) -> None:
        self.settings = settings
        self.secrets = secrets
        self.orders = orders
        self.emails = emails
        self.features = features
        self.notifications = notifications
        self.student_subscriptions = student_subscriptions
        self.activation_guides = activation_guides
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"

    async def fulfill(self, session: AsyncSession, order: Order) -> None:
        loaded_order = await self.orders.get(session, order.id)
        if loaded_order:
            order = loaded_order
        offer = await session.get(Offer, order.offer_id)
        user = await session.get(User, order.user_id)
        if not offer or not user:
            raise ValueError("بيانات الطلب ناقصة")

        await self.orders.confirm_reservation(session, order)
        await self.student_subscriptions.mark_payment_approved(session, order)

        if offer.delivery_type in {
            DeliveryType.INVENTORY_CODE.value,
            DeliveryType.INVENTORY_ACCOUNT.value,
        }:
            await self._enqueue_inventory_delivery(session, order, offer, user)
            return

        if offer.delivery_type == DeliveryType.EMAIL_CODE.value:
            enabled = self.settings.feature_email_codes and await self.features.enabled(
                session, "email_codes", False
            )
            if not enabled:
                raise ValueError("نظام الإيميلات غير مفعل")
            await self.emails.reserve(session, order, offer)
            await self.notifications.send_user(
                session,
                user,
                "جاري تجهيز رمز التحقق",
                (
                    f"تمت مصادقة الدفع للطلب <code>{order.public_id}</code>. "
                    "سيصلك الرمز فور وصول الرسالة المطابقة لهذا الطلب."
                ),
            )
            return

        await self.orders.change_status(
            session, order, OrderStatus.PROCESSING.value, note="الطلب يحتاج تنفيذ مزود الخدمة"
        )
        await self.notifications.send_user(
            session,
            user,
            "تمت مصادقة الدفع ✅",
            f"الطلب <code>{order.public_id}</code> قيد التنفيذ لدى مزود الخدمة.",
        )
        reviewer_ids = await self.notifications.provider_support_ids(session, order.provider_id)
        for telegram_id in reviewer_ids:
            try:
                await self.notifications.bot.send_message(
                    telegram_id,
                    (
                        "📦 طلب يحتاج تنفيذًا يدويًا\n"
                        f"رقم الطلب: {order.public_id}\n"
                        f"العرض: {offer.title}"
                    ),
                )
            except Exception as exc:
                logger.warning("Could not notify provider %s: %s", telegram_id, exc)

    async def _enqueue_inventory_delivery(
        self,
        session: AsyncSession,
        order: Order,
        offer: Offer,
        user: User,
    ) -> DeliveryJob:
        reservation = await session.scalar(
            select(PurchaseReservation).where(PurchaseReservation.order_id == order.id)
        )
        if not reservation or not reservation.inventory_item_id:
            await self.orders.change_status(
                session,
                order,
                OrderStatus.NEEDS_SUPPORT.value,
                note="لا يوجد حجز مخزون مرتبط بالطلب بعد الدفع",
            )
            raise ValueError("لا يوجد مورد محجوز لهذا الطلب")
        if reservation.status != ReservationStatus.CONFIRMED.value:
            raise ValueError("لم يتم تثبيت حجز المورد")

        existing = await session.scalar(
            select(DeliveryJob).where(DeliveryJob.idempotency_key == f"order:{order.id}:inventory")
        )
        if existing:
            return existing

        job = DeliveryJob(
            order_id=order.id,
            inventory_item_id=reservation.inventory_item_id,
            idempotency_key=f"order:{order.id}:inventory",
            status=DeliveryJobStatus.PENDING.value,
        )
        session.add(job)
        await self.orders.change_status(
            session,
            order,
            OrderStatus.WAITING_FULFILLMENT.value,
            note="تم إنشاء مهمة تسليم آمنة",
        )
        await self.notifications.send_user(
            session,
            user,
            "تم تأكيد الدفع ✅",
            (
                f"تم قبول الدفع للطلب <code>{order.public_id}</code>. "
                "راجع تعليمات التفعيل وثبّت قراءتها حتى يرسل البوت بيانات الحساب بصورة آمنة."
            ),
        )
        guide = await self.activation_guides.get_for_offer(session, offer.id)
        if guide and guide.show_before_delivery:
            await self.activation_guides.send_to_chat(
                self.notifications.bot,
                user.telegram_id,
                guide,
                order_id=order.id,
                include_acknowledgement=guide.acknowledgement_required,
            )
        await session.flush()
        return job

    def _format_inventory_payload(self, item: InventoryItem, raw_payload: str) -> str:
        if item.item_kind != "account":
            return f"{item.label or 'كود التفعيل'}:\n<code>{raw_payload}</code>"
        try:
            payload = json.loads(raw_payload)
        except (json.JSONDecodeError, TypeError):
            return f"{item.label or 'بيانات الاشتراك'}:\n<code>{raw_payload}</code>"
        if not isinstance(payload, dict):
            return f"{item.label or 'بيانات الاشتراك'}:\n<code>{raw_payload}</code>"
        lines: list[str] = []
        email = payload.get("login_email") or payload.get("email") or payload.get("username")
        password = payload.get("login_password") or payload.get("password")
        instructions = payload.get("instructions") or payload.get("activation_instructions")
        if email:
            lines.append(f"البريد/المستخدم: <code>{email}</code>")
        if password:
            lines.append(f"كلمة المرور: <code>{password}</code>")
        if instructions:
            lines.append(f"\nطريقة التفعيل:\n{instructions}")
        # Do not expose mailbox secrets, OAuth tokens, app passwords, or IMAP credentials.
        if not lines:
            lines.append(f"<code>{raw_payload}</code>")
        return "\n".join(lines)

    async def process_next_delivery(self, session: AsyncSession) -> bool:
        now = datetime.now(UTC)
        job = await session.scalar(
            select(DeliveryJob)
            .where(
                or_(
                    and_(
                        DeliveryJob.status == DeliveryJobStatus.PENDING.value,
                        DeliveryJob.next_attempt_at <= now,
                    ),
                    and_(
                        DeliveryJob.status == DeliveryJobStatus.PROCESSING.value,
                        DeliveryJob.lease_expires_at.is_not(None),
                        DeliveryJob.lease_expires_at <= now,
                    ),
                )
            )
            .order_by(DeliveryJob.created_at, DeliveryJob.id)
            .with_for_update(skip_locked=True)
        )
        if not job:
            return False

        job.status = DeliveryJobStatus.PROCESSING.value
        job.attempts += 1
        job.started_at = job.started_at or now
        job.lease_owner = self.worker_id
        job.lease_expires_at = now + timedelta(seconds=self.settings.delivery_lease_seconds)
        job.last_error = None
        await session.commit()

        order = await self.orders.get(session, job.order_id)
        item = (
            await session.get(InventoryItem, job.inventory_item_id)
            if job.inventory_item_id
            else None
        )
        if not order or not item:
            job = await session.get(DeliveryJob, job.id)
            if job:
                job.status = DeliveryJobStatus.FAILED.value
                job.lease_owner = None
                job.lease_expires_at = None
                job.last_error = "بيانات الطلب أو المخزون غير موجودة"
                await session.commit()
            return True

        guide = await self.activation_guides.get_for_offer(session, order.offer_id)
        if guide and guide.acknowledgement_required:
            acknowledged = await self.activation_guides.acknowledged(
                session, order_id=order.id, user_id=order.user_id
            )
            if not acknowledged:
                job = await session.get(DeliveryJob, job.id)
                if job:
                    job.status = DeliveryJobStatus.PENDING.value
                    job.lease_owner = None
                    job.lease_expires_at = None
                    job.last_error = "بانتظار تأكيد قراءة تعليمات التفعيل"
                    job.next_attempt_at = datetime.now(UTC) + timedelta(minutes=2)
                    await session.commit()
                return True

        raw_payload = self.secrets.decrypt(item.encrypted_payload)
        friend_member = None
        warranty_claim = None
        if job.job_type == "friend_group_delivery":
            friend_member = await session.scalar(
                select(FriendGroupMember).where(FriendGroupMember.order_id == order.id)
            )
        elif job.job_type == "warranty_replacement":
            replacement = await session.scalar(
                select(WarrantyReplacement).where(WarrantyReplacement.delivery_job_id == job.id)
            )
            if replacement:
                warranty_claim = await session.get(WarrantyClaim, replacement.claim_id)
        if warranty_claim is not None:
            body = (
                f"تم تفعيل الضمان وتعويضك بحساب جديد!\n"
                f"رقم المطالبة: <code>{warranty_claim.public_id}</code>\n"
                f"{self._format_inventory_payload(item, raw_payload)}\n\n"
                "جرّب تسجيل الدخول ثم أكد نجاح التفعيل من الأزرار أدناه."
            )
        elif friend_member is not None:
            body = (
                f"اكتمل عدد الأصدقاء وتم إرسال الحساب لجميع الأعضاء ✅\n"
                f"رقم الطلب: <code>{order.public_id}</code>\n"
                f"{self._format_inventory_payload(item, raw_payload)}\n\n"
                "هذا الحساب مخصص لأعضاء مجموعتك فقط."
            )
        else:
            body = (
                f"رقم الطلب: <code>{order.public_id}</code>\n"
                f"{self._format_inventory_payload(item, raw_payload)}\n\n"
                "احتفظ بالبيانات ولا تشاركها مع أي شخص."
            )
        allow_code = bool(
            await session.scalar(
                select(EmailAccount.id).where(
                    EmailAccount.provider_id == order.provider_id,
                    (EmailAccount.offer_id == order.offer_id) | (EmailAccount.offer_id.is_(None)),
                )
            )
        )
        try:
            if warranty_claim is not None:
                from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

                reply_markup = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(
                            text="✅ جرّبت ونجح التفعيل",
                            callback_data=f"warranty:confirm:{warranty_claim.id}",
                            style="success",
                        )],
                        [InlineKeyboardButton(
                            text="❌ توجد مشكلة في التفعيل",
                            callback_data=f"warranty:problem:{warranty_claim.id}",
                            style="danger",
                        )],
                    ]
                )
                title = "تم تفعيل الضمان وتعويضك بحساب جديد ✅"
                delivery_key = f"warranty:{warranty_claim.id}:delivery-message"
            else:
                reply_markup = order_actions_keyboard(order, allow_code=allow_code)
                title = (
                    "اكتمل حساب الأصدقاء وتم التسليم ✅"
                    if friend_member is not None
                    else "تم تسليم الاشتراك ✅"
                )
                delivery_key = f"order:{order.id}:delivery-message"
            await self.notifications.send_user(
                session,
                order.user,
                title,
                body,
                reply_markup=reply_markup,
                raise_on_error=True,
                idempotency_key=delivery_key,
            )
            # Persist proof that Telegram accepted the sensitive delivery before
            # changing inventory/order state. A recovered lease will not resend it.
            await session.commit()
        except Exception as exc:  # pragma: no cover - NotificationService normally absorbs errors.
            logger.exception("Delivery send failed order=%s: %s", order.id, exc)
            job = await session.get(DeliveryJob, job.id)
            if job:
                job.last_error = str(exc)[:2000]
                job.lease_owner = None
                job.lease_expires_at = None
                if job.attempts >= self.settings.delivery_max_attempts:
                    job.status = DeliveryJobStatus.FAILED.value
                    await self.orders.change_status(
                        session,
                        order,
                        OrderStatus.NEEDS_SUPPORT.value,
                        note="فشل إرسال بيانات الاشتراك بعد عدة محاولات",
                    )
                else:
                    job.status = DeliveryJobStatus.PENDING.value
                    job.next_attempt_at = datetime.now(UTC) + timedelta(
                        seconds=self.settings.delivery_retry_seconds
                    )
                await session.commit()
            return True

        job_id = job.id
        item_id = item.id
        order_id = order.id
        claim_id = warranty_claim.id if warranty_claim is not None else None
        member_id = friend_member.id if friend_member is not None else None
        job = await session.get(DeliveryJob, job_id)
        item = await session.scalar(
            select(InventoryItem).where(InventoryItem.id == item_id).with_for_update()
        )
        order = await self.orders.get(session, order_id)
        warranty_claim = (
            await session.scalar(
                select(WarrantyClaim).where(WarrantyClaim.id == claim_id).with_for_update()
            )
            if claim_id is not None
            else None
        )
        friend_member = (
            await session.scalar(
                select(FriendGroupMember)
                .where(FriendGroupMember.id == member_id)
                .with_for_update()
            )
            if member_id is not None
            else None
        )
        if not job or not item or not order:
            return True
        job.status = DeliveryJobStatus.SENT.value
        job.lease_owner = None
        job.lease_expires_at = None
        job.completed_at = datetime.now(UTC)
        if warranty_claim is not None:
            # Replacement delivery must not restart or extend the original subscription.
            item.status = InventoryStatus.DELIVERED.value
            item.delivered_at = datetime.now(UTC)
            warranty_claim.status = WarrantyClaimStatus.WAITING_STUDENT_CONFIRMATION.value
            await self.orders.change_status(
                session,
                order,
                OrderStatus.DELIVERED.value,
                note=f"تم إرسال الحساب البديل ضمن الضمان #{warranty_claim.id}",
            )
        elif friend_member is not None:
            group = await session.scalar(
                select(FriendGroup)
                .where(FriendGroup.id == friend_member.group_id)
                .with_for_update()
            ) if friend_member else None
            if friend_member:
                friend_member.status = FriendMemberStatus.DELIVERED.value
                friend_member.delivered_at = datetime.now(UTC)
            await self.orders.change_status(
                session,
                order,
                OrderStatus.DELIVERED.value,
                note=f"تم تسليم الحساب المشترك للمجموعة عبر Outbox",
            )
            await self.student_subscriptions.mark_delivered(session, order, item)
            if group:
                delivered_count = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(FriendGroupMember)
                        .where(
                            FriendGroupMember.group_id == group.id,
                            FriendGroupMember.status == FriendMemberStatus.DELIVERED.value,
                        )
                    )
                    or 0
                )
                if delivered_count >= group.required_members:
                    group.status = FriendGroupStatus.DELIVERED.value
                    group.delivered_at = datetime.now(UTC)
                    item.status = InventoryStatus.DELIVERED.value
                    item.delivered_at = datetime.now(UTC)
                else:
                    item.status = InventoryStatus.RESERVED.value
        else:
            item.status = InventoryStatus.DELIVERED.value
            item.delivered_at = datetime.now(UTC)
            await self.orders.change_status(
                session,
                order,
                OrderStatus.DELIVERED.value,
                note=f"تم تسليم عنصر المخزون #{item.id} عبر Outbox",
            )
            await self.student_subscriptions.mark_delivered(session, order, item)
        guide = await self.activation_guides.get_for_offer(session, order.offer_id)
        if guide:
            try:
                await self.activation_guides.send_to_chat(
                    self.notifications.bot, order.user.telegram_id, guide
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("Could not resend guide after delivery order=%s: %s", order.id, exc)
        await session.commit()
        return True
