from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.time import as_utc
from app.db.models import (
    CouponKind,
    PlanEntitlement,
    Provider,
    ProviderCommissionOverride,
    ProviderCoupon,
    ProviderCouponRedemption,
    ProviderFeatureOverride,
    ProviderSubscription,
    ProviderSubscriptionStatus,
    SubscriptionChangeLog,
    SubscriptionPlan,
    User,
)


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    key: str
    label: str
    description: str
    essential_after_expiry: bool = False


@dataclass(frozen=True, slots=True)
class LimitDefinition:
    key: str
    label: str
    description: str


FEATURES: Final[tuple[FeatureDefinition, ...]] = (
    FeatureDefinition("orders.view", "مشاهدة الطلبات", "متابعة الطلبات السابقة والحالية.", True),
    FeatureDefinition("payments.review", "تدقيق المدفوعات", "تأكيد أو رفض إثباتات الدفع.", True),
    FeatureDefinition("support.manage", "إدارة الدعم", "الرد على التذاكر والشكاوى.", True),
    FeatureDefinition("withdrawals.request", "طلب السحب", "طلب سحب المستحقات المتاحة.", True),
    FeatureDefinition("sales.accept", "استقبال طلبات جديدة", "السماح للطلاب بإنشاء طلبات جديدة."),
    FeatureDefinition("offers.manage", "إدارة العروض", "إضافة العروض وتعديلها وإيقافها."),
    FeatureDefinition("inventory.manage", "إدارة المخزون", "إضافة الأكواد والحسابات والمخزون."),
    FeatureDefinition("emails.manage", "إدارة الإيميلات", "ربط إيميلات التفعيل ومراقبة استخدامها."),
    FeatureDefinition("reports.basic", "التقارير الأساسية", "إنشاء تقارير HTML أساسية."),
    FeatureDefinition("reports.advanced", "التقارير المتقدمة", "فترات مخصصة ورسوم وتحليلات موسعة."),
    FeatureDefinition("reports.export", "تصدير التقارير", "تصدير Excel وPDF عندما تتوفر الصيغة."),
    FeatureDefinition("staff.manage", "إدارة الموظفين", "إضافة موظفين وصلاحيات للمنصة."),
    FeatureDefinition("broadcasts.send", "الحملات والإشعارات", "إرسال حملات موجهة لعملاء المنصة."),
    FeatureDefinition("gemini.support", "Gemini للدعم", "استخدام المساعد الذكي في الدعم."),
    FeatureDefinition("api.access", "واجهة API", "السماح بالتكامل البرمجي الخارجي."),
)

LIMITS: Final[tuple[LimitDefinition, ...]] = (
    LimitDefinition("offers.max", "أقصى عدد عروض", "-1 يعني غير محدود."),
    LimitDefinition("staff.max", "أقصى عدد موظفين", "عدد موظفي المنصة المسموح."),
    LimitDefinition("reports.monthly", "تقارير الشهر", "عدد التقارير الممكن إنشاؤها شهريًا."),
    LimitDefinition("emails.max", "أقصى عدد إيميلات", "عدد حسابات التفعيل المرتبطة."),
    LimitDefinition("broadcasts.monthly", "حملات الشهر", "عدد الحملات الجماعية شهريًا."),
    LimitDefinition("orders.monthly", "طلبات الشهر", "-1 يعني غير محدود."),
    LimitDefinition("report_history_days", "مدة سجل التقارير", "عدد الأيام المتاحة في التقارير."),
)

FEATURE_LABELS: Final[dict[str, str]] = {item.key: item.label for item in FEATURES}
LIMIT_LABELS: Final[dict[str, str]] = {item.key: item.label for item in LIMITS}
FEATURE_TOKENS: Final[dict[str, str]] = {str(index): item.key for index, item in enumerate(FEATURES)}
LIMIT_TOKENS: Final[dict[str, str]] = {str(index): item.key for index, item in enumerate(LIMITS)}


def feature_token(key: str) -> str:
    return next((token for token, value in FEATURE_TOKENS.items() if value == key), key)


def feature_key_from_token(token: str) -> str | None:
    key = FEATURE_TOKENS.get(token, token)
    return key if key in FEATURE_LABELS else None


def limit_token(key: str) -> str:
    return next((token for token, value in LIMIT_TOKENS.items() if value == key), key)


