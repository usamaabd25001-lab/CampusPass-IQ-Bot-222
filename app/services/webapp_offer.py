from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import (
    ActivationMode,
    CatalogSection,
    CatalogServiceItem,
    Category,
    DeliveryType,
    Offer,
    OfferCatalogPlacement,
    OfferStatus,
    OfferValidityPolicy,
    SubscriptionStartTrigger,
    ValidityType,
)
from app.services.activation_guides import ActivationGuideService
from app.services.catalog import CatalogService
from app.services.offer_lifecycle import OfferLifecycleService
from app.services.pricing import PriceService
from app.services.provider_operations import ProviderOperationsService
from app.services.warranties import WarrantyService
from app.services.webapp_validation import (
    normalize_text,
    parse_iqd_amount,
    validate_catalog_label,
    validate_offer_description,
    validate_offer_title,
    validate_optional_human_text,
    validate_required_human_text,
    validate_terms,
)
from app.services.workflows import WorkflowService


@dataclass(frozen=True, slots=True)
class OfferCreatePayload:
    section_id: int
    service_id: int
    variant_name: str = ""
    title: str = ""
    description: str = ""
    regular_price_iqd: int | str = 0
    promotion_price_iqd: int | str | None = None
    promotion_end: str | None = None
    fulfillment_kind: str = "manual"
    account_type: str = "not_applicable"
    shared_capacity: int | None = None
    unlimited_capacity: bool = False
    email_provider: str = ""
    student_email_required: bool = False
    student_code_relay_enabled: bool = False
    temporary_access_minutes: int | None = None
    logout_proof_required: bool = False
    validity_type: str = ValidityType.MONTHS_FROM_ACTIVATION.value
    validity_value: int | None = 1
    fixed_end: str | None = None
    start_trigger: str = SubscriptionStartTrigger.USER_ACTIVATED.value
    daily_limit: int | None = None
    warranty_enabled: bool | None = None
    warranty_sla_minutes: int = 60
    terms: str = ""
    guide_text: str = ""


