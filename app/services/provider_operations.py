from __future__ import annotations

import hashlib
import secrets as py_secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import SecretBox
from app.domain.provider_operations import (
    OtpLeaseDecision,
    ProviderInboxStatus,
    can_transition_inbox,
    canonical_payment_name,
    normalize_balance_mode,
    otp_lease_result,
    temporary_access_deadline,
)
from app.db.models import (
    ActivationRequestStatus,
    EmailAccount,
    LogoutProofStatus,
    OtpAccountLease,
    Order,
    PaymentMethod,
    ProviderInboxEvent,
    ProviderInboxItem,
    ProviderInboxItemStatus,
    ProviderOfferFulfillmentProfile,
    ProviderPaymentMethodConfig,
    ProviderTermsAcceptance,
    ProviderWorkingHour,
    StudentActivationRequest,
    StudentCodeRelay,
    StudentCodeRelayStatus,
    StudentOperationalRestriction,
    StudentRestrictionStatus,
    TemporaryAccessSession,
    TemporaryLogoutProof,
    User,
)


class ProviderOperationsService:
    """Transactional provider operations introduced in V11.2.

    Telegram handlers remain presentation-only. This service owns provider terms,
    working hours, payment configuration, the unified inbox, student activation
    relays, OTP leases and temporary-account logout enforcement.
    """

    def __init__(self, secrets: SecretBox) -> None:
        self.secrets = secrets

    async def accept_terms(
        self,
        session: AsyncSession,
        *,
        provider_id: int,
        user_id: int,
        version: str,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderTermsAcceptance:
        row = await session.scalar(
            select(ProviderTermsAcceptance).where(
                ProviderTermsAcceptance.provider_id == int(provider_id),
                ProviderTermsAcceptance.user_id == int(user_id),
                ProviderTermsAcceptance.terms_version == str(version),
            )
        )
        if row is None:
            row = ProviderTermsAcceptance(
                provider_id=int(provider_id),
                user_id=int(user_id),
                terms_version=str(version),
                metadata_json=dict(metadata or {}),
            )
            session.add(row)
        else:
            row.revoked_at = None
            row.accepted_at = datetime.now(UTC)
            merged = dict(row.metadata_json or {})
            merged.update(metadata or {})
            row.metadata_json = merged
        await session.flush()
        return row

    async def has_accepted_terms(
        self,
        session: AsyncSession,
        *,
        provider_id: int,
        user_id: int,
        version: str,
    ) -> bool:
        return bool(
            await session.scalar(
                select(ProviderTermsAcceptance.id).where(
                    ProviderTermsAcceptance.provider_id == int(provider_id),
                    ProviderTermsAcceptance.user_id == int(user_id),
                    ProviderTermsAcceptance.terms_version == str(version),
                    ProviderTermsAcceptance.revoked_at.is_(None),
                )
            )
        )

    async def configure_fulfillment(
        self,
        session: AsyncSession,
        *,
        provider_id: int,
        offer_id: int,
        account_type: str,
        activation_mode: str,
        shared_capacity: int | None = None,
        unlimited_capacity: bool = False,
        temporary_access_minutes: int | None = None,
        logout_proof_required: bool = False,
        student_email_required: bool = False,
        student_code_relay_enabled: bool = False,
        otp_lease_seconds: int = 60,
        max_otp_attempts: int = 3,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderOfferFulfillmentProfile:
        if account_type not in {"private", "shared", "friends_only", "not_applicable"}:
            raise ValueError("نوع الحساب غير مدعوم")
        if shared_capacity is not None and shared_capacity < 1:
            raise ValueError("عدد الأشخاص يجب أن يكون واحداً أو أكثر")
        if not 1 <= int(otp_lease_seconds) <= 60:
            raise ValueError("مدة قفل OTP يجب ألا تتجاوز 60 ثانية")
        if not 1 <= int(max_otp_attempts) <= 3:
            raise ValueError("الحد الأقصى لمحاولات OTP هو 3")
        if temporary_access_minutes is not None and temporary_access_minutes < 1:
            raise ValueError("مدة الحساب المؤقت غير صحيحة")
        row = await session.scalar(
            select(ProviderOfferFulfillmentProfile).where(
                ProviderOfferFulfillmentProfile.offer_id == int(offer_id)
            )
        )
        values = {
            "provider_id": int(provider_id),
            "account_type": account_type,
            "activation_mode": activation_mode,
            "shared_capacity": shared_capacity,
            "unlimited_capacity": bool(unlimited_capacity),
            "temporary_access_minutes": temporary_access_minutes,
            "logout_proof_required": bool(logout_proof_required),
            "student_email_required": bool(student_email_required),
            "student_code_relay_enabled": bool(student_code_relay_enabled),
            "otp_lease_seconds": int(otp_lease_seconds),
            "max_otp_attempts": int(max_otp_attempts),
            "metadata_json": dict(metadata or {}),
        }
        if row is None:
            row = ProviderOfferFulfillmentProfile(offer_id=int(offer_id), **values)
            session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await session.flush()
        return row

    async def set_working_day(
        self,
        session: AsyncSession,
        *,
        provider_id: int,
        weekday: int,
        opens_minute: int,
        closes_minute: int,
        is_closed: bool = False,
    ) -> ProviderWorkingHour:
        if weekday not in range(7):
            raise ValueError("اليوم غير صحيح")
        if opens_minute not in range(1440) or closes_minute not in range(1440):
            raise ValueError("وقت الدوام غير صحيح")
        row = await session.scalar(
            select(ProviderWorkingHour).where(
                ProviderWorkingHour.provider_id == int(provider_id),
                ProviderWorkingHour.weekday == int(weekday),
            )
        )
        if row is None:
            row = ProviderWorkingHour(provider_id=int(provider_id), weekday=int(weekday))
            session.add(row)
        row.opens_minute = int(opens_minute)
        row.closes_minute = int(closes_minute)
        row.is_closed = bool(is_closed)
        row.is_active = True
        await session.flush()
        return row

    async def create_payment_method(
        self,
        session: AsyncSession,
        *,
        provider_id: int,
        channel: str,
        recipient: str,
        instructions: str,
        balance_mode: str | None = None,
        proof_guide_file_id: str | None = None,
        proof_guide_text: str = "",
    ) -> PaymentMethod:
        name = canonical_payment_name(channel)
        normalized_mode = normalize_balance_mode(balance_mode)
        if channel == "mobile_balance" and normalized_mode is None:
            raise ValueError("حدد طريقة دفع الرصيد")
        if channel == "electronic" and normalized_mode is not None:
            raise ValueError("نوع تحويل الرصيد لا يستخدم مع الدفع الإلكتروني")
        method = PaymentMethod(
            provider_id=int(provider_id),
            name=name,
            method_type="balance" if channel == "mobile_balance" else "card_transfer",
            recipient=str(recipient).strip()[:255],
            instructions=str(instructions).strip()[:4000],
            icon="📱" if channel == "mobile_balance" else "💳",
        )
        session.add(method)
        await session.flush()
        session.add(
            ProviderPaymentMethodConfig(
                payment_method_id=method.id,
                provider_id=int(provider_id),
                channel=channel,
                balance_mode=normalized_mode,
                proof_guide_file_id=proof_guide_file_id,
                proof_guide_text=str(proof_guide_text).strip()[:4000],
            )
        )
        await session.flush()
        return method

    async def enqueue_inbox(
        self,
        session: AsyncSession,
        *,
        provider_id: int,
        kind: str,
        idempotency_key: str,
        title: str,
        summary: str,
        order_id: int | None = None,
        user_id: int | None = None,
        source_type: str = "",
        source_id: int | None = None,
        file_id: str | None = None,
        amount_iqd: int | None = None,
        priority: str = "normal",
        payload: dict[str, Any] | None = None,
    ) -> ProviderInboxItem:
        existing = await session.scalar(
            select(ProviderInboxItem).where(
                ProviderInboxItem.idempotency_key == str(idempotency_key)
            )
        )
        if existing is not None:
            return existing
        item = ProviderInboxItem(
            provider_id=int(provider_id),
            kind=str(kind),
            priority=str(priority),
            order_id=order_id,
            user_id=user_id,
            source_type=str(source_type),
            source_id=source_id,
            title=str(title)[:255],
            summary=str(summary)[:5000],
            file_id=file_id,
            amount_iqd=amount_iqd,
            payload_json=dict(payload or {}),
            idempotency_key=str(idempotency_key)[:180],
        )
        session.add(item)
        await session.flush()
        session.add(
            ProviderInboxEvent(
                inbox_item_id=item.id,
                event_type="created",
                to_status=ProviderInboxStatus.NEW.value,
            )
        )
        await session.flush()
        return item

    async def transition_inbox(
        self,
        session: AsyncSession,
        *,
        item_id: int,
        provider_id: int,
        actor_user_id: int,
        target_status: str,
        note: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ProviderInboxItem:
        item = await session.scalar(
            select(ProviderInboxItem)
            .where(
                ProviderInboxItem.id == int(item_id),
                ProviderInboxItem.provider_id == int(provider_id),
            )
            .with_for_update()
        )
        if item is None:
            raise ValueError("عنصر البريد غير موجود")
        if item.status == target_status:
            return item
        if not can_transition_inbox(item.status, target_status):
            raise ValueError("لا يمكن تغيير حالة عنصر البريد بهذه الطريقة")
        before = item.status
        item.status = target_status
        if target_status in {
            ProviderInboxStatus.RESOLVED.value,
            ProviderInboxStatus.REJECTED.value,
        }:
            item.processed_by_user_id = int(actor_user_id)
            item.processed_at = datetime.now(UTC)
        session.add(
            ProviderInboxEvent(
                inbox_item_id=item.id,
                actor_user_id=int(actor_user_id),
                event_type="status_changed",
                from_status=before,
                to_status=target_status,
                note=str(note)[:4000],
                metadata_json=dict(metadata or {}),
            )
        )
        await session.flush()
        return item

    @staticmethod
    def _email_hint(email: str) -> str:
        local, _, domain = email.partition("@")
        if not domain:
            return "***"
        visible = local[:2]
        return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"

    async def create_activation_request(
        self,
        session: AsyncSession,
        *,
        order: Order,
        student_email: str,
        requested_by_user_id: int | None = None,
    ) -> StudentActivationRequest:
        email = str(student_email).strip().lower()
        if "@" not in email or len(email) > 255:
            raise ValueError("الإيميل غير صحيح")
        request = StudentActivationRequest(
            order_id=order.id,
            provider_id=order.provider_id,
            user_id=order.user_id,
            encrypted_email=self.secrets.encrypt(email),
            email_hint=self._email_hint(email),
            requested_by_user_id=requested_by_user_id,
        )
        session.add(request)
        await session.flush()
        await self.enqueue_inbox(
            session,
            provider_id=order.provider_id,
            kind="student_activation_email",
            idempotency_key=f"activation-email:{request.id}",
            title="إيميل طالب بانتظار التفعيل",
            summary=f"الطلب {order.public_id} — {request.email_hint}",
            order_id=order.id,
            user_id=order.user_id,
            source_type="activation_request",
            source_id=request.id,
            payload={"email_hint": request.email_hint},
        )
        return request

    async def request_student_code(
        self,
        session: AsyncSession,
        *,
        activation_request_id: int,
        provider_id: int,
        actor_user_id: int,
    ) -> StudentActivationRequest:
        row = await session.scalar(
            select(StudentActivationRequest)
            .where(
                StudentActivationRequest.id == int(activation_request_id),
                StudentActivationRequest.provider_id == int(provider_id),
            )
            .with_for_update()
        )
        if row is None:
            raise ValueError("طلب التفعيل غير موجود")
        if row.status in {ActivationRequestStatus.ACTIVATED.value, ActivationRequestStatus.CANCELLED.value}:
            raise ValueError("طلب التفعيل مغلق")
        row.status = ActivationRequestStatus.WAITING_STUDENT_CODE.value
        row.code_requested_at = datetime.now(UTC)
        row.requested_by_user_id = int(actor_user_id)
        await session.flush()
        return row

    async def submit_student_code(
        self,
        session: AsyncSession,
        *,
        activation_request_id: int,
        student_user_id: int,
        code: str,
        ttl_minutes: int = 5,
    ) -> StudentCodeRelay:
        raw = str(code).strip()
        if not raw.isdigit() or not 4 <= len(raw) <= 8:
            raise ValueError("اكتب رمزاً رقمياً من 4 إلى 8 خانات")
        request = await session.scalar(
            select(StudentActivationRequest)
            .where(
                StudentActivationRequest.id == int(activation_request_id),
                StudentActivationRequest.user_id == int(student_user_id),
            )
            .with_for_update()
        )
        if request is None or request.status != ActivationRequestStatus.WAITING_STUDENT_CODE.value:
            raise ValueError("لا يوجد طلب رمز نشط")
        previous = list(
            (
                await session.scalars(
                    select(StudentCodeRelay).where(
                        StudentCodeRelay.activation_request_id == request.id
                    )
                )
            ).all()
        )
        attempt = len(previous) + 1
        if attempt > 3:
            raise ValueError("تم استنفاد محاولات الرمز")
        now = datetime.now(UTC)
        for item in previous:
            if item.status == StudentCodeRelayStatus.PENDING.value:
                item.status = StudentCodeRelayStatus.EXPIRED.value
        relay = StudentCodeRelay(
            activation_request_id=request.id,
            attempt=attempt,
            encrypted_code=self.secrets.encrypt(raw),
            code_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=now + timedelta(minutes=max(1, min(ttl_minutes, 10))),
        )
        session.add(relay)
        request.status = ActivationRequestStatus.CODE_RECEIVED.value
        await session.flush()
        await self.enqueue_inbox(
            session,
            provider_id=request.provider_id,
            kind="student_code_relay",
            idempotency_key=f"student-code:{relay.id}",
            title="رمز تحقق وصل من الطالب",
            summary=f"رمز مؤقت للطلب #{request.order_id} — المحاولة {attempt}",
            order_id=request.order_id,
            user_id=request.user_id,
            source_type="student_code_relay",
            source_id=relay.id,
            priority="high",
            payload={"expires_at": relay.expires_at.isoformat(), "attempt": attempt},
        )
        return relay

    async def consume_student_code(
        self,
        session: AsyncSession,
        *,
        relay_id: int,
        provider_id: int,
    ) -> str:
        relay = await session.scalar(
            select(StudentCodeRelay)
            .join(
                StudentActivationRequest,
                StudentActivationRequest.id == StudentCodeRelay.activation_request_id,
            )
            .where(
                StudentCodeRelay.id == int(relay_id),
                StudentActivationRequest.provider_id == int(provider_id),
            )
            .with_for_update()
        )
        if relay is None or relay.status != StudentCodeRelayStatus.PENDING.value:
            raise ValueError("الرمز غير متاح")
        if relay.expires_at <= datetime.now(UTC):
            relay.status = StudentCodeRelayStatus.EXPIRED.value
            raise ValueError("انتهت صلاحية الرمز")
        relay.status = StudentCodeRelayStatus.CONSUMED.value
        relay.consumed_at = datetime.now(UTC)
        await session.flush()
        return self.secrets.decrypt(relay.encrypted_code)

    async def acquire_otp_lease(
        self,
        session: AsyncSession,
        *,
        email_account_id: int,
        order_id: int,
        holder_user_id: int,
        lease_seconds: int = 60,
    ) -> tuple[OtpLeaseDecision, int, OtpAccountLease | None]:
        # Lock the parent account so two requests cannot both observe an empty lease.
        account = await session.scalar(
            select(EmailAccount)
            .where(EmailAccount.id == int(email_account_id))
            .with_for_update()
        )
        if account is None:
            raise ValueError("حساب البريد غير موجود")
        now = datetime.now(UTC)
        existing = await session.scalar(
            select(OtpAccountLease)
            .where(
                OtpAccountLease.email_account_id == account.id,
                OtpAccountLease.status == "active",
            )
            .order_by(OtpAccountLease.expires_at.desc())
            .limit(1)
        )
        if existing and existing.expires_at <= now:
            existing.status = "expired"
            existing.released_at = now
        decision = otp_lease_result(
            now=now,
            existing_order_id=existing.order_id if existing and existing.status == "active" else None,
            existing_expires_at=existing.expires_at if existing and existing.status == "active" else None,
            requested_order_id=int(order_id),
            lease_seconds=int(lease_seconds),
        )
        if decision.decision is OtpLeaseDecision.BUSY:
            return decision.decision, decision.wait_seconds, existing
        if decision.decision is OtpLeaseDecision.ALREADY_HELD_BY_ORDER and existing:
            return decision.decision, decision.wait_seconds, existing
        token = py_secrets.token_urlsafe(24)
        lease = OtpAccountLease(
            email_account_id=account.id,
            order_id=int(order_id),
            holder_user_id=int(holder_user_id),
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=now + timedelta(seconds=int(lease_seconds)),
        )
        session.add(lease)
        await session.flush()
        return decision.decision, 0, lease

    async def release_otp_lease(
        self,
        session: AsyncSession,
        *,
        lease_id: int,
        order_id: int,
    ) -> bool:
        lease = await session.scalar(
            select(OtpAccountLease)
            .where(
                OtpAccountLease.id == int(lease_id),
                OtpAccountLease.order_id == int(order_id),
            )
            .with_for_update()
        )
        if lease is None or lease.status != "active":
            return False
        lease.status = "released"
        lease.released_at = datetime.now(UTC)
        await session.flush()
        return True

    async def release_otp_lease_for_order(
        self,
        session: AsyncSession,
        *,
        order_id: int,
        email_account_id: int | None = None,
        final_status: str = "released",
    ) -> int:
        query = select(OtpAccountLease).where(
            OtpAccountLease.order_id == int(order_id),
            OtpAccountLease.status == "active",
        )
        if email_account_id is not None:
            query = query.where(OtpAccountLease.email_account_id == int(email_account_id))
        leases = list((await session.scalars(query.with_for_update())).all())
        now = datetime.now(UTC)
        for lease in leases:
            lease.status = str(final_status)[:20]
            lease.released_at = now
        if leases:
            await session.flush()
        return len(leases)

    async def submit_logout_proof(
        self,
        session: AsyncSession,
        *,
        temporary_session: TemporaryAccessSession,
        provider_id: int,
        order_id: int,
        user_id: int,
        telegram_file_id: str,
        evidence_asset_id: int | None = None,
        student_note: str = "",
    ) -> TemporaryLogoutProof:
        row = await session.scalar(
            select(TemporaryLogoutProof).where(
                TemporaryLogoutProof.temporary_session_id == temporary_session.id
            )
        )
        if row is None:
            row = TemporaryLogoutProof(
                temporary_session_id=temporary_session.id,
                provider_id=int(provider_id),
                order_id=int(order_id),
                user_id=int(user_id),
            )
            session.add(row)
        row.telegram_file_id = str(telegram_file_id)
        row.evidence_asset_id = evidence_asset_id
        row.student_note = str(student_note)[:2000]
        row.status = LogoutProofStatus.PENDING.value
        await session.flush()
        await self.enqueue_inbox(
            session,
            provider_id=int(provider_id),
            kind="logout_proof",
            idempotency_key=f"logout-proof:{row.id}",
            title="إثبات تسجيل خروج بانتظار التأكيد",
            summary=f"الطلب #{order_id}",
            order_id=int(order_id),
            user_id=int(user_id),
            source_type="temporary_logout_proof",
            source_id=row.id,
            file_id=str(telegram_file_id),
            priority="high",
        )
        return row

    async def confirm_logout_proof(
        self,
        session: AsyncSession,
        *,
        proof_id: int,
        provider_id: int,
        actor_user_id: int,
        accepted: bool,
        note: str = "",
    ) -> TemporaryLogoutProof:
        proof = await session.scalar(
            select(TemporaryLogoutProof)
            .where(
                TemporaryLogoutProof.id == int(proof_id),
                TemporaryLogoutProof.provider_id == int(provider_id),
            )
            .with_for_update()
        )
        if proof is None:
            raise ValueError("إثبات الخروج غير موجود")
        proof.status = (
            LogoutProofStatus.CONFIRMED.value if accepted else LogoutProofStatus.REJECTED.value
        )
        proof.provider_note = str(note)[:2000]
        proof.confirmed_by_user_id = int(actor_user_id)
        proof.confirmed_at = datetime.now(UTC)
        if accepted:
            temp = await session.get(TemporaryAccessSession, proof.temporary_session_id)
            if temp:
                temp.deletion_acknowledged_at = datetime.now(UTC)
            restrictions = list(
                (
                    await session.scalars(
                        select(StudentOperationalRestriction).where(
                            StudentOperationalRestriction.user_id == proof.user_id,
                            StudentOperationalRestriction.order_id == proof.order_id,
                            StudentOperationalRestriction.status.in_(
                                [
                                    StudentRestrictionStatus.ACTIVE.value,
                                    StudentRestrictionStatus.REVIEW.value,
                                ]
                            ),
                        )
                    )
                ).all()
            )
            for restriction in restrictions:
                restriction.status = StudentRestrictionStatus.LIFTED.value
                restriction.lifted_at = datetime.now(UTC)
                restriction.lifted_by_user_id = int(actor_user_id)
        await session.flush()
        return proof

    async def escalate_overdue_temporary_access(
        self,
        session: AsyncSession,
        *,
        grace_minutes: int = 30,
        limit: int = 200,
    ) -> int:
        now = datetime.now(UTC)
        sessions = list(
            (
                await session.scalars(
                    select(TemporaryAccessSession)
                    .where(
                        TemporaryAccessSession.deletion_required.is_(True),
                        TemporaryAccessSession.deletion_acknowledged_at.is_(None),
                        TemporaryAccessSession.ends_at <= now - timedelta(minutes=grace_minutes),
                    )
                    .order_by(TemporaryAccessSession.ends_at)
                    .limit(limit)
                )
            ).all()
        )
        escalated = 0
        for temp in sessions:
            deadline = temporary_access_deadline(
                now=now,
                ends_at=temp.ends_at,
                grace_minutes=grace_minutes,
                proof_confirmed=False,
            )
            if not deadline.should_escalate or temp.escalated_at is not None:
                continue
            order = await session.get(Order, temp.order_id)
            if order is None:
                continue
            proof = await session.scalar(
                select(TemporaryLogoutProof).where(
                    TemporaryLogoutProof.temporary_session_id == temp.id,
                    TemporaryLogoutProof.status == LogoutProofStatus.CONFIRMED.value,
                )
            )
            if proof is not None:
                temp.deletion_acknowledged_at = proof.confirmed_at or now
                continue
            existing = await session.scalar(
                select(StudentOperationalRestriction).where(
                    StudentOperationalRestriction.user_id == temp.user_id,
                    StudentOperationalRestriction.order_id == temp.order_id,
                    StudentOperationalRestriction.restriction_type == "temporary_logout_overdue",
                    StudentOperationalRestriction.status.in_(
                        [
                            StudentRestrictionStatus.ACTIVE.value,
                            StudentRestrictionStatus.REVIEW.value,
                        ]
                    ),
                )
            )
            if existing is None:
                session.add(
                    StudentOperationalRestriction(
                        user_id=temp.user_id,
                        provider_id=order.provider_id,
                        order_id=order.id,
                        restriction_type="temporary_logout_overdue",
                        reason="لم يثبت الطالب تسجيل الخروج بعد انتهاء المدة وفترة السماح",
                    )
                )
            temp.escalated_at = now
            await self.enqueue_inbox(
                session,
                provider_id=order.provider_id,
                kind="logout_proof",
                idempotency_key=f"logout-overdue:{temp.id}",
                title="⚠️ لم يثبت الطالب تسجيل الخروج",
                summary=(
                    f"الطلب {order.public_id}. انتهت مدة الاستخدام وفترة السماح؛ "
                    "يرجى تغيير كلمة المرور فوراً."
                ),
                order_id=order.id,
                user_id=temp.user_id,
                source_type="temporary_access_session",
                source_id=temp.id,
                priority="urgent",
                payload={"grace_ended_at": deadline.grace_ends_at.isoformat()},
            )
            escalated += 1
        await session.flush()
        return escalated

    async def active_restriction(
        self,
        session: AsyncSession,
        *,
        telegram_id: int,
    ) -> StudentOperationalRestriction | None:
        return await session.scalar(
            select(StudentOperationalRestriction)
            .join(User, User.id == StudentOperationalRestriction.user_id)
            .where(
                User.telegram_id == int(telegram_id),
                StudentOperationalRestriction.status.in_(
                    [
                        StudentRestrictionStatus.ACTIVE.value,
                        StudentRestrictionStatus.REVIEW.value,
                    ]
                ),
            )
            .order_by(StudentOperationalRestriction.imposed_at.desc())
            .limit(1)
        )
