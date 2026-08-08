from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.telegram_webapp import VerifiedInitData
from app.db.models import Provider, ProviderStaff, ProviderStatus, User
from app.services.audit import AuditService
from app.services.catalog import CatalogService
from app.services.platform_access import mark_platform_authorization_dirty
from app.services.subscriptions import SubscriptionService
from app.services.users import UserService
from app.services.webapp_validation import (
    normalize_staff_identifiers,
    parse_iqd_amount,
    validate_optional_arabic_platform_name,
    validate_optional_english_name,
    validate_optional_human_text,
    validate_optional_percentage,
    validate_telegram_id,
)


@dataclass(frozen=True, slots=True)
class ProviderCreatePayload:
    name_ar: str = ""
    name_en: str = ""
    description: str = ""
    owner_telegram_id: int = 0
    staff_identifiers: list[str] = field(default_factory=list)
    management_percent: int = 0
    service_fee_iqd: int = 0


class WebAppProviderService:
    """Owner-only provider creation for the hardened Telegram Web App wizard.

    The public provider name fields are deliberately optional. The database still
    needs a stable non-null display key, so an internal placeholder is generated
    only when the owner leaves both names empty; it can later be changed from the
    provider information workflow without exposing or asking for a slug.
    """

    def __init__(
        self,
        *,
        bot: Bot,
        settings: Settings,
        users: UserService,
        subscriptions: SubscriptionService,
        catalog: CatalogService,
        audit: AuditService,
    ) -> None:
        self.bot = bot
        self.settings = settings
        self.users = users
        self.subscriptions = subscriptions
        self.catalog = catalog
        self.audit = audit

    async def _unique_slug(self, session: AsyncSession) -> str:
        for _ in range(12):
            candidate = f"platform-{secrets.token_hex(5)}"
            exists = await session.scalar(select(Provider.id).where(Provider.slug == candidate))
            if not exists:
                return candidate
        raise RuntimeError("تعذر إنشاء معرف داخلي فريد للمنصة")

    async def _unique_internal_name(
        self,
        session: AsyncSession,
        *,
        name_ar: str,
        name_en: str,
        owner_telegram_id: int,
    ) -> str:
        preferred = name_ar or name_en
        if preferred:
            duplicate = await session.scalar(
                select(Provider.id).where(func.lower(Provider.name_ar) == preferred.lower())
            )
            if duplicate:
                raise ValueError("اسم المنصة مستخدم مسبقًا")
            return preferred
        base = f"منصة جديدة {str(owner_telegram_id)[-6:]}"
        candidate = base
        counter = 2
        while await session.scalar(select(Provider.id).where(Provider.name_ar == candidate)):
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    async def _resolve_staff(
        self,
        session: AsyncSession,
        identifiers: list[str],
        *,
        owner: User,
    ) -> list[User]:
        clean = normalize_staff_identifiers(identifiers)
        resolved: list[User] = []
        seen_ids = {owner.id}
        for identifier in clean:
            if identifier.startswith("@"):
                username = identifier[1:].lower()
                user = await session.scalar(
                    select(User).where(func.lower(User.telegram_username) == username)
                )
            else:
                user = await self.users.get(session, int(identifier))
            if user is None:
                raise ValueError(
                    f"الموظف {identifier} غير مسجل في البوت؛ يجب أن يفتح البوت ويضغط /start أولًا"
                )
            if user.id in seen_ids:
                continue
            if user.is_banned or not user.is_active:
                raise ValueError(f"الموظف {identifier} غير متاح حاليًا")
            seen_ids.add(user.id)
            resolved.append(user)
        return resolved

    @staticmethod
    def _owner_staff(provider_id: int, user_id: int) -> ProviderStaff:
        return ProviderStaff(
            provider_id=provider_id,
            user_id=user_id,
            title="owner",
            role="OWNER",
            can_review_payments=True,
            can_manage_offers=True,
            can_manage_inventory=True,
            can_manage_branding=True,
            can_support=True,
            can_view_reports=True,
            can_manage_disputes=True,
            can_approve_refunds=True,
            can_view_finance=True,
            can_request_withdrawal=True,
            can_manage_payout_accounts=True,
            can_view_pii=True,
            can_export_data=True,
            is_active=True,
        )

    @staticmethod
    def _operator_staff(provider_id: int, user_id: int) -> ProviderStaff:
        return ProviderStaff(
            provider_id=provider_id,
            user_id=user_id,
            title="operator",
            role="STAFF",
            can_review_payments=True,
            can_manage_offers=True,
            can_manage_inventory=True,
            can_manage_branding=False,
            can_support=True,
            can_view_reports=True,
            can_manage_disputes=False,
            can_approve_refunds=False,
            can_view_finance=False,
            can_request_withdrawal=False,
            can_manage_payout_accounts=False,
            can_view_pii=True,
            can_export_data=False,
            is_active=True,
        )

    async def create(
        self,
        session: AsyncSession,
        verified: VerifiedInitData,
        payload: ProviderCreatePayload,
    ) -> dict:
        if not self.settings.is_admin(verified.user.id):
            raise PermissionError("هذه الواجهة مخصصة لمالك البوت فقط")

        name_ar = validate_optional_arabic_platform_name(payload.name_ar)
        name_en = validate_optional_english_name(payload.name_en)
        description = validate_optional_human_text(
            payload.description,
            label="وصف المنصة",
            max_length=2000,
        )
        owner_telegram_id = validate_telegram_id(payload.owner_telegram_id)
        management_percent = validate_optional_percentage(payload.management_percent, default=0)
        service_fee_iqd = parse_iqd_amount(payload.service_fee_iqd, optional=True)

        owner = await self.users.get(session, owner_telegram_id)
        if owner is None:
            raise ValueError(
                "مالك المنصة غير مسجل في البوت. يجب أن يفتح البوت ويضغط /start أولًا ثم أعد المحاولة"
            )
        if owner.is_banned or not owner.is_active:
            raise ValueError("حساب مالك المنصة غير متاح حاليًا")

        staff_users = await self._resolve_staff(
            session,
            list(payload.staff_identifiers or []),
            owner=owner,
        )
        actor = await self.users.get_or_create(
            session,
            verified.user.id,
            verified.user.username,
            verified.user.full_name or "Bot Owner",
        )
        internal_name = await self._unique_internal_name(
            session,
            name_ar=name_ar,
            name_en=name_en,
            owner_telegram_id=owner_telegram_id,
        )
        if name_en:
            duplicate_en = await session.scalar(
                select(Provider.id).where(func.lower(Provider.name_en) == name_en.lower())
            )
            if duplicate_en:
                raise ValueError("اسم المنصة الإنجليزي مستخدم مسبقًا")

        provider = Provider(
            name_ar=internal_name,
            name_en=name_en,
            slug=await self._unique_slug(session),
            description=description,
            contact_username=(owner.telegram_username or None),
            management_percent=management_percent,
            default_service_fee_iqd=service_fee_iqd,
            status=ProviderStatus.ACTIVE.value,
            is_active=True,
        )
        session.add(provider)
        await session.flush()

        session.add(self._owner_staff(provider.id, owner.id))
        if owner.role == "user":
            owner.role = "provider"
        owner.has_platform_access = True
        for staff_user in staff_users:
            session.add(self._operator_staff(provider.id, staff_user.id))
            if staff_user.role == "user":
                staff_user.role = "provider"
            staff_user.has_platform_access = True

        await self.subscriptions.ensure_subscription(session, provider, actor)
        await self.catalog.create_default_provider_catalog(session, provider)
        await self.audit.log(
            session,
            actor,
            "provider.created.webapp.v2",
            "provider",
            str(provider.id),
            {
                "name_ar_input": name_ar,
                "name_en": name_en,
                "owner_telegram_id": owner_telegram_id,
                "staff_count": len(staff_users),
                "management_percent": management_percent,
                "service_fee_iqd": service_fee_iqd,
                "activated_immediately": True,
            },
        )
        mark_platform_authorization_dirty(
            session,
            telegram_id=owner_telegram_id,
            provider_id=provider.id,
        )
        for staff_user in staff_users:
            mark_platform_authorization_dirty(
                session,
                telegram_id=staff_user.telegram_id,
                provider_id=provider.id,
            )
        await session.flush()
        return {
            "ok": True,
            "provider_id": provider.id,
            "name": name_ar or name_en or internal_name,
            "name_ar": name_ar,
            "name_en": name_en,
            "owner_telegram_id": owner_telegram_id,
            "staff_telegram_ids": [user.telegram_id for user in staff_users],
            "management_percent": management_percent,
            "service_fee_iqd": service_fee_iqd,
            "is_active": True,
            "requires_logo": False,
        }

    async def notify_created(self, *, admin_telegram_id: int, result: dict) -> None:
        provider_id = int(result["provider_id"])
        name = str(result.get("name") or f"منصة #{provider_id}")
        admin_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🏢 فتح المنصة",
                        callback_data=f"admin:provider:{provider_id}",
                        style="primary",
                    )
                ],
                [InlineKeyboardButton(text="🏢 العودة للمنصات", callback_data="admin:providers")],
            ]
        )
        try:
            await self.bot.send_message(
                admin_telegram_id,
                f"✅ تم إنشاء وتفعيل منصة <b>{name}</b> من الـWeb App.\n\n"
                f"👤 المالك: <code>{int(result['owner_telegram_id'])}</code>\n"
                f"👥 الموظفون: <b>{len(result.get('staff_telegram_ids') or [])}</b>\n"
                f"📊 نسبة الإدارة: <b>{int(result.get('management_percent') or 0)}%</b>\n"
                f"⚙️ رسوم الخدمة لكل طلب: <b>{int(result.get('service_fee_iqd') or 0):,} د.ع</b>\n"
                "🖼 الشعار اختياري ويمكن إضافته أو تغييره لاحقًا.",
                reply_markup=admin_markup,
            )
        except Exception:
            pass

        recipients = [int(result["owner_telegram_id"])] + [
            int(item) for item in result.get("staff_telegram_ids") or []
        ]
        for telegram_id in dict.fromkeys(recipients):
            if telegram_id == admin_telegram_id:
                continue
            try:
                await self.bot.send_message(
                    telegram_id,
                    f"🏢 تم ربط حسابك بمنصة <b>{name}</b>.\n"
                    "عند فتح لوحة المنصة ستظهر لك سياسة العمل والخصوصية قبل أدوات الإدارة.",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="🏢 لوحة إدارة المنصة",
                                    callback_data=f"provider:select:{provider_id}",
                                    style="success",
                                )
                            ]
                        ]
                    ),
                )
            except Exception:
                pass