class WebAppOfferService:
    """Provider offer builder used by the Telegram Mini App.

    The browser sends business intent (for example ``ready_account``) rather than
    internal delivery enums. This service maps that intent to the existing
    commerce engine, validates every branch again, then writes the offer,
    fulfillment profile, warranty and activation guide in one transaction.
    """

    FULFILLMENT_MAP: dict[str, tuple[str, str]] = {
        "ready_account": (
            DeliveryType.INVENTORY_ACCOUNT.value,
            ActivationMode.EMAIL_PASSWORD.value,
        ),
        "activation_code": (
            DeliveryType.INVENTORY_CODE.value,
            ActivationMode.ACTIVATION_CODE.value,
        ),
        "student_account": (
            DeliveryType.STUDENT_EMAIL_INVITE.value,
            ActivationMode.MANUAL.value,
        ),
        "invite_link": (
            DeliveryType.MANUAL.value,
            ActivationMode.CUSTOM_DATA.value,
        ),
        "otp_account": (
            DeliveryType.EMAIL_CODE.value,
            ActivationMode.EMAIL_PASSWORD_CODE.value,
        ),
        "manual": (DeliveryType.MANUAL.value, ActivationMode.MANUAL.value),
        "custom": (DeliveryType.MANUAL.value, ActivationMode.CUSTOM_DATA.value),
    }
    ACCOUNT_FULFILLMENT_KINDS = {"ready_account", "otp_account"}
    INVENTORY_FULFILLMENT_KINDS = {"ready_account", "activation_code"}
    EMAIL_PROVIDERS = {"google", "microsoft", "yahoo", "other", ""}

    def __init__(
        self,
        *,
        settings: Settings,
        catalog: CatalogService,
        pricing: PriceService,
        workflows: WorkflowService,
        offer_lifecycle: OfferLifecycleService,
        provider_operations: ProviderOperationsService,
        warranties: WarrantyService,
        activation_guides: ActivationGuideService,
    ) -> None:
        self.settings = settings
        self.catalog = catalog
        self.pricing = pricing
        self.workflows = workflows
        self.offer_lifecycle = offer_lifecycle
        self.provider_operations = provider_operations
        self.warranties = warranties
        self.activation_guides = activation_guides

    async def bootstrap(self, session: AsyncSession, provider) -> dict:
        sections = await self.catalog.create_default_provider_catalog(session, provider)
        services = list(
            (
                await session.scalars(
                    select(CatalogServiceItem)
                    .where(CatalogServiceItem.provider_id == provider.id)
                    .order_by(
                        CatalogServiceItem.section_id,
                        CatalogServiceItem.sort_order,
                        CatalogServiceItem.id,
                    )
                )
            ).all()
        )
        return {
            "provider": {
                "id": provider.id,
                "name": provider.name_ar or provider.name_en or f"منصة #{provider.id}",
            },
            "sections": [
                {
                    "id": row.id,
                    "name": row.name,
                    "emoji": row.emoji,
                    "is_active": bool(row.is_active),
                }
                for row in sections
            ],
            "services": [
                {
                    "id": row.id,
                    "section_id": row.section_id,
                    "name": row.name,
                    "emoji": row.emoji,
                    "is_active": bool(row.is_active),
                }
                for row in services
            ],
            "default_service_fee_iqd": int(
                getattr(provider, "default_service_fee_iqd", 0) or 0
            ),
            "duration_presets": [
                {"label": "شهر", "validity_type": "months_from_activation", "value": 1},
                {"label": "3 أشهر", "validity_type": "months_from_activation", "value": 3},
                {"label": "6 أشهر", "validity_type": "months_from_activation", "value": 6},
                {"label": "سنة", "validity_type": "months_from_activation", "value": 12},
            ],
        }

    async def add_section(self, session: AsyncSession, provider_id: int, name: str) -> dict:
        from app.core.emoji import smart_emoji

        clean = validate_catalog_label(name, label="اسم القسم")
        duplicate = await session.scalar(
            select(CatalogSection).where(
                CatalogSection.provider_id == provider_id,
                func.lower(CatalogSection.name) == clean.lower(),
            )
        )
        if duplicate:
            if not duplicate.is_active:
                duplicate.is_active = True
                duplicate.name = clean
                await session.flush()
                return {
                    "id": duplicate.id,
                    "name": duplicate.name,
                    "emoji": duplicate.emoji,
                    "is_active": True,
                }
            raise ValueError("هذا القسم موجود مسبقًا")
        row = CatalogSection(
            provider_id=provider_id,
            name=clean,
            emoji=smart_emoji(clean),
            is_active=True,
        )
        session.add(row)
        await session.flush()
        return {"id": row.id, "name": row.name, "emoji": row.emoji, "is_active": True}

    async def rename_section(
        self, session: AsyncSession, provider_id: int, section_id: int, name: str
    ) -> dict:
        clean = validate_catalog_label(name, label="اسم القسم")
        row = await session.get(CatalogSection, int(section_id))
        if row is None or row.provider_id != provider_id:
            raise ValueError("القسم غير موجود")
        duplicate = await session.scalar(
            select(CatalogSection.id).where(
                CatalogSection.provider_id == provider_id,
                func.lower(CatalogSection.name) == clean.lower(),
                CatalogSection.id != row.id,
            )
        )
        if duplicate:
            raise ValueError("يوجد قسم آخر بهذا الاسم")
        row.name = clean
        await session.flush()
        return {
            "id": row.id,
            "name": row.name,
            "emoji": row.emoji,
            "is_active": bool(row.is_active),
        }

    async def set_section_active(
        self, session: AsyncSession, provider_id: int, section_id: int, active: bool
    ) -> dict:
        row = await session.get(CatalogSection, int(section_id))
        if row is None or row.provider_id != provider_id:
            raise ValueError("القسم غير موجود")
        row.is_active = bool(active)
        await session.flush()
        return {"id": row.id, "is_active": bool(row.is_active)}

    async def add_service(
        self, session: AsyncSession, provider_id: int, section_id: int, name: str
    ) -> dict:
        from app.core.emoji import smart_emoji

        section = await session.get(CatalogSection, int(section_id))
        if section is None or section.provider_id != provider_id:
            raise ValueError("القسم غير موجود")
        clean = validate_catalog_label(name, label="اسم الخدمة")
        duplicate = await session.scalar(
            select(CatalogServiceItem).where(
                CatalogServiceItem.section_id == section.id,
                func.lower(CatalogServiceItem.name) == clean.lower(),
            )
        )
        if duplicate:
            if not duplicate.is_active:
                duplicate.is_active = True
                duplicate.name = clean
                await session.flush()
                return {
                    "id": duplicate.id,
                    "section_id": duplicate.section_id,
                    "name": duplicate.name,
                    "emoji": duplicate.emoji,
                    "is_active": True,
                }
            raise ValueError("هذه الخدمة موجودة داخل القسم مسبقًا")
        row = CatalogServiceItem(
            provider_id=provider_id,
            section_id=section.id,
            name=clean,
            emoji=smart_emoji(clean),
            is_active=True,
        )
        session.add(row)
        await session.flush()
        return {
            "id": row.id,
            "section_id": row.section_id,
            "name": row.name,
            "emoji": row.emoji,
            "is_active": True,
        }

    async def rename_service(
        self, session: AsyncSession, provider_id: int, service_id: int, name: str
    ) -> dict:
        clean = validate_catalog_label(name, label="اسم الخدمة")
        row = await session.get(CatalogServiceItem, int(service_id))
        if row is None or row.provider_id != provider_id:
            raise ValueError("الخدمة غير موجودة")
        duplicate = await session.scalar(
            select(CatalogServiceItem.id).where(
                CatalogServiceItem.section_id == row.section_id,
                func.lower(CatalogServiceItem.name) == clean.lower(),
                CatalogServiceItem.id != row.id,
            )
        )
        if duplicate:
            raise ValueError("توجد خدمة أخرى بهذا الاسم")
        row.name = clean
        await session.flush()
        return {
            "id": row.id,
            "section_id": row.section_id,
            "name": row.name,
            "emoji": row.emoji,
            "is_active": bool(row.is_active),
        }

    async def set_service_active(
        self, session: AsyncSession, provider_id: int, service_id: int, active: bool
    ) -> dict:
        row = await session.get(CatalogServiceItem, int(service_id))
        if row is None or row.provider_id != provider_id:
            raise ValueError("الخدمة غير موجودة")
        row.is_active = bool(active)
        await session.flush()
        return {"id": row.id, "is_active": bool(row.is_active)}

    def _parse_baghdad_datetime(
        self, raw: str | None, *, end_of_day: bool = False
    ) -> datetime | None:
        text = (raw or "").strip()
        if not text:
            return None
        parsed: datetime | None = None
        for pattern in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, pattern)
                if pattern == "%Y-%m-%d" and end_of_day:
                    parsed = parsed.replace(hour=23, minute=59, second=59)
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError("صيغة التاريخ أو الوقت غير صحيحة")
        return parsed.replace(tzinfo=ZoneInfo(self.settings.timezone)).astimezone(UTC)

    @staticmethod
    def _duration_label(validity_type: str, validity_value: int | None, fixed_end: str | None) -> str:
        if validity_type == ValidityType.MONTHS_FROM_ACTIVATION.value and validity_value:
            if int(validity_value) == 1:
                return "شهر"
            if int(validity_value) == 12:
                return "سنة"
            return f"{int(validity_value)} أشهر"
        if validity_type == ValidityType.DAYS_FROM_ACTIVATION.value and validity_value:
            return f"{int(validity_value)} يوم"
        if validity_type == ValidityType.FIXED_OFFER_END.value and fixed_end:
            return f"حتى {fixed_end[:10]}"
        if validity_type == ValidityType.INVENTORY_END.value:
            return "حسب الحساب"
        return "مدة مخصصة"

    @staticmethod
    def _guide_steps(text: str) -> list[dict]:
        lines = [normalize_text(line) for line in (text or "").splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            raise ValueError("اكتب خطوة واحدة على الأقل لطريقة التسجيل أو التفعيل")
        if len(lines) > 20:
            raise ValueError("تعليمات التفعيل تقبل 20 خطوة نصية كحد أقصى")
        return [{"kind": "text", "text": line[:4000]} for line in lines]

    async def create_draft(
        self,
        session: AsyncSession,
        *,
        staff,
        payload: OfferCreatePayload,
    ) -> dict:
        provider_id = int(staff.provider_id)
        section = await session.get(CatalogSection, int(payload.section_id))
        service_item = await session.get(CatalogServiceItem, int(payload.service_id))
        if (
            section is None
            or service_item is None
            or section.provider_id != provider_id
            or service_item.provider_id != provider_id
            or service_item.section_id != section.id
            or not section.is_active
            or not service_item.is_active
        ):
            raise ValueError("القسم أو الخدمة غير متاحة لمنصتك")

        variant_name = validate_optional_human_text(
            payload.variant_name,
            label="فئة الخدمة",
            max_length=100,
        )
        description = validate_offer_description(payload.description)
        terms = validate_terms(payload.terms)
        guide_text = validate_required_human_text(
            payload.guide_text,
            label="تعليمات التسجيل والتفعيل",
            min_length=3,
            max_length=8000,
            min_letters=2,
        )
        guide_steps = self._guide_steps(guide_text)

        regular_result = await self.pricing.validate_offer_price(
            session, str(parse_iqd_amount(payload.regular_price_iqd))
        )
        regular_price = int(regular_result.value)
        if regular_result.suspiciously_low:
            raise ValueError(
                "السعر منخفض بصورة غير معتادة. استخدم تأكيد السعر الذكي في الواجهة قبل الحفظ"
            )

        original_price: int | None = None
        price = regular_price
        start_at: datetime | None = None
        end_at: datetime | None = None
        if payload.promotion_price_iqd not in {None, ""}:
            promo_amount = parse_iqd_amount(payload.promotion_price_iqd)
            promo_result = await self.pricing.validate_offer_price(session, str(promo_amount))
            if promo_result.value >= regular_price:
                raise ValueError("سعر العرض المؤقت يجب أن يكون أقل من السعر الطبيعي")
            end_at = self._parse_baghdad_datetime(payload.promotion_end, end_of_day=True)
            if end_at is None or end_at <= datetime.now(UTC):
                raise ValueError("وقت انتهاء العرض المؤقت يجب أن يكون في المستقبل")
            original_price = regular_price
            price = int(promo_result.value)
            start_at = datetime.now(UTC)
        elif payload.promotion_end:
            raise ValueError("لا تضع تاريخ انتهاء إذا لم يكن العرض مؤقتًا")

        fulfillment_kind = str(payload.fulfillment_kind or "").strip()
        mapping = self.FULFILLMENT_MAP.get(fulfillment_kind)
        if mapping is None:
            raise ValueError("طريقة الحصول على الخدمة غير معتمدة")
        delivery_type, activation_mode = mapping

        validity_type = str(payload.validity_type or "")
        if validity_type not in {mode.value for mode in ValidityType}:
            raise ValueError("نوع الصلاحية غير معتمد")
        validity_value = payload.validity_value
        fixed_end = None
        if validity_type == ValidityType.DAYS_FROM_ACTIVATION.value:
            if validity_value is None or not 1 <= int(validity_value) <= 1095:
                raise ValueError("عدد الأيام يجب أن يكون بين 1 و1095")
        elif validity_type == ValidityType.MONTHS_FROM_ACTIVATION.value:
            if validity_value is None or not 1 <= int(validity_value) <= 36:
                raise ValueError("عدد الأشهر يجب أن يكون بين 1 و36")
        elif validity_type == ValidityType.FIXED_OFFER_END.value:
            fixed_end = self._parse_baghdad_datetime(payload.fixed_end, end_of_day=True)
            if fixed_end is None or fixed_end <= datetime.now(UTC):
                raise ValueError("تاريخ نهاية الصلاحية يجب أن يكون في المستقبل")
            validity_value = None
        else:
            validity_value = None

        start_trigger = str(payload.start_trigger or "")
        if start_trigger not in {trigger.value for trigger in SubscriptionStartTrigger}:
            raise ValueError("وقت بدء الاشتراك غير معتمد")

        daily_limit = payload.daily_limit
        if daily_limit is not None and not 1 <= int(daily_limit) <= 100000:
            raise ValueError("الحد اليومي يجب أن يكون بين 1 و100000 أو غير محدود")
        if payload.warranty_enabled is None:
            raise ValueError("حدد بوضوح هل العرض يشمل ضمانًا أم لا")

        account_type = str(payload.account_type or "not_applicable")
        account_based = fulfillment_kind in self.ACCOUNT_FULFILLMENT_KINDS
        if account_based:
            if account_type not in {"private", "shared", "friends_only"}:
                raise ValueError("حدد هل الحساب خاص أو مشترك")
        else:
            account_type = "not_applicable"

        capacity: int | None = None
        unlimited_capacity = False
        if account_type == "private":
            capacity = 1
        elif account_type in {"shared", "friends_only"}:
            unlimited_capacity = bool(payload.unlimited_capacity)
            if not unlimited_capacity:
                if payload.shared_capacity is None or not 2 <= int(payload.shared_capacity) <= 10000:
                    raise ValueError("عدد مستخدمي الحساب المشترك يجب أن يكون بين 2 و10000")
                capacity = int(payload.shared_capacity)

        temporary_minutes = payload.temporary_access_minutes
        if temporary_minutes is not None:
            if not account_based:
                raise ValueError("الاستخدام المؤقت بالساعات متاح للحسابات فقط")
            if not 15 <= int(temporary_minutes) <= 43200:
                raise ValueError("مدة الاستخدام المؤقت يجب أن تكون بين 15 و43200 دقيقة")

        email_provider = str(payload.email_provider or "").strip().lower()
        if email_provider not in self.EMAIL_PROVIDERS:
            raise ValueError("مزود البريد غير معتمد")
        if fulfillment_kind == "otp_account" and not email_provider:
            raise ValueError("حدد مزود البريد للحساب الذي يحتاج رمز دخول")

        student_email_required = bool(payload.student_email_required) or fulfillment_kind == "student_account"
        student_code_relay_enabled = bool(payload.student_code_relay_enabled)
        if student_code_relay_enabled and not student_email_required:
            raise ValueError("نقل رمز الطالب يتطلب أولًا التفعيل على إيميل الطالب")

        duration_label = self._duration_label(validity_type, validity_value, payload.fixed_end)
        generated_title = " ".join(
            part
            for part in [
                "اشتراك",
                service_item.name,
                variant_name,
                "—",
                duration_label,
            ]
            if part
        ).replace(" —  ", " — ")
        title = validate_offer_title(payload.title or generated_title)

        category = await session.scalar(select(Category).where(Category.name == section.name))
        if category is None:
            category = await session.scalar(
                select(Category).where(Category.is_active.is_(True)).order_by(Category.sort_order).limit(1)
            )
        if category is None:
            category = Category(name="خدمات رقمية", emoji="🛍")
            session.add(category)
            await session.flush()

        provider = staff.provider
        service_fee_iqd = int(getattr(provider, "default_service_fee_iqd", 0) or 0)
        offer = Offer(
            provider_id=provider_id,
            category_id=category.id,
            title=title,
            description=description,
            original_price_iqd=original_price,
            price_iqd=price,
            service_fee_iqd=service_fee_iqd,
            start_at=start_at,
            end_at=end_at,
            duration_days=(
                int(validity_value)
                if validity_type == ValidityType.DAYS_FROM_ACTIVATION.value and validity_value
                else None
            ),
            delivery_type=delivery_type,
            daily_limit=(int(daily_limit) if daily_limit is not None else None),
            terms=terms,
            status=OfferStatus.DRAFT.value,
            is_active=False,
            max_code_attempts=3,
        )
        session.add(offer)
        await session.flush()
        session.add(
            OfferCatalogPlacement(
                offer_id=offer.id,
                provider_id=provider_id,
                section_id=section.id,
                service_id=service_item.id,
            )
        )
        session.add(
            OfferValidityPolicy(
                offer_id=offer.id,
                validity_type=validity_type,
                duration_value=(int(validity_value) if validity_value is not None else None),
                fixed_end_at=fixed_end,
                start_trigger=start_trigger,
            )
        )
        await self.workflows.ensure_offer(session, offer)

        await self.provider_operations.configure_fulfillment(
            session,
            provider_id=provider_id,
            offer_id=offer.id,
            account_type=account_type,
            activation_mode=activation_mode,
            shared_capacity=capacity,
            unlimited_capacity=unlimited_capacity,
            temporary_access_minutes=(int(temporary_minutes) if temporary_minutes is not None else None),
            logout_proof_required=bool(payload.logout_proof_required or temporary_minutes is not None),
            student_email_required=student_email_required,
            student_code_relay_enabled=student_code_relay_enabled,
            otp_lease_seconds=min(60, int(self.settings.otp_account_lease_seconds)),
            max_otp_attempts=3,
            metadata={
                "fulfillment_kind": fulfillment_kind,
                "email_provider": email_provider,
                "configured_from": "webapp-v4",
                "variant_name": variant_name,
            },
        )
        await self.warranties.configure(
            session,
            provider_id=provider_id,
            offer_id=offer.id,
            enabled=bool(payload.warranty_enabled),
            response_sla_minutes=max(5, min(int(payload.warranty_sla_minutes or 60), 1440)),
        )
        await self.activation_guides.upsert(
            session,
            offer=offer,
            activation_mode=activation_mode,
            title="طريقة التسجيل والتفعيل",
            intro_text="اتبع الخطوات بالترتيب، وإذا واجهتك مشكلة استخدم دعم الطلب.",
            steps=guide_steps,
            actor_user_id=staff.user_id,
            acknowledgement_required=True,
            show_before_delivery=True,
        )

        if fulfillment_kind == "otp_account":
            offer.status = OfferStatus.DRAFT.value
            offer.is_active = False
            next_action = "connect_email"
        elif fulfillment_kind in self.INVENTORY_FULFILLMENT_KINDS:
            offer.status = OfferStatus.OUT_OF_STOCK.value
            offer.is_active = False
            next_action = "add_inventory"
        else:
            offer.status = OfferStatus.ACTIVE.value
            offer.is_active = True
            next_action = "ready"
            await self.offer_lifecycle.queue_launch_announcement(session, offer, staff.user_id)

        await session.flush()
        return {
            "ok": True,
            "offer_id": offer.id,
            "title": offer.title,
            "provider_id": provider_id,
            "delivery_type": delivery_type,
            "activation_mode": activation_mode,
            "fulfillment_kind": fulfillment_kind,
            "status": offer.status,
            "is_active": bool(offer.is_active),
            "service_fee_iqd": service_fee_iqd,
            "next_action": next_action,
            "requires_guide": False,
        }
