from __future__ import annotations

import asyncio

import html
import orjson
import logging
import secrets
from pathlib import Path
from datetime import UTC, datetime

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, ORJSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select, text

from app import AIOGRAM_TARGET, TELEGRAM_BOT_API_TARGET, __version__
from app.core.context import AppContext
from app.core.telegram_webapp import TelegramWebAppAuthError, verify_telegram_init_data
from app.db.models import Offer, OrderStatus, Provider, ReleaseCompatibility, RuntimeConfigGeneration, User
from app.services.platform_access import effective_staff_view, resolve_provider_access
from app.services.webapp_profile import ProfilePayload
from app.services.webapp_provider import ProviderCreatePayload
from app.services.webapp_offer import OfferCreatePayload
from app.services.webapp_validation import (
    normalize_iraqi_phone,
    normalize_staff_identifiers,
    parse_iqd_amount,
    validate_catalog_label,
    validate_governorate,
    validate_offer_description,
    validate_offer_title,
    validate_optional_arabic_platform_name,
    validate_optional_english_name,
    validate_optional_human_text,
    validate_optional_percentage,
    validate_person_full_name,
    validate_required_human_text,
    validate_telegram_id,
    validate_terms,
)

logger = logging.getLogger(__name__)


class StudentProfileUpdate(BaseModel):
    full_name: str = Field(min_length=8, max_length=180)
    phone: str = Field(min_length=10, max_length=20)
    governorate: str = Field(min_length=2, max_length=80)
    university: str = Field(min_length=2, max_length=180)
    college: str = Field(min_length=2, max_length=180)
    department: str = Field(min_length=2, max_length=180)
    stage: str = Field(min_length=1, max_length=80)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        return validate_person_full_name(value)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_iraqi_phone(value)

    @field_validator("governorate")
    @classmethod
    def validate_governorate_field(cls, value: str) -> str:
        return validate_governorate(value)

    @field_validator("university")
    @classmethod
    def validate_university(cls, value: str) -> str:
        return validate_required_human_text(value, label="الجامعة أو المعهد", max_length=180)

    @field_validator("college")
    @classmethod
    def validate_college(cls, value: str) -> str:
        return validate_required_human_text(value, label="الكلية", max_length=180)

    @field_validator("department")
    @classmethod
    def validate_department(cls, value: str) -> str:
        return validate_required_human_text(value, label="القسم أو الاختصاص", max_length=180)

    @field_validator("stage")
    @classmethod
    def validate_stage(cls, value: str) -> str:
        return validate_required_human_text(
            value, label="المرحلة", min_length=1, max_length=80, min_letters=1
        )


class ProviderCreateRequest(BaseModel):
    name_ar: str = Field(default="", max_length=180)
    name_en: str = Field(default="", max_length=180)
    description: str = Field(default="", max_length=2000)
    owner_telegram_id: int | str
    staff_identifiers: list[str] = Field(default_factory=list, max_length=25)
    management_percent: int | str | None = None
    service_fee_iqd: int | str | None = None

    @field_validator("name_ar")
    @classmethod
    def validate_name_ar(cls, value: str) -> str:
        return validate_optional_arabic_platform_name(value)

    @field_validator("name_en")
    @classmethod
    def validate_name_en(cls, value: str) -> str:
        return validate_optional_english_name(value)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return validate_optional_human_text(value, label="وصف المنصة", max_length=2000)

    @field_validator("owner_telegram_id")
    @classmethod
    def validate_owner_id(cls, value: int | str) -> int:
        return validate_telegram_id(value)

    @field_validator("staff_identifiers")
    @classmethod
    def validate_staff(cls, value: list[str]) -> list[str]:
        return normalize_staff_identifiers(value)

    @field_validator("management_percent")
    @classmethod
    def validate_management_percent(cls, value: int | str | None) -> int:
        return validate_optional_percentage(value, default=0)

    @field_validator("service_fee_iqd")
    @classmethod
    def validate_service_fee(cls, value: int | str | None) -> int:
        return parse_iqd_amount(value, optional=True)


class CatalogNameRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_catalog_label(value, label="الاسم")


class OfferCreateRequest(BaseModel):
    provider_id: int = Field(gt=0)
    section_id: int = Field(gt=0)
    service_id: int = Field(gt=0)
    variant_name: str = Field(default="", max_length=100)
    title: str = Field(default="", max_length=220)
    description: str = Field(default="", max_length=4000)
    regular_price_iqd: int | str
    promotion_price_iqd: int | str | None = None
    promotion_end: str | None = Field(default=None, max_length=40)
    fulfillment_kind: str = Field(min_length=3, max_length=40)
    account_type: str = Field(default="not_applicable", max_length=30)
    shared_capacity: int | None = Field(default=None, ge=2, le=10000)
    unlimited_capacity: bool = False
    email_provider: str = Field(default="", max_length=30)
    student_email_required: bool = False
    student_code_relay_enabled: bool = False
    temporary_access_minutes: int | None = Field(default=None, ge=15, le=43200)
    logout_proof_required: bool = False
    validity_type: str = Field(min_length=3, max_length=80)
    validity_value: int | None = Field(default=None, ge=1, le=1095)
    fixed_end: str | None = Field(default=None, max_length=40)
    start_trigger: str = Field(min_length=3, max_length=80)
    daily_limit: int | None = Field(default=None, ge=1, le=100000)
    warranty_enabled: bool | None = None
    warranty_sla_minutes: int = Field(default=60, ge=5, le=1440)
    terms: str = Field(default="", max_length=4000)
    guide_text: str = Field(min_length=3, max_length=8000)

    @field_validator("variant_name")
    @classmethod
    def validate_variant(cls, value: str) -> str:
        return validate_optional_human_text(value, label="فئة الخدمة", max_length=100)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        text = (value or "").strip()
        return validate_offer_title(text) if text else ""

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return validate_offer_description(value)

    @field_validator("regular_price_iqd")
    @classmethod
    def validate_regular_price(cls, value: int | str) -> int:
        return parse_iqd_amount(value)

    @field_validator("promotion_price_iqd")
    @classmethod
    def validate_promo_price(cls, value: int | str | None) -> int | None:
        if value is None or str(value).strip() == "":
            return None
        return parse_iqd_amount(value)

    @field_validator("terms")
    @classmethod
    def validate_terms_field(cls, value: str) -> str:
        return validate_terms(value)

    @model_validator(mode="after")
    def validate_conditional_fields(self):
        if self.promotion_price_iqd is not None:
            if self.promotion_price_iqd >= self.regular_price_iqd:
                raise ValueError("سعر العرض المؤقت يجب أن يكون أقل من السعر الطبيعي")
            if not (self.promotion_end or "").strip():
                raise ValueError("تاريخ انتهاء العرض المؤقت مطلوب")
        elif (self.promotion_end or "").strip():
            raise ValueError("لا يمكن تحديد نهاية عرض مؤقت بدون سعر خصم")
        if self.validity_type in {"days_from_activation", "months_from_activation"} and self.validity_value is None:
            raise ValueError("قيمة مدة الصلاحية مطلوبة")
        if self.validity_type == "fixed_offer_end" and not (self.fixed_end or "").strip():
            raise ValueError("تاريخ نهاية الصلاحية مطلوب")
        if self.account_type in {"shared", "friends_only"} and not self.unlimited_capacity and self.shared_capacity is None:
            raise ValueError("حدد عدد مستخدمي الحساب المشترك أو اختر غير محدود")
        if self.fulfillment_kind == "otp_account" and not self.email_provider:
            raise ValueError("حدد مزود البريد للحساب الذي يحتاج رمز دخول")
        if self.warranty_enabled is None:
            raise ValueError("حدد بوضوح هل العرض يشمل ضمانًا أم لا")
        return self