def limit_key_from_token(token: str) -> str | None:
    key = LIMIT_TOKENS.get(token, token)
    return key if key in LIMIT_LABELS else None
ESSENTIAL_FEATURES: Final[frozenset[str]] = frozenset(
    item.key for item in FEATURES if item.essential_after_expiry
)


@dataclass(slots=True)
class EntitlementResult:
    enabled: bool
    limit: int | None
    source: str
    subscription_status: str


class SubscriptionService:
    def __init__(self, default_plan_code: str = "free", default_grace_days: int = 3) -> None:
        self.default_plan_code = default_plan_code
        self.default_grace_days = default_grace_days

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    async def get_plan(self, session: AsyncSession, code: str) -> SubscriptionPlan | None:
        return await session.scalar(
            select(SubscriptionPlan)
            .options(selectinload(SubscriptionPlan.features))
            .where(SubscriptionPlan.code == code, SubscriptionPlan.is_active.is_(True))
        )

    async def list_plans(self, session: AsyncSession) -> list[SubscriptionPlan]:
        return list(
            (
                await session.scalars(
                    select(SubscriptionPlan)
                    .options(selectinload(SubscriptionPlan.features))
                    .where(SubscriptionPlan.is_active.is_(True))
                    .order_by(SubscriptionPlan.sort_order, SubscriptionPlan.price_iqd)
                )
            )
            .unique()
            .all()
        )

    async def create_plan(
        self,
        session: AsyncSession,
        *,
        code: str,
        name_ar: str,
        price_iqd: int,
        billing_days: int,
        grace_days: int,
        actor: User | None = None,
        inherit_from: str = "free",
        description: str = "",
    ) -> SubscriptionPlan:
        normalized = code.strip().lower().replace(" ", "-")
        if not normalized or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for char in normalized
        ):
            raise ValueError("رمز الباقة يجب أن يكون إنجليزيًا بدون مسافات.")
        if await session.scalar(
            select(SubscriptionPlan.id).where(SubscriptionPlan.code == normalized)
        ):
            raise ValueError("رمز الباقة مستخدم مسبقًا.")
        if price_iqd < 0 or not 1 <= billing_days <= 1095 or not 0 <= grace_days <= 90:
            raise ValueError("بيانات السعر أو المدة غير صحيحة.")
        source = await self.get_plan(session, inherit_from)
        plan = SubscriptionPlan(
            code=normalized,
            name_ar=name_ar.strip()[:120],
            name_en=normalized.replace("-", " ").title(),
            description=description.strip()[:2000],
            price_iqd=price_iqd,
            billing_days=billing_days,
            grace_days=grace_days,
            sort_order=100,
            is_system=False,
            is_active=True,
        )
        session.add(plan)
        await session.flush()
        if source:
            session.add_all(
                [
                    PlanEntitlement(
                        plan_id=plan.id,
                        feature_key=item.feature_key,
                        is_enabled=item.is_enabled,
                        limit_value=item.limit_value,
                        metadata_json=dict(item.metadata_json or {}),
                    )
                    for item in source.features
                ]
            )
        await session.flush()
        return plan

    async def set_plan_feature(
        self,
        session: AsyncSession,
        plan: SubscriptionPlan,
        feature_key: str,
        enabled: bool,
    ) -> PlanEntitlement:
        if feature_key not in FEATURE_LABELS:
            raise ValueError("الميزة غير معروفة.")
        row = await session.scalar(
            select(PlanEntitlement).where(
                PlanEntitlement.plan_id == plan.id,
                PlanEntitlement.feature_key == feature_key,
            )
        )
        if row is None:
            row = PlanEntitlement(plan_id=plan.id, feature_key=feature_key, is_enabled=enabled)
            session.add(row)
        else:
            row.is_enabled = enabled
        await session.flush()
        return row

    async def set_plan_limit(
        self,
        session: AsyncSession,
        plan: SubscriptionPlan,
        limit_key: str,
        value: int | None,
    ) -> PlanEntitlement:
        if limit_key not in LIMIT_LABELS:
            raise ValueError("الحد غير معروف.")
        row = await session.scalar(
            select(PlanEntitlement).where(
                PlanEntitlement.plan_id == plan.id,
                PlanEntitlement.feature_key == limit_key,
            )
        )
        if row is None:
            row = PlanEntitlement(
                plan_id=plan.id,
                feature_key=limit_key,
                is_enabled=True,
                limit_value=value,
            )
            session.add(row)
        else:
            row.is_enabled = True
            row.limit_value = value
        await session.flush()
        return row

    async def set_custom_price(
        self,
        session: AsyncSession,
        provider: Provider,
        value_iqd: int | None,
        actor: User | None,
        reason: str = "سعر مخصص",
    ) -> ProviderSubscription:
        if value_iqd is not None and value_iqd < 0:
            raise ValueError("السعر لا يمكن أن يكون سالبًا.")
        subscription = await self.ensure_subscription(session, provider, actor)
        old = self.snapshot(subscription)
        subscription.custom_price_iqd = value_iqd
        await session.flush()
        await self._log(
            session,
            provider.id,
            actor,
            "subscription.custom_price",
            old,
            self.snapshot(subscription),
            reason,
        )
        return subscription

    async def get_subscription(
        self, session: AsyncSession, provider_id: int
    ) -> ProviderSubscription | None:
        subscription = await session.scalar(
            select(ProviderSubscription)
            .options(
                selectinload(ProviderSubscription.plan).selectinload(SubscriptionPlan.features)
            )
            .where(ProviderSubscription.provider_id == provider_id)
        )
        if subscription:
            self._refresh_status(subscription)
        return subscription

    def _refresh_status(
        self, subscription: ProviderSubscription, now: datetime | None = None
    ) -> str:
        now = now or self._now()
        if subscription.status in {
            ProviderSubscriptionStatus.PAUSED.value,
            ProviderSubscriptionStatus.CANCELLED.value,
        }:
            return subscription.status
        ends_at = as_utc(subscription.ends_at)
        grace_until = as_utc(subscription.grace_until)
        if ends_at is None or now <= ends_at:
            subscription.status = (
                ProviderSubscriptionStatus.TRIAL.value
                if subscription.is_trial
                else ProviderSubscriptionStatus.ACTIVE.value
            )
            return subscription.status
        if grace_until and now <= grace_until:
            subscription.status = ProviderSubscriptionStatus.GRACE.value
            return subscription.status
        subscription.status = ProviderSubscriptionStatus.EXPIRED.value
        return subscription.status

    async def ensure_subscription(
        self,
        session: AsyncSession,
        provider: Provider,
        actor: User | None = None,
    ) -> ProviderSubscription:
        existing = await self.get_subscription(session, provider.id)
        if existing:
            return existing
        plan = await self.get_plan(session, self.default_plan_code)
        if not plan:
            raise RuntimeError(f"Default subscription plan {self.default_plan_code!r} is missing")
        now = self._now()
        subscription = ProviderSubscription(
            provider_id=provider.id,
            plan_id=plan.id,
            plan=plan,
            status=ProviderSubscriptionStatus.ACTIVE.value,
            starts_at=now,
            ends_at=None if plan.code == "free" else now + timedelta(days=plan.billing_days),
            grace_until=None,
            is_trial=False,
            created_by_user_id=actor.id if actor else None,
            note="اشتراك افتراضي أنشئ تلقائيًا",
        )
        session.add(subscription)
        await session.flush()
        await self._log(
            session,
            provider.id,
            actor,
            "subscription.created",
            {},
            self.snapshot(subscription),
            "اشتراك افتراضي",
        )
        return subscription

    async def assign_plan(
        self,
        session: AsyncSession,
        provider: Provider,
        plan_code: str,
        actor: User | None,
        *,
        duration_days: int | None = None,
        custom_price_iqd: int | None = None,
        reason: str = "",
        trial: bool = False,
        starts_at: datetime | None = None,
    ) -> ProviderSubscription:
        plan = await self.get_plan(session, plan_code)
        if not plan:
            raise ValueError("الباقة غير موجودة أو متوقفة.")
        subscription = await self.get_subscription(session, provider.id)
        old = self.snapshot(subscription) if subscription else {}
        now = starts_at or self._now()
        days = duration_days if duration_days is not None else plan.billing_days
        ends_at = (
            None
            if plan.code == "free" and not trial and duration_days is None
            else now + timedelta(days=max(1, days))
        )
        grace_days = plan.grace_days if plan.grace_days >= 0 else self.default_grace_days
        grace_until = ends_at + timedelta(days=grace_days) if ends_at else None
        if subscription is None:
            subscription = ProviderSubscription(provider_id=provider.id, plan_id=plan.id)
            session.add(subscription)
        subscription.plan_id = plan.id
        subscription.plan = plan
        subscription.starts_at = now
        subscription.ends_at = ends_at
        subscription.grace_until = grace_until
        subscription.is_trial = trial
        subscription.status = (
            ProviderSubscriptionStatus.TRIAL.value
            if trial
            else ProviderSubscriptionStatus.ACTIVE.value
        )
        subscription.custom_price_iqd = custom_price_iqd
        subscription.note = reason
        subscription.created_by_user_id = actor.id if actor else subscription.created_by_user_id
        subscription.reminder_3d_sent = False
        subscription.reminder_1d_sent = False
        subscription.expiry_notice_sent = False
        provider.report_plan = (
            plan.code if plan.code in {"free", "lite", "pro"} else provider.report_plan
        )
        await session.flush()
        await self._log(
            session,
            provider.id,
            actor,
            "subscription.plan_assigned" if not trial else "subscription.trial_granted",
            old,
            self.snapshot(subscription),
            reason,
        )
        return subscription

    async def grant_trial(
        self,
        session: AsyncSession,
        provider: Provider,
        days: int,
        actor: User | None,
        *,
        plan_code: str = "pro",
        reason: str = "تجربة مجانية",
    ) -> ProviderSubscription:
        if days < 1 or days > 365:
            raise ValueError("مدة التجربة يجب أن تكون بين يوم و365 يومًا.")
        return await self.assign_plan(
            session,
            provider,
            plan_code,
            actor,
            duration_days=days,
            custom_price_iqd=0,
            reason=reason,
            trial=True,
        )

    async def extend(
        self,
        session: AsyncSession,
        provider: Provider,
        days: int,
        actor: User | None,
        reason: str = "تمديد يدوي",
    ) -> ProviderSubscription:
        if days < 1 or days > 1095:
            raise ValueError("التمديد يجب أن يكون بين يوم و3 سنوات.")
        subscription = await self.ensure_subscription(session, provider, actor)
        old = self.snapshot(subscription)
        now = self._now()
        current_end = as_utc(subscription.ends_at)
        base = current_end if current_end and current_end > now else now
        subscription.ends_at = base + timedelta(days=days)
        grace_days = subscription.plan.grace_days if subscription.plan else self.default_grace_days
        subscription.grace_until = subscription.ends_at + timedelta(days=grace_days)
        subscription.status = (
            ProviderSubscriptionStatus.TRIAL.value
            if subscription.is_trial
            else ProviderSubscriptionStatus.ACTIVE.value
        )
        subscription.reminder_3d_sent = False
        subscription.reminder_1d_sent = False
        subscription.expiry_notice_sent = False
        await session.flush()
        await self._log(
            session,
            provider.id,
            actor,
            "subscription.extended",
            old,
            self.snapshot(subscription),
            reason,
        )
        return subscription

    async def set_paused(
        self,
        session: AsyncSession,
        provider: Provider,
        paused: bool,
        actor: User | None,
        reason: str = "",
    ) -> ProviderSubscription:
        subscription = await self.ensure_subscription(session, provider, actor)
        old = self.snapshot(subscription)
        subscription.status = (
            ProviderSubscriptionStatus.PAUSED.value
            if paused
            else (
                ProviderSubscriptionStatus.TRIAL.value
                if subscription.is_trial
                else ProviderSubscriptionStatus.ACTIVE.value
            )
        )
        await session.flush()
        await self._log(
            session,
            provider.id,
            actor,
            "subscription.paused" if paused else "subscription.resumed",
            old,
            self.snapshot(subscription),
            reason,
        )
        return subscription

    async def effective_entitlement(
        self,
        session: AsyncSession,
        provider_id: int,
        feature_key: str,
        now: datetime | None = None,
    ) -> EntitlementResult:
        now = now or self._now()
        subscription = await self.get_subscription(session, provider_id)
        if subscription is None:
            provider = await session.get(Provider, provider_id)
            if not provider:
                return EntitlementResult(False, None, "provider_missing", "missing")
            subscription = await self.ensure_subscription(session, provider)

        status = self._refresh_status(subscription, now)
        override = await session.scalar(
            select(ProviderFeatureOverride)
            .where(
                ProviderFeatureOverride.provider_id == provider_id,
                ProviderFeatureOverride.feature_key == feature_key,
                ProviderFeatureOverride.valid_from <= now,
                or_(
                    ProviderFeatureOverride.valid_until.is_(None),
                    ProviderFeatureOverride.valid_until >= now,
                ),
            )
            .order_by(ProviderFeatureOverride.created_at.desc())
            .limit(1)
        )
        if override and override.enabled_override is not None:
            return EntitlementResult(
                override.enabled_override,
                override.limit_override,
                "override",
                status,
            )

        if status in {
            ProviderSubscriptionStatus.EXPIRED.value,
            ProviderSubscriptionStatus.CANCELLED.value,
            ProviderSubscriptionStatus.PAUSED.value,
        }:
            return EntitlementResult(
                feature_key in ESSENTIAL_FEATURES,
                override.limit_override if override else None,
                "expired_essential"
                if feature_key in ESSENTIAL_FEATURES
                else "subscription_inactive",
                status,
            )

        plan_feature = next(
            (item for item in subscription.plan.features if item.feature_key == feature_key),
            None,
        )
        enabled = bool(plan_feature and plan_feature.is_enabled)
        limit = plan_feature.limit_value if plan_feature else None
        if override and override.limit_override is not None:
            limit = override.limit_override
        return EntitlementResult(enabled, limit, "plan", status)

    async def feature_enabled(
        self, session: AsyncSession, provider_id: int, feature_key: str
    ) -> bool:
        return (await self.effective_entitlement(session, provider_id, feature_key)).enabled

    async def feature_limit(
        self, session: AsyncSession, provider_id: int, limit_key: str
    ) -> int | None:
        return (await self.effective_entitlement(session, provider_id, limit_key)).limit

    async def assert_within_limit(
        self,
        session: AsyncSession,
        provider_id: int,
        limit_key: str,
        current_count: int,
    ) -> None:
        result = await self.effective_entitlement(session, provider_id, limit_key)
        limit_value = result.limit
        if not result.enabled:
            raise ValueError("هذه الخاصية غير متاحة في باقة المنصة الحالية.")
        if limit_value is not None and limit_value >= 0 and current_count >= limit_value:
            label = LIMIT_LABELS.get(limit_key, limit_key)
            raise ValueError(f"تم الوصول إلى الحد المسموح: {label} = {limit_value}")

    async def set_feature_override(
        self,
        session: AsyncSession,
        provider: Provider,
        feature_key: str,
        enabled: bool | None,
        actor: User | None,
        *,
        days: int | None = None,
        reason: str = "",
    ) -> ProviderFeatureOverride | None:
        if feature_key not in FEATURE_LABELS:
            raise ValueError("الميزة غير معروفة.")
        now = self._now()
        if enabled is None:
            active = list(
                (
                    await session.scalars(
                        select(ProviderFeatureOverride).where(
                            ProviderFeatureOverride.provider_id == provider.id,
                            ProviderFeatureOverride.feature_key == feature_key,
                            or_(
                                ProviderFeatureOverride.valid_until.is_(None),
                                ProviderFeatureOverride.valid_until >= now,
                            ),
                        )
                    )
                ).all()
            )
            for item in active:
                item.valid_until = now - timedelta(seconds=1)
            await self._log(
                session,
                provider.id,
                actor,
                "subscription.feature_inherit",
                {},
                {"feature": feature_key},
                reason,
            )
            return None
        valid_until = now + timedelta(days=days) if days else None
        override = ProviderFeatureOverride(
            provider_id=provider.id,
            feature_key=feature_key,
            enabled_override=enabled,
            valid_from=now,
            valid_until=valid_until,
            reason=reason,
            created_by_user_id=actor.id if actor else None,
        )
        session.add(override)
        await session.flush()
        await self._log(
            session,
            provider.id,
            actor,
            "subscription.feature_override",
            {},
            {"feature": feature_key, "enabled": enabled, "days": days},
            reason,
        )
        return override

    async def set_limit_override(
        self,
        session: AsyncSession,
        provider: Provider,
        limit_key: str,
        limit_value: int | None,
        actor: User | None,
        *,
        days: int | None = None,
        reason: str = "",
    ) -> ProviderFeatureOverride | None:
        if limit_key not in LIMIT_LABELS:
            raise ValueError("الحد غير معروف.")
        now = self._now()
        if limit_value is None:
            active = list(
                (
                    await session.scalars(
                        select(ProviderFeatureOverride).where(
                            ProviderFeatureOverride.provider_id == provider.id,
                            ProviderFeatureOverride.feature_key == limit_key,
                            or_(
                                ProviderFeatureOverride.valid_until.is_(None),
                                ProviderFeatureOverride.valid_until >= now,
                            ),
                        )
                    )
                ).all()
            )
            for item in active:
                item.valid_until = now - timedelta(seconds=1)
            return None
        valid_until = now + timedelta(days=days) if days else None
        override = ProviderFeatureOverride(
            provider_id=provider.id,
            feature_key=limit_key,
            enabled_override=True,
            limit_override=limit_value,
            valid_from=now,
            valid_until=valid_until,
            reason=reason,
            created_by_user_id=actor.id if actor else None,
        )
        session.add(override)
        await session.flush()
        await self._log(
            session,
            provider.id,
            actor,
            "subscription.limit_override",
            {},
            {"limit": limit_key, "value": limit_value, "days": days},
            reason,
        )
        return override

    async def set_commission_override(
        self,
        session: AsyncSession,
        provider: Provider,
        percent: int,
        days: int,
        actor: User | None,
        reason: str = "إعفاء أو تعديل مؤقت",
    ) -> ProviderCommissionOverride:
        if not 0 <= percent <= 100:
            raise ValueError("النسبة يجب أن تكون بين 0 و100.")
        if not 1 <= days <= 1095:
            raise ValueError("المدة يجب أن تكون بين يوم و3 سنوات.")
        now = self._now()
        override = ProviderCommissionOverride(
            provider_id=provider.id,
            management_percent=percent,
            valid_from=now,
            valid_until=now + timedelta(days=days),
            reason=reason,
            created_by_user_id=actor.id if actor else None,
        )
        session.add(override)
        await session.flush()
        await self._log(
            session,
            provider.id,
            actor,
            "subscription.commission_override",
            {"default_percent": provider.management_percent},
            {"percent": percent, "days": days},
            reason,
        )
        return override

    async def effective_management_percent(self, session: AsyncSession, provider: Provider) -> int:
        now = self._now()
        override = await session.scalar(
            select(ProviderCommissionOverride)
            .where(
                ProviderCommissionOverride.provider_id == provider.id,
                ProviderCommissionOverride.valid_from <= now,
                ProviderCommissionOverride.valid_until >= now,
            )
            .order_by(ProviderCommissionOverride.created_at.desc())
            .limit(1)
        )
        return override.management_percent if override else provider.management_percent

    async def redeem_coupon(
        self,
        session: AsyncSession,
        provider: Provider,
        code: str,
        actor: User | None,
    ) -> str:
        now = self._now()
        normalized = code.strip().upper()
        coupon = await session.scalar(
            select(ProviderCoupon).where(ProviderCoupon.code == normalized)
        )
        if not coupon or not coupon.is_active:
            raise ValueError("الكوبون غير موجود أو متوقف.")
        if coupon.provider_id and coupon.provider_id != provider.id:
            raise ValueError("هذا الكوبون مخصص لمنصة أخرى.")
        valid_from = as_utc(coupon.valid_from)
        valid_until = as_utc(coupon.valid_until)
        if (valid_from and valid_from > now) or (valid_until and valid_until < now):
            raise ValueError("الكوبون غير صالح في الوقت الحالي.")
        if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
            raise ValueError("اكتمل عدد استخدامات الكوبون.")
        used = await session.scalar(
            select(ProviderCouponRedemption.id).where(
                ProviderCouponRedemption.coupon_id == coupon.id,
                ProviderCouponRedemption.provider_id == provider.id,
            )
        )
        if used:
            raise ValueError("تم استخدام هذا الكوبون لهذه المنصة سابقًا.")

        message: str
        if coupon.kind == CouponKind.TRIAL.value:
            plan = await session.get(SubscriptionPlan, coupon.plan_id) if coupon.plan_id else None
            await self.grant_trial(
                session,
                provider,
                coupon.value_int or 7,
                actor,
                plan_code=plan.code if plan else "pro",
                reason=f"كوبون {coupon.code}",
            )
            message = f"تم تفعيل تجربة مجانية لمدة {coupon.value_int or 7} أيام."
        elif coupon.kind == CouponKind.PLAN.value:
            plan = await session.get(SubscriptionPlan, coupon.plan_id) if coupon.plan_id else None
            if not plan:
                raise ValueError("الباقة المرتبطة بالكوبون غير متوفرة.")
            await self.assign_plan(
                session,
                provider,
                plan.code,
                actor,
                duration_days=coupon.value_int or plan.billing_days,
                custom_price_iqd=0,
                reason=f"كوبون {coupon.code}",
            )
            message = f"تم تفعيل باقة {plan.name_ar}."
        elif coupon.kind == CouponKind.FEATURE.value:
            if not coupon.feature_key:
                raise ValueError("ميزة الكوبون غير محددة.")
            await self.set_feature_override(
                session,
                provider,
                coupon.feature_key,
                True,
                actor,
                days=coupon.feature_days or coupon.value_int or 7,
                reason=f"كوبون {coupon.code}",
            )
            message = "تم فتح الميزة بنجاح."
        elif coupon.kind in {
            CouponKind.PERCENT_DISCOUNT.value,
            CouponKind.FIXED_DISCOUNT.value,
        }:
            subscription = await self.ensure_subscription(session, provider, actor)
            base_price = (
                subscription.custom_price_iqd
                if subscription.custom_price_iqd is not None
                else subscription.plan.price_iqd
            )
            if coupon.kind == CouponKind.PERCENT_DISCOUNT.value:
                if not 1 <= coupon.value_int <= 100:
                    raise ValueError("نسبة الخصم في الكوبون غير صحيحة.")
                new_price = max(0, round(base_price * (100 - coupon.value_int) / 100))
                message = f"تم تطبيق خصم {coupon.value_int}%، والسعر المسجل أصبح {new_price:,} د.ع."
            else:
                new_price = max(0, base_price - coupon.value_int)
                message = (
                    f"تم تطبيق خصم {coupon.value_int:,} د.ع، والسعر المسجل أصبح {new_price:,} د.ع."
                )
            await self.set_custom_price(
                session,
                provider,
                new_price,
                actor,
                reason=f"كوبون {coupon.code}",
            )
        else:
            raise ValueError("نوع الكوبون غير مدعوم.")

        session.add(
            ProviderCouponRedemption(
                coupon_id=coupon.id,
                provider_id=provider.id,
                redeemed_by_user_id=actor.id if actor else None,
            )
        )
        coupon.used_count += 1
        await self._log(
            session,
            provider.id,
            actor,
            "subscription.coupon_redeemed",
            {},
            {"code": coupon.code, "kind": coupon.kind},
            message,
        )
        await session.flush()
        return message

    async def sync_lifecycle(self, session: AsyncSession) -> list[ProviderSubscription]:
        subscriptions = list(
            (
                await session.scalars(
                    select(ProviderSubscription).options(selectinload(ProviderSubscription.plan))
                )
            ).all()
        )
        changed: list[ProviderSubscription] = []
        for subscription in subscriptions:
            old = subscription.status
            self._refresh_status(subscription)
            if subscription.status != old:
                changed.append(subscription)
                session.add(
                    SubscriptionChangeLog(
                        provider_id=subscription.provider_id,
                        action="subscription.lifecycle",
                        old_data={"status": old},
                        new_data={"status": subscription.status},
                        reason="تحديث تلقائي لحالة الاشتراك",
                    )
                )
        await session.flush()
        return changed

    @staticmethod
    def snapshot(subscription: ProviderSubscription | None) -> dict:
        if subscription is None:
            return {}
        return {
            "plan_id": subscription.plan_id,
            "plan_code": subscription.plan.code if subscription.plan else None,
            "status": subscription.status,
            "starts_at": subscription.starts_at.isoformat() if subscription.starts_at else None,
            "ends_at": subscription.ends_at.isoformat() if subscription.ends_at else None,
            "grace_until": subscription.grace_until.isoformat()
            if subscription.grace_until
            else None,
            "is_trial": subscription.is_trial,
            "custom_price_iqd": subscription.custom_price_iqd,
        }

    async def _log(
        self,
        session: AsyncSession,
        provider_id: int,
        actor: User | None,
        action: str,
        old_data: dict,
        new_data: dict,
        reason: str,
    ) -> None:
        session.add(
            SubscriptionChangeLog(
                provider_id=provider_id,
                actor_user_id=actor.id if actor else None,
                action=action,
                old_data=old_data,
                new_data=new_data,
                reason=reason,
            )
        )
        await session.flush()
