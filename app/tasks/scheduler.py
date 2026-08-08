from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.context import AppContext
from app.core.time import as_utc, format_date
from app.db.models import (
    BackupRun,
    BackupRunStatus,
    Provider,
    ProviderStaff,
    ProviderStatus,
    ProviderSubscription,
    ProviderSubscriptionStatus,
    ProviderWebhookDelivery,
    WebhookDeliveryStatus,
    ScheduledRun,
    Order,
    TemporaryAccessSession,
    StudentSubscription,
    StudentSubscriptionStatus,
    User,
)

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, context: AppContext) -> None:
        self.context = context
        self.task: asyncio.Task | None = None
        self.stop_event = asyncio.Event()
        self.last_report_date = None
        self.last_subscription_check_hour: datetime | None = None

    async def start(self) -> None:
        self.task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self.stop_event.set()
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task

    async def run(self) -> None:
        timezone = ZoneInfo(self.context.settings.timezone)
        interval = max(10, self.context.settings.email_poll_seconds)
        while not self.stop_event.is_set():
            backup_schedule_id: int | None = None
            try:
                now_local = datetime.now(timezone)
                now_utc = datetime.now(UTC)
                async with self.context.database.session_factory() as session:
                    has_lock = await self.context.database.try_transaction_lock(
                        session, self.context.settings.scheduler_lock_id
                    )
                    if not has_lock:
                        await session.rollback()
                    else:
                        worker_id = f"{self.context.settings.release_id}:{self.context.settings.runtime_mode}"
                        await self.context.services.enterprise_scale.heartbeat(
                            session, worker_id, ["webhooks", "lifecycle"]
                        )
                        due_webhooks = list((await session.scalars(
                            select(ProviderWebhookDelivery).where(
                                ProviderWebhookDelivery.status.in_({
                                    WebhookDeliveryStatus.PENDING.value,
                                    WebhookDeliveryStatus.RETRY.value,
                                }),
                                ProviderWebhookDelivery.next_attempt_at <= now_utc,
                            ).order_by(ProviderWebhookDelivery.next_attempt_at).limit(10)
                        )).all())
                        for delivery in due_webhooks:
                            await self.context.services.enterprise_scale.deliver_webhook(session, delivery)
                        # Friends-only reservations must settle escrow/refunds before
                        # the generic reservation sweeper releases their inventory.
                        await self.context.services.friend_packages.expire_groups(session)
                        await self.context.services.orders.expire_reservations(session)
                        for _ in range(10):
                            processed = await self.context.services.fulfillment.process_next_delivery(
                                session
                            )
                            if not processed:
                                break
                        if self.context.settings.feature_email_codes:
                            await self.context.services.email_codes.poll_pending(session)
                        await self.temporary_access_tick(session, now_utc)
                        lifecycle_interval = max(30, int(self.context.settings.offer_lifecycle_interval_seconds))
                        lifecycle_key = str(int(now_utc.timestamp()) // lifecycle_interval)
                        lifecycle_run = await self.context.services.operations.claim_scheduled_run(
                            session, "offer_lifecycle", lifecycle_key
                        )
                        if lifecycle_run is not None:
                            try:
                                await self.context.services.offer_lifecycle.run_cycle(session, now_utc)
                                await self.context.services.operations.finish_scheduled_run(
                                    session, lifecycle_run, success=True
                                )
                            except Exception as exc:
                                await self.context.services.operations.finish_scheduled_run(
                                    session,
                                    lifecycle_run,
                                    success=False,
                                    error=f"{type(exc).__name__}: {str(exc)[:1000]}",
                                )
                                raise
                        await self.context.services.announcements.process_due(session)
                        await self.context.services.owner_commerce.expire_hybrid_purchases(
                            session, now=now_utc, limit=100
                        )
                        await self.context.services.owner_commerce.process_ad_campaigns(
                            session, now=now_utc, campaign_limit=3, recipient_batch=100
                        )
                        await self.context.services.owner_commerce.sync_central_inbox(
                            session, limit=50
                        )
                        await self.context.services.evidence.migrate_legacy_references(session, limit=25)
                        await self.context.services.evidence.archive_pending(session, limit=5)
                        await self.context.services.evidence.purge_expired(session, limit=20)

                        hour_key = now_local.strftime("%Y-%m-%dT%H")
                        hourly = await self.context.services.operations.claim_scheduled_run(
                            session, "hourly_lifecycle", hour_key
                        )
                        if hourly is not None:
                            try:
                                await self.subscription_lifecycle(session)
                                await self.student_subscription_lifecycle(session)
                                new_invoices = await self.context.services.owner_commerce.issue_due_invoices(
                                    session, now=now_utc
                                )
                                for invoice in new_invoices:
                                    await self._notify_provider_staff(
                                        session,
                                        invoice.provider_id,
                                        "🧾 فاتورة رسوم CampusPass IQ",
                                        f"صدرت الفاتورة {invoice.invoice_number} بقيمة "
                                        f"{invoice.total_iqd:,} د.ع. ارفع الوصل من لوحة المنصة قبل موعد الاستحقاق.",
                                    )
                                suspended = await self.context.services.owner_commerce.enforce_overdue_billing(
                                    session, now=now_utc
                                )
                                for provider_id in suspended:
                                    await self._notify_provider_staff(
                                        session,
                                        provider_id,
                                        "⛔ تم تعليق المنصة",
                                        "تم تعليق منصتك وإخفاؤها من متجر الطلاب لعدم تسديد المستحقات ضمن المهلة.",
                                    )
                                await self.context.services.enterprise_scale.lifecycle(session, now_utc)
                                if self.context.settings.encryption_key_version > 1:
                                    await self.context.services.key_rotation.rotate_batch(session)
                                await self.context.services.operations.finish_scheduled_run(
                                    session, hourly, success=True
                                )
                            except Exception as exc:
                                await self.context.services.operations.finish_scheduled_run(
                                    session,
                                    hourly,
                                    success=False,
                                    error=f"{type(exc).__name__}: {str(exc)[:1000]}",
                                )
                                raise

                        report_target = now_local.replace(
                            hour=self.context.settings.daily_report_hour,
                            minute=self.context.settings.daily_report_minute,
                            second=0,
                            microsecond=0,
                        )
                        if now_local >= report_target:
                            report_run = await self.context.services.operations.claim_scheduled_run(
                                session, "daily_reports", now_local.date().isoformat()
                            )
                            if report_run is not None:
                                try:
                                    await self.daily_reports(session, now_local)
                                    await self.context.services.operations.finish_scheduled_run(
                                        session, report_run, success=True
                                    )
                                except Exception as exc:
                                    await self.context.services.operations.finish_scheduled_run(
                                        session,
                                        report_run,
                                        success=False,
                                        error=f"{type(exc).__name__}: {str(exc)[:1000]}",
                                    )
                                    raise

                        backup_target = now_local.replace(
                            hour=self.context.settings.backup_hour,
                            minute=self.context.settings.backup_minute,
                            second=0,
                            microsecond=0,
                        )
                        if self.context.settings.backup_ready and now_local >= backup_target:
                            backup_schedule = (
                                await self.context.services.operations.claim_scheduled_run(
                                    session, "database_backup", now_local.date().isoformat()
                                )
                            )
                            if backup_schedule is not None:
                                backup_schedule_id = backup_schedule.id

                        maintenance_run = await self.context.services.operations.claim_scheduled_run(
                            session, "operations_cleanup", now_local.date().isoformat()
                        )
                        if maintenance_run is not None:
                            await self.context.services.operations.cleanup(session)
                            purged_reports = await self.context.services.reports.purge_expired_snapshots(session)
                            if purged_reports:
                                logger.info("Purged %s expired report snapshots; source financial data retained", purged_reports)
                            purged_updates = await self.context.services.telegram_updates.purge_completed(
                                session,
                                retention_days=self.context.settings.telegram_update_retention_days,
                            )
                            if purged_updates:
                                logger.info("Purged %s completed Telegram update receipts", purged_updates)
                            await self.context.services.operations.finish_scheduled_run(
                                session, maintenance_run, success=True
                            )
                        await session.commit()

                if backup_schedule_id is not None:
                    async with self.context.database.session_factory() as backup_session:
                        run = await self.context.services.backups.create(backup_session)
                        run.migration_version = await self.context.services.operations.latest_migration(
                            backup_session
                        )
                        scheduled = await backup_session.get(ScheduledRun, backup_schedule_id)
                        success = run.status == BackupRunStatus.VERIFIED.value
                        if scheduled is not None:
                            await self.context.services.operations.finish_scheduled_run(
                                backup_session,
                                scheduled,
                                success=success,
                                error=run.last_error or "",
                            )
                        expired = list(
                            (
                                await backup_session.scalars(
                                    select(BackupRun).where(
                                        BackupRun.retention_until.is_not(None),
                                        BackupRun.retention_until <= datetime.now(UTC),
                                        BackupRun.status != BackupRunStatus.DELETED.value,
                                    )
                                )
                            ).all()
                        )
                        await self.context.services.backups.purge_expired(backup_session, expired)
                        if not success:
                            await self.context.services.operations.record_incident(
                                backup_session,
                                code="BKP-LATEST",
                                severity="error",
                                source="backup",
                                summary="فشل النسخ الاحتياطي المجدول",
                                details=run.last_error or "unknown backup error",
                            )
                        else:
                            await self.context.services.operations.resolve_incident(
                                backup_session, "BKP-LATEST"
                            )
                        await backup_session.commit()
                        if not success:
                            await self.context.services.notifications.send_admins(
                                f"❌ فشل النسخ الاحتياطي {run.public_id}: "
                                f"{(run.last_error or 'خطأ غير معروف')[:300]}"
                            )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("scheduler failure")
                try:
                    async with self.context.database.session_factory() as incident_session:
                        await self.context.services.operations.record_incident(
                            incident_session,
                            code="SCH-MAIN",
                            severity="error",
                            source="scheduler",
                            summary="فشل دورة المهام الخلفية",
                            details=f"{type(exc).__name__}: {str(exc)[:2000]}",
                        )
                        await incident_session.commit()
                except Exception:
                    logger.exception("could not persist scheduler incident")
            await asyncio.sleep(interval)

    async def temporary_access_tick(self, session, now_utc: datetime) -> None:
        sessions = list(
            (
                await session.scalars(
                    select(TemporaryAccessSession)
                    .where(
                        TemporaryAccessSession.deletion_required.is_(True),
                        TemporaryAccessSession.deletion_acknowledged_at.is_(None),
                        TemporaryAccessSession.ends_at <= now_utc + timedelta(minutes=30),
                    )
                    .order_by(TemporaryAccessSession.ends_at)
                    .limit(200)
                )
            ).all()
        )
        for temp in sessions:
            order = await session.get(Order, temp.order_id)
            user = await session.get(User, temp.user_id)
            if not order or not user:
                continue
            ends_at = as_utc(temp.ends_at) or now_utc
            remaining = ends_at - now_utc
            if remaining > timedelta(minutes=10) and not temp.reminder_30m_sent:
                temp.reminder_30m_sent = True
                await self.context.services.notifications.send_user(
                    session,
                    user,
                    "تبقى 30 دقيقة للحساب المؤقت",
                    f"الطلب: <code>{order.public_id}</code>\nسجّل الخروج عند انتهاء المدة.",
                    idempotency_key=f"temp-30m:{temp.id}",
                )
            elif timedelta(0) < remaining <= timedelta(minutes=10) and not temp.reminder_10m_sent:
                temp.reminder_10m_sent = True
                await self.context.services.notifications.send_user(
                    session,
                    user,
                    "تبقى دقائق للحساب المؤقت",
                    f"الطلب: <code>{order.public_id}</code>\nاستعد لتسجيل الخروج وإرسال الإثبات.",
                    idempotency_key=f"temp-10m:{temp.id}",
                )
            if remaining <= timedelta(0) and not temp.expiry_sent:
                temp.expiry_sent = True
                await self.context.services.notifications.send_user(
                    session,
                    user,
                    "انتهت مدة الحساب المؤقت",
                    (
                        f"الطلب: <code>{order.public_id}</code>\n"
                        "سجّل الخروج الآن وأرسل صورة إثبات. لديك فترة سماح 30 دقيقة."
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(
                                text="📤 رفع إثبات تسجيل الخروج",
                                callback_data=f"tmp:proof_order:{order.id}",
                                style="success",
                            )],
                            [InlineKeyboardButton(
                                text="📡 لدي مشكلة في الإنترنت",
                                callback_data=f"tmp:review_order:{order.id}",
                                style="primary",
                            )],
                            [InlineKeyboardButton(
                                text="🆘 مركز المساعدة",
                                callback_data="announcement:open:support",
                            )],
                        ]
                    ),
                    idempotency_key=f"temp-expired:{temp.id}",
                )
        await self.context.services.provider_operations.escalate_overdue_temporary_access(
            session,
            grace_minutes=int(self.context.settings.temporary_logout_grace_minutes),
        )

    async def subscription_lifecycle(self, session) -> None:
        await self.context.services.subscriptions.sync_lifecycle(session)
        now = datetime.now(UTC)
        subscriptions = list(
            (
                await session.scalars(
                    select(ProviderSubscription).options(
                        selectinload(ProviderSubscription.plan),
                        selectinload(ProviderSubscription.provider),
                    )
                )
            ).all()
        )
        reminder_days = set(self.context.settings.subscription_reminder_days)
        for subscription in subscriptions:
            provider = subscription.provider
            if not provider or not subscription.ends_at:
                continue
            ends_at = as_utc(subscription.ends_at)
            if not ends_at:
                continue
            seconds = (ends_at - now).total_seconds()
            days_remaining = max(0, int((seconds + 86399) // 86400))
            title = "تنبيه اشتراك المنصة"
            body: str | None = None
            if 3 in reminder_days and 1 < days_remaining <= 3 and not subscription.reminder_3d_sent:
                subscription.reminder_3d_sent = True
                body = (
                    f"اشتراك {provider.name_ar} ينتهي خلال {days_remaining} أيام. "
                    "تواصل مع الإدارة للتجديد أو استخدم كوبونًا متاحًا."
                )
            elif (
                1 in reminder_days and 0 < days_remaining <= 1 and not subscription.reminder_1d_sent
            ):
                subscription.reminder_1d_sent = True
                body = (
                    f"اشتراك {provider.name_ar} ينتهي خلال أقل من يوم. "
                    "الطلبات الحالية والدعم سيبقيان متاحين، بينما تتوقف الخصائص المدفوعة بعد السماح."
                )
            elif (
                subscription.status
                in {
                    ProviderSubscriptionStatus.GRACE.value,
                    ProviderSubscriptionStatus.EXPIRED.value,
                }
                and not subscription.expiry_notice_sent
            ):
                subscription.expiry_notice_sent = True
                if subscription.status == ProviderSubscriptionStatus.GRACE.value:
                    body = (
                        f"انتهى اشتراك {provider.name_ar} ودخل فترة السماح حتى "
                        f"{subscription.grace_until:%Y-%m-%d}."
                    )
                else:
                    body = (
                        f"انتهى اشتراك {provider.name_ar}. تم إيقاف الخصائص المدفوعة "
                        "مع إبقاء الطلبات السابقة والدعم والسحب متاحة."
                    )
            if body:
                await self._notify_provider_staff(session, subscription.provider_id, title, body)

    async def student_subscription_lifecycle(self, session) -> None:
        await self.context.services.student_subscriptions.sync_statuses(session)
        now = datetime.now(UTC)
        subscriptions = list(
            (
                await session.scalars(
                    select(StudentSubscription).where(
                        StudentSubscription.ends_at.is_not(None),
                        StudentSubscription.status.in_(
                            [
                                StudentSubscriptionStatus.ACTIVE.value,
                                StudentSubscriptionStatus.EXPIRING.value,
                                StudentSubscriptionStatus.EXPIRED.value,
                            ]
                        ),
                    )
                )
            ).all()
        )
        for subscription in subscriptions:
            if not subscription.ends_at:
                continue
            ends_at = as_utc(subscription.ends_at)
            if not ends_at:
                continue
            seconds = (ends_at - now).total_seconds()
            days = max(0, int((seconds + 86399) // 86400))
            title = "تنبيه اشتراك الطالب"
            body = None
            if 0 < days <= 7 and not subscription.reminder_7d_sent:
                subscription.reminder_7d_sent = True
                body = (
                    f"اشتراكك في {subscription.offer_name_snapshot} من "
                    f"{subscription.provider_name_snapshot} سينتهي خلال {days} أيام "
                    f"بتاريخ {format_date(ends_at, self.context.settings.timezone)}."
                )
            if 0 < days <= 3 and not subscription.reminder_3d_sent:
                subscription.reminder_3d_sent = True
                body = (
                    f"اشتراكك في {subscription.offer_name_snapshot} سينتهي خلال {days} أيام. "
                    "يمكنك فتح «اشتراكاتي» لعرض الوصل أو طلب التجديد."
                )
            if 0 < days <= 1 and not subscription.reminder_1d_sent:
                subscription.reminder_1d_sent = True
                body = (
                    f"اشتراكك في {subscription.offer_name_snapshot} ينتهي خلال أقل من يوم "
                    f"بتاريخ {format_date(ends_at, self.context.settings.timezone)}."
                )
            if seconds <= 0 and not subscription.expiry_notice_sent:
                subscription.expiry_notice_sent = True
                body = (
                    f"انتهى اشتراكك في {subscription.offer_name_snapshot} بتاريخ "
                    f"{subscription.ends_at:%d/%m/%Y}."
                )
            if body:
                user = await session.get(User, subscription.user_id)
                if user:
                    await self.context.services.notifications.send_user(session, user, title, body)

    async def _notify_provider_staff(
        self, session, provider_id: int, title: str, body: str
    ) -> None:
        staff = list(
            (
                await session.scalars(
                    select(ProviderStaff).where(
                        ProviderStaff.provider_id == provider_id,
                        ProviderStaff.is_active.is_(True),
                    )
                )
            ).all()
        )
        for member in staff:
            user = await self.context.services.users.get_by_id(session, member.user_id)
            if user:
                await self.context.services.notifications.send_user(session, user, title, body)

    async def daily_reports(self, session, now_local: datetime) -> None:
        start = datetime(now_local.year, now_local.month, now_local.day, tzinfo=UTC)
        end = start + timedelta(days=1) - timedelta(microseconds=1)
        providers = (
            await session.scalars(
                select(Provider).where(Provider.status == ProviderStatus.ACTIVE.value)
            )
        ).all()
        for provider in providers:
            try:
                reports_enabled = await self.context.services.subscriptions.feature_enabled(
                    session, provider.id, "reports.basic"
                )
                if not reports_enabled:
                    continue
                report, token = await self.context.services.reports.create_provider_report(
                    session, provider, start, end, None
                )
                await self.context.services.reports.materialize_daily_metric(
                    session, report, now_local.date()
                )
                url = self.context.services.reports.report_url(token)
                staff = (
                    await session.scalars(
                        select(ProviderStaff).where(
                            ProviderStaff.provider_id == provider.id,
                            ProviderStaff.is_active.is_(True),
                            ProviderStaff.can_view_reports.is_(True),
                        )
                    )
                ).all()
                free_text = self.context.services.reports.free_message(report)
                for member in staff:
                    user = await self.context.services.users.get_by_id(session, member.user_id)
                    if user:
                        await self.context.bot.send_message(user.telegram_id, free_text)
            except ValueError:
                # The plan may intentionally limit the number of generated reports.
                continue
            except Exception as exc:
                logger.warning("report provider=%s: %s", provider.id, exc)
