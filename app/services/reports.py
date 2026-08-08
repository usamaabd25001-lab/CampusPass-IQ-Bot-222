from __future__ import annotations

import base64
import csv
import io
import mimetypes
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import qrcode
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import SecretBox
from app.core.time import as_utc
from app.services.report_artifacts import RenderedArtifact, ReportArtifactRenderer
from app.db.models import (
    DailyProviderMetric,
    EmailAccount,
    LedgerEntry,
    Offer,
    Order,
    PaymentProof,
    OrderStatus,
    Provider,
    ProviderBrandProfile,
    Report,
    ReportAccess,
    ReportArtifact,
    ReportArtifactStatus,
    Review,
    StudentProfile,
    StudentSubscription,
    StudentSubscriptionStatus,
    SystemSetting,
    User,
    WithdrawalRequest,
    WithdrawalStatus,
)

if TYPE_CHECKING:
    from app.services.subscriptions import SubscriptionService


class ReportService:
    def __init__(
        self,
        settings: Settings,
        secrets: SecretBox,
        subscriptions: SubscriptionService,
    ) -> None:
        self.settings = settings
        self.secrets = secrets
        self.subscriptions = subscriptions
        self.templates = Environment(
            loader=FileSystemLoader(str(Path(__file__).resolve().parents[1] / "reports" / "templates")),
            autoescape=select_autoescape(["html", "xml"]),
        )

    async def _usage_allowed(self, session: AsyncSession, provider: Provider) -> bool:
        month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        count = int(
            await session.scalar(
                select(func.count())
                .select_from(Report)
                .where(
                    Report.provider_id == provider.id,
                    Report.created_at >= month_start,
                )
            )
            or 0
        )
        entitlement = await self.subscriptions.effective_entitlement(
            session, provider.id, "reports.monthly"
        )
        if not entitlement.enabled:
            return False
        if entitlement.limit is None or entitlement.limit == -1:
            return True
        return count < entitlement.limit

    async def create_provider_report(
        self,
        session: AsyncSession,
        provider: Provider,
        period_start: datetime,
        period_end: datetime,
        created_by_user_id: int | None,
        report_type: str = "general",
        tier: str = "free",
    ) -> tuple[Report, str]:
        if not await self._usage_allowed(session, provider):
            raise ValueError("تم الوصول إلى حد التقارير في الخطة الحالية")
        rows = (
            await session.execute(
                select(
                    func.count(Order.id).label("orders"),
                    func.coalesce(func.sum(Order.subtotal_iqd), 0).label("sales"),
                    func.coalesce(func.sum(Order.service_fee_iqd), 0).label("service_fees"),
                    func.coalesce(func.sum(Order.management_fee_iqd), 0).label("management_fees"),
                    func.coalesce(func.sum(Order.provider_net_iqd), 0).label("provider_net"),
                    func.coalesce(func.sum(Order.owner_net_iqd), 0).label("owner_net"),
                    func.sum(case((Order.status == OrderStatus.COMPLETED.value, 1), else_=0)).label(
                        "completed"
                    ),
                    func.sum(case((Order.status == OrderStatus.REFUNDED.value, 1), else_=0)).label(
                        "refunded"
                    ),
                    func.sum(
                        case((Order.status == OrderStatus.NEEDS_SUPPORT.value, 1), else_=0)
                    ).label("support"),
                ).where(
                    Order.provider_id == provider.id,
                    Order.created_at >= period_start,
                    Order.created_at <= period_end,
                )
            )
        ).one()
        statuses = {
            status: int(count)
            for status, count in (
                await session.execute(
                    select(Order.status, func.count(Order.id))
                    .where(
                        Order.provider_id == provider.id,
                        Order.created_at >= period_start,
                        Order.created_at <= period_end,
                    )
                    .group_by(Order.status)
                )
            ).all()
        }
        top_offers = [
            {"title": title, "count": int(count), "sales": int(sales or 0)}
            for title, count, sales in (
                await session.execute(
                    select(
                        Offer.title,
                        func.count(Order.id),
                        func.sum(Order.subtotal_iqd),
                    )
                    .join(Offer, Offer.id == Order.offer_id)
                    .where(
                        Order.provider_id == provider.id,
                        Order.created_at >= period_start,
                        Order.created_at <= period_end,
                    )
                    .group_by(Offer.title)
                    .order_by(func.count(Order.id).desc())
                    .limit(3)
                )
            ).all()
        ]
        emails = [
            {
                "label": label,
                "username": self._mask_email(username),
                "used": used,
                "limit": limit,
                "status": status,
            }
            for label, username, used, limit, status in (
                await session.execute(
                    select(
                        EmailAccount.label,
                        EmailAccount.username,
                        EmailAccount.used_today,
                        EmailAccount.daily_limit,
                        EmailAccount.status,
                    ).where(EmailAccount.provider_id == provider.id)
                )
            ).all()
        ]
        provider_credits = int(
            await session.scalar(
                select(func.coalesce(func.sum(LedgerEntry.amount_iqd), 0)).where(
                    LedgerEntry.provider_id == provider.id,
                    LedgerEntry.account_code == "provider_payable",
                    LedgerEntry.direction == "credit",
                    LedgerEntry.status == "posted",
                )
            )
            or 0
        )
        provider_debits = int(
            await session.scalar(
                select(func.coalesce(func.sum(LedgerEntry.amount_iqd), 0)).where(
                    LedgerEntry.provider_id == provider.id,
                    LedgerEntry.account_code.in_(
                        ["provider_withdrawal", "provider_payable_refund"]
                    ),
                    LedgerEntry.direction == "debit",
                    LedgerEntry.status == "posted",
                )
            )
            or 0
        )
        rating_average, rating_count = (
            await session.execute(
                select(func.avg(Review.rating), func.count(Review.id)).where(
                    Review.provider_id == provider.id
                )
            )
        ).one()
        withdrawals_in_period = int(
            await session.scalar(
                select(func.coalesce(func.sum(WithdrawalRequest.amount_iqd), 0)).where(
                    WithdrawalRequest.provider_id == provider.id,
                    WithdrawalRequest.status == WithdrawalStatus.PAID.value,
                    WithdrawalRequest.processed_at >= period_start,
                    WithdrawalRequest.processed_at <= period_end,
                )
            )
            or 0
        )
        # V5 analytics are calculated from real order/student data and filtered by period.
        student_count = int(
            await session.scalar(
                select(func.count(func.distinct(Order.user_id))).where(
                    Order.provider_id == provider.id,
                    Order.created_at >= period_start,
                    Order.created_at <= period_end,
                )
            )
            or 0
        )
        new_students = int(
            await session.scalar(
                select(func.count(func.distinct(User.id)))
                .join(Order, Order.user_id == User.id)
                .where(
                    Order.provider_id == provider.id,
                    Order.created_at >= period_start,
                    Order.created_at <= period_end,
                    User.created_at >= period_start,
                    User.created_at <= period_end,
                )
            )
            or 0
        )

        async def top_profile(field):
            value, count = (
                await session.execute(
                    select(field, func.count(func.distinct(Order.user_id)))
                    .join(StudentProfile, StudentProfile.user_id == Order.user_id)
                    .where(
                        Order.provider_id == provider.id,
                        Order.created_at >= period_start,
                        Order.created_at <= period_end,
                        field.is_not(None),
                        field != "",
                    )
                    .group_by(field)
                    .order_by(func.count(func.distinct(Order.user_id)).desc())
                    .limit(1)
                )
            ).first() or ("غير متوفر", 0)
            return {"name": str(value or "غير متوفر"), "count": int(count or 0)}

        top_university = await top_profile(StudentProfile.university)
        top_college = await top_profile(StudentProfile.college)
        top_department = await top_profile(StudentProfile.department)
        top_stage = await top_profile(StudentProfile.stage)
        top_governorate = await top_profile(StudentProfile.governorate)

        async def ranked_profile(field, limit: int = 5):
            return [
                {"name": str(value or "غير محدد"), "count": int(count or 0)}
                for value, count in (
                    await session.execute(
                        select(field, func.count(func.distinct(Order.user_id)))
                        .join(StudentProfile, StudentProfile.user_id == Order.user_id)
                        .where(
                            Order.provider_id == provider.id,
                            Order.created_at >= period_start,
                            Order.created_at <= period_end,
                            field.is_not(None),
                            field != "",
                        )
                        .group_by(field)
                        .order_by(func.count(func.distinct(Order.user_id)).desc())
                        .limit(limit)
                    )
                ).all()
            ]

        profile_rankings = {
            "universities": await ranked_profile(StudentProfile.university),
            "colleges": await ranked_profile(StudentProfile.college),
            "departments": await ranked_profile(StudentProfile.department),
            "stages": await ranked_profile(StudentProfile.stage),
            "governorates": await ranked_profile(StudentProfile.governorate),
        }

        # Aggregate trend in Python to stay portable across PostgreSQL and SQLite tests.
        raw_orders = list(
            (
                await session.execute(
                    select(Order.created_at, Order.subtotal_iqd, Order.status).where(
                        Order.provider_id == provider.id,
                        Order.created_at >= period_start,
                        Order.created_at <= period_end,
                    )
                )
            ).all()
        )
        trend_map: dict[str, dict[str, int]] = {}
        for created_at, subtotal, status in raw_orders:
            key = created_at.strftime("%Y-%m-%d")
            row = trend_map.setdefault(key, {"orders": 0, "sales": 0, "completed": 0})
            row["orders"] += 1
            row["sales"] += int(subtotal or 0)
            if status == OrderStatus.COMPLETED.value:
                row["completed"] += 1
        trend = [
            {"label": key, **values}
            for key, values in sorted(trend_map.items())[-31:]
        ]

        rating_distribution = {
            str(rating): int(count)
            for rating, count in (
                await session.execute(
                    select(Review.rating, func.count(Review.id))
                    .where(
                        Review.provider_id == provider.id,
                        Review.created_at >= period_start,
                        Review.created_at <= period_end,
                    )
                    .group_by(Review.rating)
                )
            ).all()
        }
        withdrawals = [
            {
                "public_id": public_id,
                "amount": int(amount or 0),
                "status": status,
                "date": created_at.isoformat(),
            }
            for public_id, amount, status, created_at in (
                await session.execute(
                    select(
                        WithdrawalRequest.public_id,
                        WithdrawalRequest.amount_iqd,
                        WithdrawalRequest.status,
                        WithdrawalRequest.created_at,
                    )
                    .where(
                        WithdrawalRequest.provider_id == provider.id,
                        WithdrawalRequest.created_at >= period_start,
                        WithdrawalRequest.created_at <= period_end,
                    )
                    .order_by(WithdrawalRequest.created_at.desc())
                    .limit(10)
                )
            ).all()
        ]
        active_subscriptions = int(
            await session.scalar(
                select(func.count()).select_from(StudentSubscription).where(
                    StudentSubscription.provider_id == provider.id,
                    StudentSubscription.status.in_(
                        [
                            StudentSubscriptionStatus.ACTIVE.value,
                            StudentSubscriptionStatus.EXPIRING.value,
                        ]
                    ),
                )
            )
            or 0
        )
        rejected_or_problem = int(
            await session.scalar(
                select(func.count()).select_from(Order).where(
                    Order.provider_id == provider.id,
                    Order.created_at >= period_start,
                    Order.created_at <= period_end,
                    Order.status.in_(
                        [
                            OrderStatus.PAYMENT_REJECTED.value,
                            OrderStatus.NEEDS_SUPPORT.value,
                            OrderStatus.CANCELLED.value,
                            OrderStatus.REFUNDED.value,
                        ]
                    ),
                )
            )
            or 0
        )
        confirmation_samples = list(
            (
                await session.execute(
                    select(PaymentProof.created_at, PaymentProof.reviewed_at)
                    .join(Order, Order.id == PaymentProof.order_id)
                    .where(
                        Order.provider_id == provider.id,
                        PaymentProof.created_at >= period_start,
                        PaymentProof.created_at <= period_end,
                        PaymentProof.reviewed_at.is_not(None),
                    )
                )
            ).all()
        )
        confirmation_seconds = [
            max(0, int((reviewed - created).total_seconds()))
            for created, reviewed in confirmation_samples
            if created is not None and reviewed is not None
        ]
        average_confirmation_seconds = (
            int(sum(confirmation_seconds) / len(confirmation_seconds))
            if confirmation_seconds
            else 0
        )

        valid_types = {
            "general",
            "students",
            "sales",
            "academics",
            "governorates",
            "ratings",
            "withdrawals",
            "provider_daily",
        }
        if report_type not in valid_types:
            report_type = "general"
        if tier == "standard":
            tier = "free"
        if tier not in {"free", "plus", "pro"}:
            tier = "free"
        report_titles = {
            "general": "التقرير العام للمنصة",
            "provider_daily": "التقرير العام للمنصة",
            "students": "تقرير الطلاب",
            "sales": "تقرير المبيعات والمشتريات",
            "academics": "تقرير الكليات والتخصصات",
            "governorates": "تقرير المحافظات",
            "ratings": "تقرير التقييمات ورضا الطلاب",
            "withdrawals": "تقرير السحوبات والمستحقات",
        }

        logo_data_uri = await session.scalar(
            select(SystemSetting.value).where(
                SystemSetting.key == f"provider.logo_data_uri.{provider.id}"
            )
        )
        brand_profile = await session.scalar(
            select(ProviderBrandProfile).where(ProviderBrandProfile.provider_id == provider.id)
        )
        provider_dark_color = await session.scalar(
            select(SystemSetting.value).where(
                SystemSetting.key == f"provider.brand_dark_color.{provider.id}"
            )
        )
        provider_name_en = (provider.name_en or "").strip()
        if not provider_name_en:
            provider_name_en = provider.name_ar

        tier_features = {
            "free": {
                "operational_summary": True,
                "financial_summary": False,
                "statuses": True,
                "top_offers": False,
                "trend": False,
                "ratings": False,
                "student_summary": False,
                "academic_rankings": False,
                "email_usage": False,
                "withdrawals": False,
            },
            "plus": {
                "operational_summary": True,
                "financial_summary": True,
                "statuses": True,
                "top_offers": True,
                "trend": True,
                "ratings": True,
                "student_summary": True,
                "academic_rankings": False,
                "email_usage": True,
                "withdrawals": False,
            },
            "pro": {
                "operational_summary": True,
                "financial_summary": True,
                "statuses": True,
                "top_offers": True,
                "trend": True,
                "ratings": True,
                "student_summary": True,
                "academic_rankings": True,
                "email_usage": True,
                "withdrawals": True,
            },
        }[tier]

        snapshot = {
            "provider": {
                "id": provider.id,
                "name_ar": provider.name_ar,
                "name_en": provider_name_en,
                "logo_url": provider.logo_url,
                "logo_file_id": provider.logo_file_id,
                "logo_data_uri": logo_data_uri or "",
                "primary_color": brand_profile.primary_color if brand_profile else self.settings.brand_primary_color,
                "secondary_color": brand_profile.secondary_color if brand_profile else self.settings.brand_secondary_color,
                "dark_color": provider_dark_color or self.settings.brand_dark_color,
            },
            "summary": {
                "orders": int(rows.orders or 0),
                "sales": int(rows.sales or 0),
                "service_fees": int(rows.service_fees or 0),
                "management_fees": int(rows.management_fees or 0),
                "provider_net": int(rows.provider_net or 0),
                "owner_net": int(rows.owner_net or 0),
                "completed": int(rows.completed or 0),
                "refunded": int(rows.refunded or 0),
                "support": int(rows.support or 0),
                "rating_average": round(float(rating_average or 0), 2),
                "rating_count": int(rating_count or 0),
                "withdrawals_paid": withdrawals_in_period,
                "available_balance": provider_credits - provider_debits,
                "net_withdrawal_today": max(0, int(rows.provider_net or 0) - withdrawals_in_period),
                "active_subscriptions": active_subscriptions,
                "rejected_or_problem": rejected_or_problem,
                "average_confirmation_seconds": average_confirmation_seconds,
            },
            "statuses": statuses,
            "top_offers": top_offers,
            "emails": emails,
            "report_meta": {
                "type": report_type,
                "title": report_titles[report_type],
                "tier": tier,
                "tier_label": {"free": "Free", "plus": "Plus", "pro": "Pro"}[tier],
                "tier_features": tier_features,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
            "students": {
                "total": student_count,
                "new": new_students,
                "top_university": top_university,
                "top_college": top_college,
                "top_department": top_department,
                "top_stage": top_stage,
                "top_governorate": top_governorate,
            },
            "profile_rankings": profile_rankings,
            "trend": trend,
            "rating_distribution": rating_distribution,
            "withdrawals": withdrawals,
        }

        # Store only the data allowed by the selected tier. This is enforcement,
        # not merely a visual hide in the HTML template.
        if tier == "free":
            snapshot["summary"] = {
                "orders": snapshot["summary"]["orders"],
                "completed": snapshot["summary"]["completed"],
                "support": snapshot["summary"]["support"],
                "active_subscriptions": snapshot["summary"]["active_subscriptions"],
                "rejected_or_problem": snapshot["summary"]["rejected_or_problem"],
            }
            snapshot["top_offers"] = []
            snapshot["emails"] = []
            snapshot["students"] = {}
            snapshot["profile_rankings"] = {}
            snapshot["trend"] = []
            snapshot["rating_distribution"] = {}
            snapshot["withdrawals"] = []
        elif tier == "plus":
            snapshot["profile_rankings"] = {}
            snapshot["withdrawals"] = []

        expires = datetime.now(UTC) + timedelta(days=self.settings.report_token_days)
        report = Report(
            provider_id=provider.id,
            report_type=report_type,
            period_start=period_start,
            period_end=period_end,
            snapshot=snapshot,
            plan=tier,
            created_by_user_id=created_by_user_id,
            expires_at=expires,
        )
        session.add(report)
        await session.flush()
        token = self.secrets.sign_report(report.id, expires)
        session.add(
            ReportAccess(
                report_id=report.id,
                token_hash=self.secrets.hash_value(token),
                max_accesses=self.settings.report_max_accesses,
            )
        )
        await session.flush()
        return report, token


    async def purge_expired_snapshots(self, session: AsyncSession) -> int:
        """Purge heavy rendered report snapshots after the retention window.

        Financial/order source rows are never deleted here. Report metadata stays
        in place for audit and plan-usage accounting, so annual reports can always
        be regenerated from the original transactional data.
        """
        cutoff = datetime.now(UTC) - timedelta(days=self.settings.report_snapshot_retention_days)
        candidates = list((await session.scalars(
            select(Report).where(Report.created_at < cutoff).limit(500)
        )).all())
        reports = [report for report in candidates if bool(report.snapshot)]
        if not reports:
            return 0
        for report in reports:
            report.snapshot = {}
            access = await session.scalar(
                select(ReportAccess).where(ReportAccess.report_id == report.id)
            )
            if access and access.revoked_at is None:
                access.revoked_at = datetime.now(UTC)
        await session.flush()
        return len(reports)

    async def resolve_report(self, session: AsyncSession, token: str) -> Report | None:
        report_id = self.secrets.verify_report(token)
        if not report_id:
            return None
        access = await session.scalar(
            select(ReportAccess)
            .where(
                ReportAccess.report_id == report_id,
                ReportAccess.token_hash == self.secrets.hash_value(token),
            )
            .with_for_update()
        )
        if not access or access.revoked_at is not None:
            return None
        if access.access_count >= access.max_accesses:
            return None
        report = await session.get(Report, report_id)
        if not report or (
            as_utc(report.expires_at) and as_utc(report.expires_at) < datetime.now(UTC)
        ):
            return None
        access.access_count += 1
        access.last_access_at = datetime.now(UTC)
        await session.flush()
        return report

    async def revoke_report(self, session: AsyncSession, report_id: int) -> bool:
        access = await session.scalar(
            select(ReportAccess).where(ReportAccess.report_id == report_id).with_for_update()
        )
        if not access or access.revoked_at is not None:
            return False
        access.revoked_at = datetime.now(UTC)
        await session.flush()
        return True

    @staticmethod
    def _mask_email(value: str) -> str:
        text = (value or "").strip()
        if "@" not in text:
            return "***" if text else ""
        local, domain = text.split("@", 1)
        if len(local) <= 2:
            masked = local[:1] + "***"
        else:
            masked = local[:2] + "***" + local[-1:]
        return f"{masked}@{domain}"

    def report_url(self, token: str) -> str:
        base = self.settings.public_base_url.rstrip("/")
        return f"{base}/reports/{token}" if base else f"/reports/{token}"

    def report_download_url(self, token: str, fmt: str) -> str:
        return f"{self.report_url(token)}/download/{fmt.strip().lower()}"

    @staticmethod
    def filename(report: Report, suffix: str) -> str:
        provider = (report.snapshot or {}).get("provider", {})
        slug = (
            provider.get("name_en") or provider.get("name_ar") or f"provider-{report.provider_id}"
        )
        normalized = "".join(ch if ch.isalnum() else "-" for ch in str(slug)).strip("-") or "report"
        report_type = (report.snapshot or {}).get("report_meta", {}).get("type", report.report_type)
        month = report.period_end.strftime("%b%Y")
        return f"CampusPass_Report_{normalized}_{month}_{report.id}.{suffix}"

    @staticmethod
    def _format_amount(value: int | float) -> str:
        return f"{int(value or 0):,} د.ع"

    @staticmethod
    def _is_remote_image(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https", "data"}

    def _read_local_image_as_data_uri(self, raw_path: str) -> str:
        path = Path(raw_path)
        if not path.is_absolute():
            project_root = Path(__file__).resolve().parents[2]
            path = project_root / path
        if not path.exists() or not path.is_file():
            return ""
        mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
        payload = base64.b64encode(path.read_bytes()).decode()
        return f"data:{mime_type};base64,{payload}"

    def _image_src(self, value: str) -> str:
        candidate = (value or "").strip()
        if not candidate:
            return ""
        if self._is_remote_image(candidate):
            return candidate
        return self._read_local_image_as_data_uri(candidate)

    def _branding(self, report: Report) -> dict[str, str | bool]:
        snapshot = report.snapshot or {}
        provider = snapshot.get("provider", {})
        provider_logo = self._image_src(provider.get("logo_data_uri", "")) or self._image_src(provider.get("logo_url", ""))
        primary = str(provider.get("primary_color") or self.settings.brand_primary_color)
        secondary = str(provider.get("secondary_color") or self.settings.brand_secondary_color)
        dark = str(provider.get("dark_color") or self.settings.brand_dark_color)
        return {
            "brand_logo_src": self._image_src(self.settings.bot_logo_url)
            or self._read_local_image_as_data_uri("app/reports/assets/campuspass-iq-horizontal-v11.png")
            or self._read_local_image_as_data_uri(self.settings.export_logo_path),
            "brand_mark_src": self._read_local_image_as_data_uri("app/reports/assets/campuspass-iq-square-v11.png"),
            "provider_logo_src": provider_logo,
            "provider_logo_available": bool(provider_logo),
            "provider_logo_hint": (
                "أعد رفع شعار المنصة من لوحة الإدارة ليتم تضمينه داخل التقارير."
                if provider.get("logo_file_id") and not provider_logo
                else "أضف شعار المنصة داخل البوت ليظهر تلقائيًا في كل ملف مُصدر."
            ),
            "primary_color": primary,
            "secondary_color": secondary,
            "dark_color": dark,
            "campuspass_primary": self.settings.brand_primary_color,
            "campuspass_secondary": self.settings.brand_secondary_color,
        }

    @staticmethod
    def _features_for_tier(tier: str) -> dict[str, bool]:
        normalized = (tier or "free").strip().lower()
        if normalized not in {"free", "plus", "pro"}:
            normalized = "free"
        common = {
            "operational_summary": True,
            "financial_summary": normalized != "free",
            "statuses": True,
            "top_offers": False,
            "trend": False,
            "ratings": False,
            "student_summary": False,
            "academic_rankings": False,
            "email_usage": False,
            "withdrawals": False,
        }
        if normalized in {"plus", "pro"}:
            common.update(
                {
                    "top_offers": True,
                    "trend": True,
                    "ratings": True,
                    "student_summary": True,
                    "email_usage": True,
                }
            )
        if normalized == "pro":
            common.update({"academic_rankings": True, "withdrawals": True})
        return common

    def render(self, report: Report, verification_url: str = "") -> str:
        snapshot = report.snapshot or {}
        report_meta = snapshot.get("report_meta", {})
        tier = str(report_meta.get("tier", report.plan or "free")).lower()
        features = report_meta.get("tier_features") or self._features_for_tier(tier)
        template_name = "provider_v5.html" if report_meta else "provider_daily.html"
        template = self.templates.get_template(template_name)
        qr_data_uri = ""
        if verification_url:
            image = qrcode.make(verification_url)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            qr_data_uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
        return template.render(
            bot_name=self.settings.bot_name,
            bot_name_en=self.settings.bot_name_en,
            report=report,
            data=snapshot,
            branding=self._branding(report),
            verification_url=verification_url,
            qr_data_uri=qr_data_uri,
            report_filename=self.filename(report, "html"),
            tier=tier,
            features=features,
            amount=self._format_amount,
        )

    def free_message(self, report: Report) -> str:
        snapshot = report.snapshot or {}
        provider = snapshot.get("provider", {})
        summary = snapshot.get("summary", {})
        return (
            f"📊 <b>تقرير {provider.get('name_ar') or provider.get('name_en') or 'المنصة'}</b>\n"
            f"الفترة: {report.period_start:%Y-%m-%d} - {report.period_end:%Y-%m-%d}\n\n"
            f"• إجمالي الطلبات: <b>{int(summary.get('orders', 0)):,}</b>\n"
            f"• الاشتراكات الفعالة: <b>{int(summary.get('active_subscriptions', 0)):,}</b>\n"
            f"• الطلبات المكتملة: <b>{int(summary.get('completed', 0)):,}</b>\n"
            f"• المرفوضة أو التي تحتاج معالجة: <b>{int(summary.get('rejected_or_problem', summary.get('support', 0))):,}</b>\n\n"
            "CampusPass IQ - Access. Services. Success."
        )

    async def materialize_daily_metric(
        self, session: AsyncSession, report: Report, metric_date: date
    ) -> DailyProviderMetric:
        aggregates = (await session.execute(
            select(
                func.count(Order.id),
                func.sum(case((Order.status == OrderStatus.COMPLETED.value, 1), else_=0)),
                func.sum(case((Order.status.in_([OrderStatus.PAYMENT_REJECTED.value, OrderStatus.NEEDS_SUPPORT.value, OrderStatus.CANCELLED.value, OrderStatus.REFUNDED.value]), 1), else_=0)),
                func.coalesce(func.sum(Order.subtotal_iqd), 0),
                func.coalesce(func.sum(Order.service_fee_iqd + Order.management_fee_iqd), 0),
                func.coalesce(func.sum(Order.provider_net_iqd), 0),
            ).where(
                Order.provider_id == report.provider_id,
                Order.created_at >= report.period_start,
                Order.created_at <= report.period_end,
            )
        )).one()
        active_subscriptions = int(await session.scalar(
            select(func.count()).select_from(StudentSubscription).where(
                StudentSubscription.provider_id == report.provider_id,
                StudentSubscription.status.in_([StudentSubscriptionStatus.ACTIVE.value, StudentSubscriptionStatus.EXPIRING.value]),
            )
        ) or 0)
        samples = list((await session.execute(
            select(PaymentProof.created_at, PaymentProof.reviewed_at)
            .join(Order, Order.id == PaymentProof.order_id)
            .where(
                Order.provider_id == report.provider_id,
                PaymentProof.created_at >= report.period_start,
                PaymentProof.created_at <= report.period_end,
                PaymentProof.reviewed_at.is_not(None),
            )
        )).all())
        durations = [max(0, int((reviewed-created).total_seconds())) for created, reviewed in samples if created and reviewed]
        values = {
            "orders_count": int(aggregates[0] or 0),
            "completed_count": int(aggregates[1] or 0),
            "rejected_or_problem_count": int(aggregates[2] or 0),
            "active_subscriptions_count": active_subscriptions,
            "sales_iqd": int(aggregates[3] or 0),
            "bot_fees_iqd": int(aggregates[4] or 0),
            "provider_net_iqd": int(aggregates[5] or 0),
            "average_confirmation_seconds": int(sum(durations)/len(durations)) if durations else 0,
            "snapshot_json": {"report_id": report.id, "period_start": report.period_start.isoformat(), "period_end": report.period_end.isoformat()},
            "computed_at": datetime.now(UTC),
        }
        row = await session.scalar(select(DailyProviderMetric).where(
            DailyProviderMetric.provider_id == report.provider_id,
            DailyProviderMetric.metric_date == metric_date,
        ).with_for_update())
        if row is None:
            row = DailyProviderMetric(provider_id=report.provider_id, metric_date=metric_date, **values)
            session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await session.flush()
        return row

    def render_artifact(
        self, report: Report, *, verification_url: str = "", format: str = "html"
    ) -> RenderedArtifact:
        rendered = self.render(report, verification_url=verification_url)
        normalized = format.strip().lower()
        if normalized == "html":
            return ReportArtifactRenderer.html(rendered, self.filename(report, "html"))
        if normalized == "pdf":
            if str(report.plan).lower() != "pro":
                raise ValueError("PDF الرسمي متاح لتقارير Pro فقط")
            return ReportArtifactRenderer.pdf(
                rendered,
                self.filename(report, "pdf"),
                base_url=str(Path(__file__).resolve().parents[2]),
            )
        raise ValueError("صيغة التقرير غير مدعومة")

    async def record_artifact(
        self, session: AsyncSession, report: Report, artifact: RenderedArtifact
    ) -> ReportArtifact:
        row = await session.scalar(select(ReportArtifact).where(
            ReportArtifact.report_id == report.id, ReportArtifact.format == artifact.format
        ).with_for_update())
        values = {
            "status": ReportArtifactStatus.READY.value,
            "filename": artifact.filename,
            "media_type": artifact.media_type,
            "sha256": artifact.sha256,
            "byte_size": len(artifact.content),
            "generated_at": datetime.now(UTC),
            "expires_at": report.expires_at,
            "error": "",
        }
        if row is None:
            row = ReportArtifact(report_id=report.id, format=artifact.format, **values)
            session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await session.flush()
        return row

    def export_csv(self, report: Report) -> str:
        snapshot = report.snapshot or {}
        provider = snapshot.get("provider", {})
        summary = snapshot.get("summary", {})
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["CampusPass IQ", "Operational & Financial Report"])
        writer.writerow(["Provider", provider.get("name_ar", "")])
        writer.writerow(["Provider EN", provider.get("name_en", "")])
        writer.writerow(["Report ID", report.id])
        writer.writerow(["Period Start", report.period_start.isoformat()])
        writer.writerow(["Period End", report.period_end.isoformat()])
        writer.writerow([])
        writer.writerow(["Summary"])
        writer.writerow(["Metric", "Value"])
        metrics = [
            ("Orders", summary.get("orders", 0)),
            ("Sales IQD", summary.get("sales", 0)),
            ("Provider Net IQD", summary.get("provider_net", 0)),
            ("Owner Net IQD", summary.get("owner_net", 0)),
            ("Service Fees IQD", summary.get("service_fees", 0)),
            ("Management Fees IQD", summary.get("management_fees", 0)),
            ("Completed", summary.get("completed", 0)),
            ("Refunded", summary.get("refunded", 0)),
            ("Needs Support", summary.get("support", 0)),
            ("Withdrawals Paid IQD", summary.get("withdrawals_paid", 0)),
            ("Available Balance IQD", summary.get("available_balance", 0)),
            ("Rating Average", summary.get("rating_average", 0)),
            ("Rating Count", summary.get("rating_count", 0)),
        ]
        writer.writerows(metrics)
        writer.writerow([])
        writer.writerow(["Order Statuses"])
        writer.writerow(["Status", "Count"])
        for status, count in (snapshot.get("statuses") or {}).items():
            writer.writerow([status, count])
        writer.writerow([])
        writer.writerow(["Top Offers"])
        writer.writerow(["Offer", "Orders", "Sales IQD"])
        for item in snapshot.get("top_offers") or []:
            writer.writerow([item.get("title", ""), item.get("count", 0), item.get("sales", 0)])
        writer.writerow([])
        writer.writerow(["Email Usage"])
        writer.writerow(["Label", "Email", "Used Today", "Limit", "Status"])
        for item in snapshot.get("emails") or []:
            writer.writerow(
                [
                    item.get("label", ""),
                    item.get("username", ""),
                    item.get("used", 0),
                    item.get("limit", 0),
                    item.get("status", ""),
                ]
            )
        return output.getvalue()