class OfferCopyRequest(BaseModel):
    provider_id: int = Field(gt=0)
    section_name: str = Field(min_length=2, max_length=160)
    service_name: str = Field(min_length=2, max_length=160)
    variant_name: str = Field(default="", max_length=100)
    title: str = Field(min_length=3, max_length=220)
    price_iqd: int | str
    duration_text: str = Field(min_length=1, max_length=120)
    fulfillment_label: str = Field(default="", max_length=180)
    warranty_enabled: bool = False

    @field_validator("section_name")
    @classmethod
    def validate_section_name(cls, value: str) -> str:
        return validate_catalog_label(value, label="اسم القسم")

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, value: str) -> str:
        return validate_catalog_label(value, label="اسم الخدمة")

    @field_validator("variant_name")
    @classmethod
    def validate_variant(cls, value: str) -> str:
        return validate_optional_human_text(value, label="فئة الخدمة", max_length=100)

    @field_validator("title")
    @classmethod
    def validate_copy_title(cls, value: str) -> str:
        return validate_offer_title(value)

    @field_validator("price_iqd")
    @classmethod
    def validate_price(cls, value: int | str) -> int:
        return parse_iqd_amount(value)

    @field_validator("duration_text")
    @classmethod
    def validate_duration_text(cls, value: str) -> str:
        return validate_required_human_text(
            value, label="مدة العرض", min_length=1, max_length=120, min_letters=1
        )

    @field_validator("fulfillment_label")
    @classmethod
    def validate_fulfillment_label(cls, value: str) -> str:
        return validate_optional_human_text(value, label="طريقة التفعيل", max_length=180)


class ActiveStateRequest(BaseModel):
    active: bool


