from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import order_actions_keyboard
from app.core.config import Settings
from app.core.security import SecretBox
from app.core.time import as_utc
from app.db.models import (
    EmailAccount,
    EmailAccountStatus,
    EmailReservation,
    EmailReservationStatus,
    Offer,
    Order,
    OrderStatus,
    User,
    VerificationMessage,
)
from app.integrations.email.imap_client import (
    EmailCandidate,
    IMAPAuthenticationError,
    IMAPClientError,
    IMAPTimeoutError,
    fetch_candidates,
    test_connection,
)
from app.services.notifications import NotificationService
from app.services.orders import OrderService
from app.services.provider_operations import ProviderOperationsService
from app.services.student_subscriptions import StudentSubscriptionService

logger = logging.getLogger(__name__)


class EmailCodeService:
    """Non-blocking IMAP delivery with deterministic failure recovery."""

    def __init__(
        self,
        settings: Settings,
        secrets: SecretBox,
        orders: OrderService,
        notifications: NotificationService,
        student_subscriptions: StudentSubscriptionService,
        provider_operations: ProviderOperationsService,
    ) -> None:
        self.settings = settings
        self.secrets = secrets
        self.orders = orders
        self.notifications = notifications
        self.student_subscriptions = student_subscriptions
        self.provider_operations = provider_operations

    async def test_connection(
        self, host: str, port: int, username: str, password: str
    ) -> tuple[bool, str]:
        return await test_connection(
            host,
            port,
            username,
            password,
            timeout=float(self.settings.email_imap_overall_timeout_seconds),
        )

    async def reset_daily_counters(self, session: AsyncSession) -> None:
        accounts = list((await session.scalars(select(EmailAccount))).all())
        for account in accounts:
            if account.counter_date != date.today():
                account.counter_date = date.today()
                account.used_today = 0
                if account.status == EmailAccountStatus.DAILY_LIMIT.value:
                    account.status = EmailAccountStatus.AVAILABLE.value
        await session.flush()

    async def reserve(self, session: AsyncSession, order: Order, offer: Offer) -> EmailReservation:
        await self.reset_daily_counters(session)
        now = datetime.now(UTC)
        accounts = list(
            (
                await session.scalars(
                    select(EmailAccount)
                    .where(
                        EmailAccount.provider_id == order.provider_id,
                        or_(EmailAccount.offer_id == offer.id, EmailAccount.offer_id.is_(None)),
                        EmailAccount.status.in_(
                            {
                                EmailAccountStatus.AVAILABLE.value,
                                EmailAccountStatus.RESERVED.value,
                            }
                        ),
                        EmailAccount.used_today < EmailAccount.daily_limit,
                        or_(EmailAccount.valid_from.is_(None), EmailAccount.valid_from <= now),
                        or_(EmailAccount.valid_until.is_(None), EmailAccount.valid_until >= now),
                    )
                    .order_by(EmailAccount.used_today.asc(), EmailAccount.id.asc())
                    .limit(20)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        account = None
        shortest_wait = 60
        for candidate in accounts:
            decision, wait_seconds, _lease = await self.provider_operations.acquire_otp_lease(
                session,
                email_account_id=candidate.id,
                order_id=order.id,
                holder_user_id=order.user_id,
                lease_seconds=min(60, int(self.settings.otp_account_lease_seconds)),
            )
            if decision.value in {"acquired", "already_held_by_order"}:
                account = candidate
                break
            shortest_wait = min(shortest_wait, max(1, int(wait_seconds or 1)))
        if account is None:
            raise ValueError(
                "⏳ يرجى الانتظار لثوانٍ معدودة. هناك مشترك آخر يقوم بتسجيل الدخول "
                f"حالياً لتجنب حظر الحساب. دورك محفوظ؛ حاول بعد {shortest_wait} ثانية."
            )
        order.code_attempts += 1
        reservation = EmailReservation(
            order_id=order.id,
            email_account_id=account.id,
            attempt=order.code_attempts,
            expires_at=now + timedelta(minutes=self.settings.email_reservation_minutes),
        )
        session.add(reservation)
        await self.orders.change_status(
            session,
            order,
            OrderStatus.WAITING_CODE.value,
            note=f"تم حجز الإيميل {account.label}",
        )
        await session.flush()
        return reservation

    async def request_new_code(
        self, session: AsyncSession, order: Order, offer: Offer
    ) -> EmailReservation:
        max_attempts = min(offer.max_code_attempts, self.settings.max_code_attempts)
        if order.code_attempts >= max_attempts:
            raise ValueError("تم استنفاد محاولات الكود ويجب التواصل مع مزود الخدمة")
        active = await session.scalar(
            select(EmailReservation).where(
                EmailReservation.order_id == order.id,
                EmailReservation.status == EmailReservationStatus.WAITING.value,
            )
        )
        if active:
            active.status = EmailReservationStatus.CANCELLED.value
            account = await session.get(EmailAccount, active.email_account_id)
            if account and account.status == EmailAccountStatus.RESERVED.value:
                account.status = EmailAccountStatus.AVAILABLE.value
            await self.provider_operations.release_otp_lease_for_order(
                session, order_id=order.id, email_account_id=active.email_account_id
            )
        return await self.reserve(session, order, offer)

    async def poll_pending(self, session: AsyncSession) -> None:
        now = datetime.now(UTC)
        reservations = list(
            (
                await session.scalars(
                    select(EmailReservation)
                    .where(EmailReservation.status == EmailReservationStatus.WAITING.value)
                    .order_by(EmailReservation.started_at.asc())
                    .limit(100)
                )
            ).all()
        )
        for reservation in reservations:
            expires_at = as_utc(reservation.expires_at)
            if expires_at and expires_at <= now:
                await self._expire(session, reservation)
                continue
            try:
                await self._poll_one(session, reservation)
            except IMAPAuthenticationError as exc:
                await self._recover_failure(
                    session,
                    reservation,
                    user_message=(
                        "تعذر الوصول إلى بريد مزود الخدمة. تم تحرير الحجز وتحويل الطلب "
                        "إلى الدعم، ويمكنك المحاولة مجددًا بعد إصلاح البريد."
                    ),
                    internal_reason=str(exc),
                    reconnect=True,
                )
            except (IMAPTimeoutError, IMAPClientError) as exc:
                await self._recover_failure(
                    session,
                    reservation,
                    user_message=(
                        "لم يستجب خادم البريد في الوقت المحدد. لم يتجمد طلبك؛ تم تحويله "
                        "إلى الدعم ويمكن إعادة المحاولة بأمان."
                    ),
                    internal_reason=str(exc),
                    reconnect=False,
                )
            except Exception as exc:
                logger.exception("Email reservation %s failed", reservation.id)
                await self._recover_failure(
                    session,
                    reservation,
                    user_message=(
                        "حدث خلل مؤقت أثناء جلب رمز التحقق. تم تحرير البريد وتحويل الطلب "
                        "إلى الدعم حتى لا يبقى عالقًا."
                    ),
                    internal_reason=f"{type(exc).__name__}: {str(exc)[:300]}",
                    reconnect=False,
                )

    async def _expire(self, session: AsyncSession, reservation: EmailReservation) -> None:
        reservation.status = EmailReservationStatus.EXPIRED.value
        account = await session.get(EmailAccount, reservation.email_account_id)
        if account:
            account.status = EmailAccountStatus.AVAILABLE.value
        await self.provider_operations.release_otp_lease_for_order(
            session,
            order_id=reservation.order_id,
            email_account_id=reservation.email_account_id,
            final_status="expired",
        )
        order = await session.get(Order, reservation.order_id)
        if order:
            await self.orders.change_status(
                session,
                order,
                OrderStatus.NEEDS_SUPPORT.value,
                note="انتهت مهلة انتظار رمز البريد",
            )
            await self.student_subscriptions.mark_needs_support(
                session, order, "email reservation expired"
            )
            user = await session.get(User, order.user_id)
            if user:
                await self.notifications.send_user(
                    session,
                    user,
                    "انتهت مهلة رمز التحقق",
                    (
                        f"رقم الطلب: <code>{order.public_id}</code>\n"
                        "لم يصل الرمز ضمن المهلة. تم تحرير البريد وتحويل الطلب إلى الدعم؛ "
                        "يمكنك فتح الدعم المباشر من تفاصيل الطلب."
                    ),
                    reply_markup=order_actions_keyboard(order),
                    idempotency_key=f"imap-expired:{reservation.id}",
                )
        await session.flush()

    async def _recover_failure(
        self,
        session: AsyncSession,
        reservation: EmailReservation,
        *,
        user_message: str,
        internal_reason: str,
        reconnect: bool,
    ) -> None:
        """Release resources and persist a complete, retryable lifecycle transition."""
        reservation.status = EmailReservationStatus.CANCELLED.value
        reservation.completed_at = datetime.now(UTC)
        account = await session.get(EmailAccount, reservation.email_account_id)
        if account:
            account.status = (
                EmailAccountStatus.RECONNECT.value
                if reconnect
                else EmailAccountStatus.AVAILABLE.value
            )
        await self.provider_operations.release_otp_lease_for_order(
            session,
            order_id=reservation.order_id,
            email_account_id=reservation.email_account_id,
            final_status="released",
        )
        order = await session.get(Order, reservation.order_id)
        if not order:
            await session.flush()
            return

        await self.orders.change_status(
            session,
            order,
            OrderStatus.NEEDS_SUPPORT.value,
            note=f"IMAP recovery: {internal_reason[:500]}",
        )
        await self.student_subscriptions.mark_needs_support(
            session, order, internal_reason
        )
        user = await session.get(User, order.user_id)
        if user:
            await self.notifications.send_user(
                session,
                user,
                "تعذر جلب رمز التحقق",
                f"رقم الطلب: <code>{order.public_id}</code>\n\n{user_message}",
                reply_markup=order_actions_keyboard(order),
                idempotency_key=f"imap-failure:{reservation.id}",
            )
        await self.notifications.send_admins(
            "⚠️ فشل IMAP وتمت استعادة دورة الطلب تلقائيًا\n"
            f"الطلب: {order.public_id}\n"
            f"الحساب: {account.label if account else reservation.email_account_id}\n"
            f"السبب: {internal_reason[:500]}"
        )
        await session.flush()

    async def _poll_one(self, session: AsyncSession, reservation: EmailReservation) -> None:
        account = await session.get(EmailAccount, reservation.email_account_id)
        order = await session.get(Order, reservation.order_id)
        if not account or not order:
            reservation.status = EmailReservationStatus.CANCELLED.value
            await session.flush()
            return
        offer = await session.get(Offer, order.offer_id)
        if not offer:
            await self._recover_failure(
                session,
                reservation,
                user_message="تعذر العثور على بيانات العرض، وتم تحويل الطلب إلى الدعم.",
                internal_reason="offer missing",
                reconnect=False,
            )
            return

        password = self.secrets.decrypt(account.encrypted_secret)
        candidates = await fetch_candidates(
            account.imap_host,
            account.imap_port,
            account.username,
            password,
            as_utc(reservation.started_at) or datetime.now(UTC),
            offer.sender_filter or account.sender_filter,
            offer.subject_regex or account.subject_regex,
            offer.code_regex or account.code_regex,
            timeout=float(self.settings.email_imap_overall_timeout_seconds),
        )
        unused: list[EmailCandidate] = []
        for candidate in candidates:
            exists = await session.scalar(
                select(VerificationMessage.id).where(
                    VerificationMessage.email_account_id == account.id,
                    VerificationMessage.message_uid == candidate.uid,
                )
            )
            if not exists:
                unused.append(candidate)
        if not unused:
            return
        if len(unused) > 1 and self.settings.email_ambiguity_policy == "review":
            reservation.status = EmailReservationStatus.REVIEW.value
            account.status = EmailAccountStatus.PAUSED.value
            await self.orders.change_status(
                session,
                order,
                OrderStatus.NEEDS_SUPPORT.value,
                note="أكثر من رسالة تحقق محتملة وتحتاج مراجعة",
            )
            await self.student_subscriptions.mark_needs_support(
                session, order, "ambiguous verification messages"
            )
            await self.notifications.send_admins(
                f"⚠️ أكثر من كود محتمل للطلب {order.public_id}. تم إيقاف التسليم الآلي."
            )
            await session.flush()
            return

        candidate = unused[0]
        code_hash = self.secrets.hash_value(f"{account.id}:{candidate.uid}:{candidate.code}")
        verification = VerificationMessage(
            email_account_id=account.id,
            email_reservation_id=reservation.id,
            message_uid=candidate.uid,
            message_id_header=candidate.message_id,
            sender=candidate.sender,
            subject=candidate.subject,
            code_hash=code_hash,
            encrypted_code=self.secrets.encrypt(candidate.code),
            received_at=candidate.received_at,
        )
        session.add(verification)
        await session.flush()

        user = await session.get(User, order.user_id)
        if user:
            await self.notifications.send_user(
                session,
                user,
                "رمز التحقق جاهز ✅",
                (
                    f"رقم الطلب: <code>{order.public_id}</code>\n"
                    f"رمز التحقق: <code>{candidate.code}</code>\n\n"
                    "استخدم الرمز مرة واحدة ثم اختر تم التفعيل أو لم يتم التفعيل."
                ),
                reply_markup=order_actions_keyboard(order, allow_code=True),
                idempotency_key=f"imap-delivered:{reservation.id}:{candidate.uid}",
            )
        verification.delivered_at = datetime.now(UTC)
        verification.status = "delivered"
        verification.encrypted_code = None
        reservation.status = EmailReservationStatus.DELIVERED.value
        reservation.completed_at = datetime.now(UTC)
        account.used_today += 1
        account.last_message_uid = candidate.uid
        account.status = (
            EmailAccountStatus.DAILY_LIMIT.value
            if account.used_today >= account.daily_limit
            else EmailAccountStatus.AVAILABLE.value
        )
        await self.provider_operations.release_otp_lease_for_order(
            session,
            order_id=order.id,
            email_account_id=account.id,
            final_status="released",
        )
        await self.orders.change_status(
            session,
            order,
            OrderStatus.DELIVERED.value,
            note="تم تسليم رمز التحقق",
        )
        await self.student_subscriptions.mark_delivered(session, order)
        await session.flush()