def build_api(context: AppContext) -> FastAPI:
    app = FastAPI(
        title="CampusPass IQ",
        version=__version__,
        docs_url=None if context.settings.environment == "production" else "/docs",
        redoc_url=None,
        default_response_class=ORJSONResponse,
    )


    def verified_webapp(request: Request):
        init_data = request.headers.get("X-Telegram-Init-Data", "").strip()
        try:
            return verify_telegram_init_data(
                init_data,
                bot_token=context.settings.bot_token,
                max_age_seconds=900,
            )
        except TelegramWebAppAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    async def verified_provider_staff(
        session,
        verified,
        *,
        provider_id: int | None = None,
        permission: str = "can_manage_offers",
    ):
        access = await resolve_provider_access(
            session,
            context.settings,
            verified.user.id,
            provider_id=provider_id,
            permission=permission,
            require_terms=True,
            allow_paused_provider=False,
        )
        if not access.allowed:
            raise HTTPException(status_code=403, detail="لا تملك صلاحية تنفيذ هذه العملية على المنصة")
        staff = await effective_staff_view(session, access)
        if staff is None:
            raise HTTPException(status_code=403, detail="تعذر تحديد المنصة المسموحة لهذا الحساب")
        return staff

    async def assert_offer_webapp_available(session, staff) -> None:
        # A logo improves branding but is not a commerce prerequisite.
        manage = await context.services.subscriptions.effective_entitlement(
            session, staff.provider_id, "offers.manage"
        )
        if not manage.enabled:
            raise HTTPException(
                status_code=403,
                detail="إدارة العروض غير متاحة في باقة المنصة الحالية",
            )
        entitlement = await context.services.subscriptions.effective_entitlement(
            session, staff.provider_id, "offers.max"
        )
        if not entitlement.enabled:
            raise HTTPException(
                status_code=403,
                detail="إنشاء العروض غير متاح في باقة المنصة الحالية",
            )
        if entitlement.limit is not None and entitlement.limit >= 0:
            current_count = int(
                await session.scalar(
                    select(func.count()).select_from(Offer).where(Offer.provider_id == staff.provider_id)
                )
                or 0
            )
            if current_count >= int(entitlement.limit):
                raise HTTPException(
                    status_code=409,
                    detail="وصلت المنصة إلى الحد الأقصى للعروض في باقتها",
                )

    def webapp_template_response(filename: str) -> HTMLResponse:
        template_path = Path(__file__).with_name("templates") / filename
        html_body = template_path.read_text(encoding="utf-8")
        html_body = (
            html_body.replace("__PRIMARY__", context.settings.brand_primary_color)
            .replace("__SECONDARY__", context.settings.brand_secondary_color)
            .replace("__DARK__", context.settings.brand_dark_color)
            .replace("__BOT_NAME__", html.escape(context.settings.bot_name))
        )
        return HTMLResponse(
            html_body,
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self' https://telegram.org 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self'; "
                    "frame-ancestors https://web.telegram.org https://*.telegram.org"
                ),
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            },
        )

    @app.post(context.settings.telegram_webhook_path)
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str = Header(
            default="", alias="X-Telegram-Bot-Api-Secret-Token"
        ),
    ):
        if context.settings.telegram_delivery_mode != "webhook":
            raise HTTPException(404)
        if context.draining:
            # A non-2xx response makes Telegram retry against the replacement
            # Render instance instead of accepting work during graceful drain.
            raise HTTPException(503, "Deployment draining")
        expected = context.settings.telegram_webhook_secret
        if not expected or not secrets.compare_digest(
            x_telegram_bot_api_secret_token.strip(), expected
        ):
            raise HTTPException(403, "Forbidden")
        content_length = request.headers.get("content-length", "").strip()
        if content_length:
            try:
                if int(content_length) > context.settings.telegram_webhook_body_limit_bytes:
                    raise HTTPException(413, "Payload too large")
            except ValueError:
                raise HTTPException(400, "Invalid Content-Length") from None
        body = await request.body()
        if len(body) > context.settings.telegram_webhook_body_limit_bytes:
            raise HTTPException(413, "Payload too large")
        try:
            payload = orjson.loads(body)
        except orjson.JSONDecodeError as exc:
            raise HTTPException(400, "Invalid Telegram update JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("update_id"), int):
            raise HTTPException(422, "Telegram update_id is required")
        try:
            async with context.database.session_factory() as session:
                row, created = await context.services.telegram_updates.enqueue(
                    session,
                    update_id=int(payload["update_id"]),
                    payload=payload,
                    release_id=context.settings.release_id,
                    max_attempts=context.settings.telegram_update_max_attempts,
                )
                await session.commit()
            context.update_wakeup.set()
        except ValueError as exc:
            logger.error("Rejected Telegram update collision update_id=%s", payload.get("update_id"))
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            logger.exception("Telegram update could not be durably accepted")
            raise HTTPException(503, "Update inbox unavailable") from exc
        return ORJSONResponse(
            {"ok": True, "accepted": created, "duplicate": not created, "update_id": row.update_id},
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/webapp/student/profile", response_class=HTMLResponse)
    async def student_profile_webapp():
        return webapp_template_response("student_profile.html")

    @app.get("/api/webapp/student/profile")
    async def get_student_profile(request: Request):
        verified = verified_webapp(request)
        async with context.database.session_factory() as session:
            result = await context.services.webapp_profile.read(session, verified)
            await session.commit()
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.put("/api/webapp/student/profile")
    async def put_student_profile(request: Request, payload: StudentProfileUpdate):
        verified = verified_webapp(request)
        try:
            async with context.database.session_factory() as session:
                result = await context.services.webapp_profile.save(
                    session,
                    verified,
                    ProfilePayload(**payload.model_dump()),
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            await context.bot.send_message(
                verified.user.id,
                "✅ تم حفظ معلومات حسابك وتدقيقها بنجاح.",
            )
        except Exception:
            logger.warning("Could not deliver profile WebApp confirmation", exc_info=True)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.get("/webapp/admin/provider", response_class=HTMLResponse)
    async def admin_provider_webapp():
        return webapp_template_response("admin_provider.html")

    @app.post("/api/webapp/admin/provider")
    async def create_provider_webapp(request: Request, payload: ProviderCreateRequest):
        verified = verified_webapp(request)
        if not context.settings.is_admin(verified.user.id):
            raise HTTPException(status_code=403, detail="هذه الواجهة مخصصة لمالك البوت فقط")
        try:
            async with context.database.session_factory() as session:
                result = await context.services.webapp_provider.create(
                    session,
                    verified,
                    ProviderCreatePayload(**payload.model_dump()),
                )
                await session.commit()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await context.services.webapp_provider.notify_created(
            admin_telegram_id=verified.user.id,
            result=result,
        )
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.post("/api/webapp/admin/provider/{provider_id}/logo")
    async def upload_provider_logo_webapp(
        request: Request, provider_id: int, file: UploadFile = File(...)
    ):
        verified = verified_webapp(request)
        if not context.settings.is_admin(verified.user.id):
            raise HTTPException(status_code=403, detail="هذه الواجهة مخصصة لمالك البوت فقط")
        raw = await file.read(context.services.branding.MAX_LOGO_BYTES + 1)
        if len(raw) > context.services.branding.MAX_LOGO_BYTES:
            raise HTTPException(status_code=413, detail="حجم الشعار يتجاوز 8MB")
        try:
            async with context.database.session_factory() as session:
                provider = await session.get(Provider, int(provider_id))
                if provider is None:
                    raise HTTPException(status_code=404, detail="المنصة غير موجودة")
                candidate = await context.services.branding.save_uploaded_bytes(
                    session,
                    provider,
                    raw,
                    telegram_chat_id=verified.user.id,
                    filename=(file.filename or "provider-logo.png"),
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse(
            {"ok": True, "logo": candidate.public_dict()},
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/webapp/provider/offer", response_class=HTMLResponse)
    async def provider_offer_webapp():
        return webapp_template_response("provider_offer.html")

    @app.get("/api/webapp/provider/offer/bootstrap")
    async def provider_offer_bootstrap(request: Request, provider_id: int):
        verified = verified_webapp(request)
        async with context.database.session_factory() as session:
            staff = await verified_provider_staff(
                session, verified, provider_id=provider_id, permission="can_manage_offers"
            )
            await assert_offer_webapp_available(session, staff)
            result = await context.services.webapp_offer.bootstrap(session, staff.provider)
            await session.commit()
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.post("/api/webapp/provider/catalog/sections")
    async def provider_add_section_webapp(
        request: Request, provider_id: int, payload: CatalogNameRequest
    ):
        verified = verified_webapp(request)
        try:
            async with context.database.session_factory() as session:
                staff = await verified_provider_staff(
                    session, verified, provider_id=provider_id, permission="can_manage_offers"
                )
                result = await context.services.webapp_offer.add_section(
                    session, staff.provider_id, payload.name
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "section": result}, headers={"Cache-Control": "no-store"})

    @app.patch("/api/webapp/provider/catalog/sections/{section_id}")
    async def provider_rename_section_webapp(
        request: Request, provider_id: int, section_id: int, payload: CatalogNameRequest
    ):
        verified = verified_webapp(request)
        try:
            async with context.database.session_factory() as session:
                staff = await verified_provider_staff(
                    session, verified, provider_id=provider_id, permission="can_manage_offers"
                )
                result = await context.services.webapp_offer.rename_section(
                    session, staff.provider_id, section_id, payload.name
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "section": result}, headers={"Cache-Control": "no-store"})

    @app.patch("/api/webapp/provider/catalog/sections/{section_id}/status")
    async def provider_section_status_webapp(
        request: Request, provider_id: int, section_id: int, payload: ActiveStateRequest
    ):
        verified = verified_webapp(request)
        try:
            async with context.database.session_factory() as session:
                staff = await verified_provider_staff(
                    session, verified, provider_id=provider_id, permission="can_manage_offers"
                )
                result = await context.services.webapp_offer.set_section_active(
                    session, staff.provider_id, section_id, payload.active
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "section": result}, headers={"Cache-Control": "no-store"})

    @app.post("/api/webapp/provider/catalog/services")
    async def provider_add_service_webapp(
        request: Request, provider_id: int, section_id: int, payload: CatalogNameRequest
    ):
        verified = verified_webapp(request)
        try:
            async with context.database.session_factory() as session:
                staff = await verified_provider_staff(
                    session, verified, provider_id=provider_id, permission="can_manage_offers"
                )
                result = await context.services.webapp_offer.add_service(
                    session, staff.provider_id, section_id, payload.name
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "service": result}, headers={"Cache-Control": "no-store"})

    @app.patch("/api/webapp/provider/catalog/services/{service_id}")
    async def provider_rename_service_webapp(
        request: Request, provider_id: int, service_id: int, payload: CatalogNameRequest
    ):
        verified = verified_webapp(request)
        try:
            async with context.database.session_factory() as session:
                staff = await verified_provider_staff(
                    session, verified, provider_id=provider_id, permission="can_manage_offers"
                )
                result = await context.services.webapp_offer.rename_service(
                    session, staff.provider_id, service_id, payload.name
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "service": result}, headers={"Cache-Control": "no-store"})

    @app.patch("/api/webapp/provider/catalog/services/{service_id}/status")
    async def provider_service_status_webapp(
        request: Request, provider_id: int, service_id: int, payload: ActiveStateRequest
    ):
        verified = verified_webapp(request)
        try:
            async with context.database.session_factory() as session:
                staff = await verified_provider_staff(
                    session, verified, provider_id=provider_id, permission="can_manage_offers"
                )
                result = await context.services.webapp_offer.set_service_active(
                    session, staff.provider_id, service_id, payload.active
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "service": result}, headers={"Cache-Control": "no-store"})

    @app.post("/api/webapp/provider/offers/copy-suggestion")
    async def provider_offer_copy_webapp(request: Request, payload: OfferCopyRequest):
        verified = verified_webapp(request)
        async with context.database.session_factory() as session:
            await verified_provider_staff(
                session, verified, provider_id=payload.provider_id, permission="can_manage_offers"
            )
        try:
            answer = await context.services.gemini.answer(
                "أنت كاتب عروض CampusPass IQ للسوق الطلابي العراقي. اكتب شرحًا عربيًا واضحًا "
                "وجذابًا ومنظمًا بإيموجي معتدل. ابدأ بتعريف مختصر، ثم أبرز الفائدة للطالب، "
                "ثم المزايا المؤكدة من المدخلات فقط، ثم طريقة الحصول على الخدمة. "
                "ممنوع اختراع ميزة أو سعر أو مدة أو ضمان أو سرعة تفعيل أو وعد غير موجود. "
                "إذا كانت معلومة غير موجودة فتجاهلها. لا تكتب Markdown ثقيلًا ولا روابط. "
                "النص يجب أن يبقى قابلًا للتعديل من صاحب المنصة وبحد أقصى 1200 حرف.",
                {
                    "section": payload.section_name,
                    "service": payload.service_name,
                    "variant": payload.variant_name,
                    "title": payload.title,
                    "price_iqd": payload.price_iqd,
                    "duration": payload.duration_text,
                    "fulfillment": payload.fulfillment_label,
                    "warranty_enabled": payload.warranty_enabled,
                },
            )
        except Exception as exc:
            logger.warning("Offer copy suggestion failed: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="المساعد الذكي غير متاح مؤقتًا") from exc
        return JSONResponse(
            {"ok": True, "suggestion": answer.strip()[:1200]},
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/webapp/provider/offers")
    async def provider_create_offer_webapp(request: Request, payload: OfferCreateRequest):
        verified = verified_webapp(request)
        try:
            async with context.database.session_factory() as session:
                staff = await verified_provider_staff(
                    session, verified, provider_id=payload.provider_id, permission="can_manage_offers"
                )
                await assert_offer_webapp_available(session, staff)
                result = await context.services.webapp_offer.create_draft(
                    session,
                    staff=staff,
                    payload=OfferCreatePayload(**payload.model_dump(exclude={"provider_id"})),
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        next_action = str(result.get("next_action") or "ready")
        if next_action == "add_inventory":
            action_text = "📦 إضافة المخزون"
            action_callback = f"provider:inventory_offer:{result['offer_id']}"
            summary = "تم إنشاء العرض، وبقيت إضافة مخزون صالح قبل ظهوره للطلاب."
        elif next_action == "connect_email":
            action_text = "📨 إعداد بريد التفعيل"
            action_callback = f"provider:offer_manage:{result['offer_id']}"
            summary = "تم إنشاء العرض، وبقي إعداد بريد/OTP قبل تفعيله للطلاب."
        else:
            action_text = "📋 عرض العروض"
            action_callback = "provider:offers"
            summary = "تم إنشاء العرض وتفعيله بنجاح."
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=action_text,
                        callback_data=action_callback,
                        style="success" if next_action == "ready" else "primary",
                    )
                ],
                [InlineKeyboardButton(text="🛍 متجري والعروض", callback_data="provider:catalog")],
            ]
        )
        try:
            await context.bot.send_message(
                verified.user.id,
                f"✅ <b>{html.escape(str(result['title']))}</b>\n\n{summary}",
                reply_markup=markup,
            )
        except Exception:
            logger.warning("Could not deliver offer WebApp confirmation", exc_info=True)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.get("/ping")
    async def ping():
        """Ultra-light anti-sleep endpoint for Render/UptimeRobot.

        It intentionally performs no database, Redis, Telegram or filesystem I/O.
        """
        return {
            "status": "ok",
            "service": "CampusPass IQ",
            "version": __version__,
            "telegram_bot_api_target": TELEGRAM_BOT_API_TARGET,
            "aiogram_target": AIOGRAM_TARGET,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    @app.head("/ping")
    async def ping_head():
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.get("/health/live")
    async def health_live():
        # Render deployment probe: process/API is alive. Database and Telegram
        # readiness are intentionally checked by /health/ready instead.
        return {
            "status": "ok",
            "version": __version__,
            "telegram_bot_api_target": TELEGRAM_BOT_API_TARGET,
            "aiogram_target": AIOGRAM_TARGET,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    async def database_health_response():
        try:
            async with context.database.session_factory() as session:
                await session.execute(text("SELECT 1"))
            return JSONResponse({"status": "ok", "version": __version__})
        except Exception:
            logger.exception("database health probe failed")
            return JSONResponse({"status": "error", "version": __version__}, status_code=503)

    async def readiness_response():
        expected_bot = context.settings.runtime_mode in {"combined", "bot"}
        expected_worker = context.settings.runtime_mode in {"combined", "worker"}
        webhook_required = expected_bot and context.settings.telegram_delivery_mode == "webhook"
        try:
            async with context.database.session_factory() as session:
                live_gate = await context.services.deployment_gates.run(
                    session,
                    redis_client=context.redis_client,
                    include_telegram=False,
                    include_webhook=False,
                    include_worker=True,
                    persist=False,
                )
        except Exception as exc:
            live_gate = {"ok": False, "checks": {"gate": {"ok": False, "error": type(exc).__name__}}}
        components = {
            "database": context.database_ready,
            "redis": context.redis_ready if context.settings.require_redis_in_production else "optional",
            "bot": context.bot_ready if expected_bot else "not_required",
            "worker": context.worker_ready if expected_worker else "external",
            "release": context.release_registered,
            "webhook": context.webhook_ready if webhook_required else "not_required",
            "update_processor": context.update_processor_ready if webhook_required else "not_required",
            "update_inflight": context.update_inflight,
            "draining": context.draining,
            "deployment_gate": bool(live_gate.get("ok")),
        }
        components_ready = (
            context.database_ready
            and (not context.settings.require_redis_in_production or context.redis_ready)
            and (not expected_bot or context.bot_ready)
            and (not expected_worker or context.worker_ready)
            and (not webhook_required or (context.webhook_ready and context.update_processor_ready))
            and context.release_registered
            and not context.draining
            and bool(live_gate.get("ok"))
        )
        if not context.ready or not components_ready:
            return JSONResponse(
                {
                    "status": "starting" if not context.startup_error else "error",
                    "version": __version__,
                    "release_id": context.settings.release_id,
                    "runtime_mode": context.settings.runtime_mode,
                    "components": components,
                    "checks": live_gate.get("checks", {}),
                    "startup_error": context.startup_error or None,
                },
                status_code=503,
            )
        if context.settings.pilot_mode and context.settings.pilot_strict_startup:
            async with context.database.session_factory() as session:
                latest_validation = await context.services.pilot.latest(session)
            if not latest_validation or latest_validation.status != "passed":
                return JSONResponse(
                    {
                        "status": "pilot_validation_required",
                        "version": __version__,
                        "release_id": context.settings.release_id,
                        "validation_status": getattr(latest_validation, "status", "not_run"),
                    },
                    status_code=503,
                )
        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "release_id": context.settings.release_id,
                "runtime_mode": context.settings.runtime_mode,
                "components": components,
            },
            headers={"X-CampusPass-Release": context.settings.release_id, "Cache-Control": "no-store"},
        )

    @app.get("/health")
    async def health():
        # Backward-compatible database health endpoint. Render uses /ping and /health/live.
        return await database_health_response()

    @app.get("/health/ready")
    async def health_ready():
        return await readiness_response()

    def _require_operations_token(authorization: str, x_admin_token: str) -> None:
        supplied = x_admin_token.strip()
        if authorization.lower().startswith("bearer "):
            supplied = authorization.split(" ", 1)[1].strip()
        expected = context.settings.api_admin_token
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Unauthorized")

    @app.get("/health/deep")
    async def health_deep(
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default=""),
    ):
        _require_operations_token(authorization, x_admin_token)
        async with context.database.session_factory() as session:
            result = await context.services.deployment_gates.run(
                session,
                redis_client=context.redis_client,
                include_telegram=context.settings.runtime_mode in {"combined", "bot"},
                include_webhook=True,
                include_worker=True,
                persist=True,
            )
            await session.commit()
        return JSONResponse(result, status_code=200 if result.get("ok") else 503)

    @app.get("/admin/deployment/gates/latest")
    async def latest_deployment_gate(
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default=""),
    ):
        _require_operations_token(authorization, x_admin_token)
        async with context.database.session_factory() as session:
            row = await context.services.deployment_gates.latest(session)
        if row is None:
            raise HTTPException(404, "No deployment gate has been recorded")
        return {
            "public_id": row.public_id,
            "release_id": row.release_id,
            "environment": row.environment,
            "runtime_mode": row.runtime_mode,
            "status": row.status,
            "checks": row.checks_json,
            "error": row.error,
            "started_at": row.started_at.isoformat(),
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }

    @app.get("/admin/update/status")
    async def update_status(
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default=""),
    ):
        _require_operations_token(authorization, x_admin_token)
        async with context.database.session_factory() as session:
            compatibility = await session.scalar(
                select(ReleaseCompatibility).where(
                    ReleaseCompatibility.release_id == context.settings.release_id
                )
            )
            generations = list(
                (
                    await session.scalars(
                        select(RuntimeConfigGeneration).order_by(
                            RuntimeConfigGeneration.namespace
                        )
                    )
                ).all()
            )
        return {
            "version": __version__,
            "release_id": context.settings.release_id,
            "ready": context.ready,
            "draining": context.draining,
            "update_inflight": context.update_inflight,
            "compatibility": None
            if compatibility is None
            else {
                "status": compatibility.status,
                "schema_head": compatibility.schema_head,
                "minimum_release_version": compatibility.minimum_release_version,
                "minimum_schema_head": compatibility.minimum_schema_head,
                "callback_schema_version": compatibility.callback_schema_version,
                "event_schema_version": compatibility.event_schema_version,
                "rollout_percent": compatibility.rollout_percent,
                "checked_at": compatibility.checked_at.isoformat(),
                "last_error": compatibility.last_error,
            },
            "cache_generations": {row.namespace: row.generation for row in generations},
        }

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics(
        authorization: str = Header(default=""),
        x_metrics_token: str = Header(default=""),
    ):
        if not context.settings.metrics_enabled:
            raise HTTPException(404)
        expected = context.settings.metrics_token
        if expected:
            supplied = x_metrics_token.strip()
            if authorization.lower().startswith("bearer "):
                supplied = authorization.split(" ", 1)[1].strip()
            if not secrets.compare_digest(supplied, expected):
                raise HTTPException(401, "Unauthorized")
        async with context.database.session_factory() as session:
            snapshot = await context.services.health.snapshot(session)
            await session.commit()
        operations = snapshot.get("operations", {})
        backup = operations.get("backup", {})
        delivery = snapshot.get("delivery_jobs", {})
        notifications = snapshot.get("notifications", {})
        values = {
            "campuspass_ready": 1 if context.ready else 0,
            "campuspass_database_ready": 1 if context.database_ready else 0,
            "campuspass_bot_ready": 1 if context.bot_ready else 0,
            "campuspass_worker_ready": 1 if context.worker_ready else 0,
            "campuspass_draining": 1 if context.draining else 0,
            "campuspass_telegram_update_inflight": int(context.update_inflight),
            "campuspass_delivery_pending": int(delivery.get("pending", 0)),
            "campuspass_delivery_failed": int(delivery.get("failed", 0)),
            "campuspass_notifications_failed": int(notifications.get("failed", 0)),
            "campuspass_open_incidents": int(operations.get("open_incidents", 0)),
            "campuspass_failed_scheduled_runs": int(operations.get("failed_scheduled_runs", 0)),
            "campuspass_backup_stale": 1 if backup.get("stale") else 0,
            "campuspass_payment_reviews": int(snapshot.get("payment_reviews", 0)),
            "campuspass_open_tickets": int(snapshot.get("open_tickets", 0)),
        }
        body = "\n".join(f"{key} {value}" for key, value in values.items()) + "\n"
        return PlainTextResponse(body, headers={"Cache-Control": "no-store"})

    @app.get("/admin/health")
    async def admin_health(
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default=""),
    ):
        supplied = x_admin_token.strip()
        if authorization.lower().startswith("bearer "):
            supplied = authorization.split(" ", 1)[1].strip()
        expected = context.settings.api_admin_token
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Unauthorized")
        async with context.database.session_factory() as session:
            snapshot = await context.services.health.snapshot(session)
            await session.commit()
            return snapshot

    @app.get("/admin/operations")
    async def admin_operations(
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default=""),
    ):
        supplied = x_admin_token.strip()
        if authorization.lower().startswith("bearer "):
            supplied = authorization.split(" ", 1)[1].strip()
        expected = context.settings.api_admin_token
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Unauthorized")
        async with context.database.session_factory() as session:
            return await context.services.operations.status_snapshot(session)

    @app.get("/admin/pilot")
    async def admin_pilot(
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default=""),
    ):
        supplied = x_admin_token.strip()
        if authorization.lower().startswith("bearer "):
            supplied = authorization.split(" ", 1)[1].strip()
        expected = context.settings.api_admin_token
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Unauthorized")
        async with context.database.session_factory() as session:
            latest = await context.services.pilot.latest(session)
            if not latest:
                return {"status": "not_run", "pilot_mode": context.settings.pilot_mode}
            return {
                "status": latest.status,
                "pilot_mode": context.settings.pilot_mode,
                "blocking_failures": latest.blocking_failures,
                "warnings": latest.warnings,
                "checks": latest.checks_json,
                "completed_at": latest.completed_at.isoformat() if latest.completed_at else None,
            }

    @app.post("/admin/reports/{report_id}/revoke")
    async def revoke_report(
        report_id: int,
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default=""),
    ):
        supplied = x_admin_token.strip()
        if authorization.lower().startswith("bearer "):
            supplied = authorization.split(" ", 1)[1].strip()
        expected = context.settings.api_admin_token
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Unauthorized")
        async with context.database.session_factory() as session:
            revoked = await context.services.reports.revoke_report(session, report_id)
            await session.commit()
        if not revoked:
            raise HTTPException(404, "Report access not found or already revoked")
        return {"ok": True, "report_id": report_id, "revoked": True}

    async def _load_report(token: str):
        async with context.database.session_factory() as session:
            row = await context.services.reports.resolve_report(session, token)
            if not row:
                raise HTTPException(
                    404, "Report not found, expired, revoked, or access limit reached"
                )
            verification_url = context.services.reports.report_url(token)
            await session.commit()
            return row, verification_url

    @app.get("/reports/{token}", response_class=HTMLResponse)
    async def report(token: str):
        row, verification_url = await _load_report(token)
        rendered = context.services.reports.render(row, verification_url=verification_url)
        return HTMLResponse(
            rendered,
            headers={
                "Cache-Control": "no-store, private",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": (
                    "default-src 'none'; img-src 'self' data: https:; "
                    "style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
                ),
            },
        )

    @app.get("/reports/{token}/download/html", response_class=HTMLResponse)
    async def report_download_html(token: str):
        row, verification_url = await _load_report(token)
        rendered = context.services.reports.render(row, verification_url=verification_url)
        filename = context.services.reports.filename(row, "html")
        return HTMLResponse(
            rendered,
            headers={
                "Cache-Control": "no-store, private",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Security-Policy": (
                    "default-src 'none'; img-src 'self' data: https:; "
                    "style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
                ),
            },
        )

    @app.get("/reports/{token}/dashboard", response_class=HTMLResponse)
    async def report_dashboard(token: str):
        row, verification_url = await _load_report(token)
        if str(row.plan).lower() != "pro":
            raise HTTPException(403, "Secure dashboard is available for Pro reports only")
        rendered = context.services.reports.render(row, verification_url=verification_url)
        return HTMLResponse(rendered, headers={"Cache-Control": "no-store, private", "X-Frame-Options": "DENY"})

    @app.get("/reports/{token}/download/pdf")
    async def report_download_pdf(token: str):
        row, verification_url = await _load_report(token)
        if str(row.plan).lower() != "pro":
            raise HTTPException(403, "Official PDF is available for Pro reports only")
        artifact = await asyncio.to_thread(
            context.services.reports.render_artifact, row, verification_url=verification_url, format="pdf"
        )
        return Response(artifact.content, media_type=artifact.media_type, headers={
            "Cache-Control": "no-store, private", "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
        })

    @app.get("/reports/{token}/download/csv")
    async def report_download_csv_disabled(token: str):
        await _load_report(token)
        raise HTTPException(410, "CSV export was retired. Plus uses HTML and Pro uses PDF/Web App.")

    @app.get("/payments/return/{order_public_id}", response_class=HTMLResponse)
    async def payment_return(order_public_id: str):
        async with context.database.session_factory() as session:
            order = await context.services.orders.get_by_public_id(session, order_public_id[:40])
        if not order:
            raise HTTPException(404, "Order not found")
        status_label = {
            OrderStatus.PAID.value: "تم استلام الدفع بنجاح ✅",
            OrderStatus.WAITING_FULFILLMENT.value: "تم الدفع وجارٍ تجهيز الطلب ✅",
            OrderStatus.PROCESSING.value: "تم الدفع والطلب قيد التنفيذ ✅",
            OrderStatus.DELIVERED.value: "تم الدفع والتسليم ✅",
            OrderStatus.COMPLETED.value: "الطلب مكتمل ✅",
            OrderStatus.NEEDS_SUPPORT.value: "تم استلام العملية وتحتاج مراجعة الدعم",
        }.get(order.status, "ما زلنا ننتظر التأكيد النهائي من بوابة الدفع")
        body = (
            "<!doctype html><html lang='ar' dir='rtl'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>حالة الدفع</title>"
            "<body style='font-family:system-ui;max-width:640px;margin:15vh auto;padding:24px;line-height:1.8'>"
            f"<h1>{html.escape(status_label)}</h1>"
            f"<p>رقم الطلب: <strong>{html.escape(order.public_id)}</strong></p>"
            "<p>ارجع إلى البوت لعرض التفاصيل ومتابعة التسليم.</p>"
            "</body></html>"
        )
        return HTMLResponse(body, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})

    async def handle_payment_webhook(request: Request, x_signature: str) -> JSONResponse:
        if not context.settings.mastercard_ready:
            raise HTTPException(503, "Card payment connector is not configured")
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError as exc:
                raise HTTPException(400, "Invalid Content-Length") from exc
            if declared_size > context.settings.payment_webhook_max_body_bytes:
                raise HTTPException(413, "Payload too large")
        raw = await request.body()
        if len(raw) > context.settings.payment_webhook_max_body_bytes:
            raise HTTPException(413, "Payload too large")
        if not context.services.mastercard.verify_webhook(raw, x_signature):
            raise HTTPException(401, "Invalid signature")
        try:
            payload = orjson.loads(raw)
            notification = context.services.mastercard.parse_webhook(payload)
        except (orjson.JSONDecodeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

        async with context.database.session_factory() as session:
            result = await context.services.payments.process_gateway_notification(
                session, notification
            )
            await session.commit()

        fulfillment = "not_required"
        if result.order and result.event.processing_status == "confirmed":
            # A webhook can be retried after a crash between payment commit and fulfillment.
            # Fulfillment is idempotent, so PAID orders are safe to resume here.
            async with context.database.session_factory() as session:
                order = await context.services.orders.get(session, result.order.id)
                if order and order.status == OrderStatus.PAID.value:
                    try:
                        friend_member = await context.services.friend_packages.member_for_order(
                            session, order.id
                        )
                        if friend_member is None:
                            await context.services.fulfillment.fulfill(session, order)
                            fulfillment = "queued"
                        else:
                            progress = await context.services.friend_packages.progress(
                                session, friend_member.group_id
                            )
                            student = await session.get(User, friend_member.user_id)
                            if student is not None:
                                await context.services.notifications.send_user(
                                    session, student,
                                    "تم تأكيد دفعتك في باقة الأصدقاء ✅",
                                    f"{progress.status_text}\n"
                                    "سيُرسل الحساب تلقائياً للجميع بعد اكتمال العدد.",
                                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                        InlineKeyboardButton(
                                            text="👥 تحديث حالة الأصدقاء",
                                            callback_data=f"friend:progress:{friend_member.group_id}",
                                            style="primary",
                                        )
                                    ]]),
                                    idempotency_key=f"friend-gateway-payment-confirmed:{friend_member.id}",
                                )
                            fulfillment = "friend_group_waiting"
                        await session.commit()
                    except Exception as exc:
                        await session.rollback()
                        logger.exception("automatic fulfillment failed order=%s", order.id)
                        async with context.database.session_factory() as recovery:
                            recovery_order = await context.services.orders.get(recovery, order.id)
                            if recovery_order and recovery_order.status == OrderStatus.PAID.value:
                                await context.services.orders.change_status(
                                    recovery,
                                    recovery_order,
                                    OrderStatus.NEEDS_SUPPORT.value,
                                    note="فشل التجهيز التلقائي بعد الدفع الإلكتروني",
                                    metadata={"error": str(exc)[:500]},
                                )
                                await recovery.commit()
                        fulfillment = "support_required"

        if result.requires_review:
            message = (
                "⚠️ Webhook دفع يحتاج مراجعة\n"
                f"الطلب: {notification.order_public_id}\n"
                f"المرجع: {notification.reference}\n"
                f"السبب: {result.message}"
            )
            for admin_id in context.settings.admin_ids:
                try:
                    await context.bot.send_message(admin_id, message)
                except Exception:
                    logger.warning("Could not notify admin about payment webhook review")

        return JSONResponse(
            {
                "ok": True,
                "accepted": result.accepted,
                "duplicate": result.duplicate,
                "requires_review": result.requires_review,
                "fulfillment": fulfillment,
            },
            status_code=200 if result.accepted else 202,
        )

    @app.post("/webhooks/payments/mastercard")
    async def mastercard_payment_webhook(
        request: Request,
        x_signature: str = Header(default=""),
    ):
        return await handle_payment_webhook(request, x_signature)

    @app.post("/webhooks/payment")
    async def legacy_payment_webhook(
        request: Request,
        x_signature: str = Header(default=""),
    ):
        return await handle_payment_webhook(request, x_signature)


    def _require_admin_token(authorization: str, x_admin_token: str) -> None:
        supplied = x_admin_token.strip()
        if authorization.lower().startswith("bearer "):
            supplied = authorization.split(" ", 1)[1].strip()
        expected = context.settings.api_admin_token
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Unauthorized")

    @app.get("/admin/enterprise/dashboard")
    async def enterprise_dashboard(authorization: str = Header(default=""), x_admin_token: str = Header(default="")):
        _require_admin_token(authorization, x_admin_token)
        async with context.database.session_factory() as session:
            return await context.services.enterprise.dashboard(session)

    @app.post("/admin/enterprise/providers/{provider_id}/subscribe/{plan_code}")
    async def enterprise_subscribe(provider_id: int, plan_code: str, request: Request,
            authorization: str = Header(default=""), x_admin_token: str = Header(default="")):
        _require_admin_token(authorization, x_admin_token)
        payload = await request.json()
        idem = str(payload.get("idempotency_key", "")).strip()
        if not idem: raise HTTPException(422, "idempotency_key is required")
        async with context.database.session_factory() as session:
            row = await context.services.enterprise.subscribe(session, provider_id=provider_id,
                plan_code=plan_code, idempotency_key=idem)
            await session.commit()
            return {"public_id": row.public_id, "status": row.status, "period_end": row.current_period_end.isoformat()}

    @app.post("/admin/enterprise/invoices/{invoice_id}/paid")
    async def enterprise_mark_invoice_paid(invoice_id: int, request: Request,
            authorization: str = Header(default=""), x_admin_token: str = Header(default="")):
        _require_admin_token(authorization, x_admin_token)
        payload = await request.json(); idem = str(payload.get("idempotency_key", "")).strip()
        if not idem: raise HTTPException(422, "idempotency_key is required")
        async with context.database.session_factory() as session:
            try: row = await context.services.enterprise.mark_invoice_paid(session, invoice_id=invoice_id, payment_idempotency_key=idem)
            except ValueError as exc: raise HTTPException(404, str(exc)) from exc
            await session.commit(); return {"invoice_number": row.invoice_number, "status": row.status, "paid_iqd": row.paid_iqd}

    @app.get("/v1/provider/me")
    async def provider_api_me(x_api_key: str = Header(default="")):
        async with context.database.session_factory() as session:
            key = await context.services.enterprise.authenticate_api_key(session, x_api_key, "provider:read")
            if not key: raise HTTPException(401, "Invalid API key or scope")
            await session.commit()
            return {"provider_id": key.provider_id, "key_name": key.name, "scopes": key.scopes_json}

    @app.get("/admin/enterprise/scale")
    async def enterprise_scale_dashboard(authorization: str = Header(default=""), x_admin_token: str = Header(default="")):
        _require_admin_token(authorization, x_admin_token)
        async with context.database.session_factory() as session:
            return await context.services.enterprise_scale.dashboard(session)

    @app.get("/v1/provider/usage")
    async def provider_api_usage(x_api_key: str = Header(default="")):
        async with context.database.session_factory() as session:
            key = await context.services.enterprise.authenticate_api_key(session, x_api_key, "provider:read")
            if not key:
                raise HTTPException(401, "Invalid API key or scope")
            result = await context.services.enterprise_scale.record_usage(session, provider_id=key.provider_id,
                api_key_id=key.id, route="GET /v1/provider/usage",
                idempotency_key=f"usage-self:{key.id}:{datetime.now(UTC).isoformat()}")
            await session.commit()
            if not result["accepted"]:
                raise HTTPException(429, "Plan API request limit exceeded")
            return result

    return app
