from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin.common import admin_actor, admin_back, require_admin
from app.bot.states import (
    AdminBillingPolicyStates,
    AdminCampaignRejectStates,
    AdminCouponCampaignStates,
    AdminHybridBundleStates,
)
from app.bot.ui import edit_or_send
from app.core.config import Settings
from app.core.utils import parse_money, safe
from app.db.models import (
    AdCampaign,
    BusinessInvoice,
    BusinessInvoiceProof,
    BusinessInvoiceStatus,
    CampaignStatus,
    CouponCampaign,
    HybridBundle,
    HybridBundleStatus,
    HybridPurchaseProof,
    Offer,
    OwnerInboxItem,
    OwnerInboxStatus,
    Provider,
    ProviderBillingPolicy,
    RewardTaskCampaign,
    RewardTaskStatus,
)
from app.domain.owner_commerce import HybridAllocation
from app.services.container import Services

router = Router(name="admin_owner_commerce")


def _nav(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    rows.append([InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _money(value: int | None) -> str:
    return f"{int(value or 0):,} د.ع"


@router.callback_query(F.data == "admin:owner_commerce")
async def owner_commerce_home(callback: CallbackQuery, settings: Settings) -> None:
    await callback.answer()
    if not callback.message or not await require_admin(callback, settings):
        return
    await edit_or_send(
        callback.message,
        "🏢 <b>مركز التجارة والسيادة</b>\n\n"
        "إدارة الفوترة، بريد الإدارة، الإعلانات، الأكواد، الباقات الهجينة والمهام.",
        reply_markup=_nav([
            [InlineKeyboardButton(text="🧾 فوترة المنصات", callback_data="admin:owner_billing", style="success")],
            [InlineKeyboardButton(text="📥 بريد الإدارة المركزي", callback_data="admin:owner_inbox", style="danger")],
            [InlineKeyboardButton(text="📢 الحملات الإعلانية", callback_data="admin:owner_ads", style="primary")],
            [InlineKeyboardButton(text="🎯 حملات الأكواد", callback_data="admin:coupon_campaigns", style="success")],
            [InlineKeyboardButton(text="📦 الباقات الهجينة", callback_data="admin:hybrid_bundles", style="primary")],
            [InlineKeyboardButton(text="💰 حملات المهام", callback_data="admin:reward_campaigns", style="success")],
        ]),
    )


@router.callback_query(F.data == "admin:owner_billing")
async def billing_home(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not callback.message or not await require_admin(callback, settings):
        return
    providers = list((await session.scalars(select(Provider).order_by(Provider.name_ar).limit(50))).all())
    outstanding = list((await session.scalars(
        select(BusinessInvoice).where(
            BusinessInvoice.status.in_([
                BusinessInvoiceStatus.ISSUED.value,
                BusinessInvoiceStatus.PARTIALLY_PAID.value,
                BusinessInvoiceStatus.OVERDUE.value,
            ])
        ).order_by(BusinessInvoice.due_at).limit(20)
    )).all())
    lines = ["🧾 <b>فوترة المنصات B2B</b>", ""]
    if outstanding:
        lines.append("<b>الفواتير المفتوحة:</b>")
        for item in outstanding[:8]:
            lines.append(f"• {safe(item.invoice_number)} — {_money(item.total_iqd-item.paid_iqd)} — {safe(item.status)}")
    else:
        lines.append("لا توجد فواتير مفتوحة ✅")
    rows = [[InlineKeyboardButton(
        text=f"🏢 {provider.name_ar}", callback_data=f"admin:billing_provider:{provider.id}", style="primary"
    )] for provider in providers]
    rows.insert(0, [InlineKeyboardButton(text="⚡ إصدار الفواتير المستحقة الآن", callback_data="admin:billing_issue_now", style="success")])
    await edit_or_send(callback.message, "\n".join(lines), reply_markup=_nav(rows))


@router.callback_query(F.data == "admin:billing_issue_now")
async def billing_issue_now(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not callback.message or not await require_admin(callback, settings):
        return
    invoices = await services.owner_commerce.issue_due_invoices(session, now=datetime.now(UTC))
    await edit_or_send(
        callback.message,
        f"✅ تم فحص السياسات وإصدار <b>{len(invoices)}</b> فاتورة جديدة.",
        reply_markup=admin_back(),
    )


@router.callback_query(F.data.startswith("admin:billing_provider:"))
async def billing_provider(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not callback.message or not await require_admin(callback, settings):
        return
    provider_id = int((callback.data or "").rsplit(":", 1)[1])
    provider = await session.get(Provider, provider_id)
    if not provider:
        await edit_or_send(callback.message, "المنصة غير موجودة.", reply_markup=admin_back())
        return
    policy = await session.scalar(select(ProviderBillingPolicy).where(ProviderBillingPolicy.provider_id == provider_id))
    fee = policy.fixed_service_fee_iqd if policy else 0
    cycle = policy.cycle_days if policy else 30
    due = policy.due_hours if policy else 48
    auto = policy.auto_suspend if policy else True
    rows = [
        [InlineKeyboardButton(text="أسبوعي", callback_data=f"admin:billing_cycle:{provider_id}:7"), InlineKeyboardButton(text="شهري", callback_data=f"admin:billing_cycle:{provider_id}:30")],
        [InlineKeyboardButton(text="💰 تعديل الرسم", callback_data=f"admin:billing_fee:{provider_id}", style="success")],
        [InlineKeyboardButton(text="⏳ تعديل مهلة السداد", callback_data=f"admin:billing_due:{provider_id}", style="primary")],
        [InlineKeyboardButton(text="↩️ الفوترة", callback_data="admin:owner_billing")],
    ]
    await edit_or_send(
        callback.message,
        f"🏢 <b>{safe(provider.name_ar)}</b>\n\n"
        f"الرسم الدوري: <b>{_money(fee)}</b>\n"
        f"الدورة: <b>{cycle} يوماً</b>\n"
        f"مهلة السداد: <b>{due} ساعة</b>\n"
        f"التعليق التلقائي: <b>{'مفعل' if auto else 'متوقف'}</b>\n"
        f"حالة المنصة: <code>{safe(provider.status)}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("admin:billing_cycle:"))
async def billing_cycle(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not callback.message or not await require_admin(callback, settings):
        return
    _, _, provider_raw, days_raw = (callback.data or "").split(":")
    provider_id, days = int(provider_raw), int(days_raw)
    current = await session.scalar(select(ProviderBillingPolicy).where(ProviderBillingPolicy.provider_id == provider_id))
    await services.owner_commerce.upsert_billing_policy(
        session, provider_id=provider_id, cycle_days=days,
        due_hours=current.due_hours if current else 48,
        fixed_service_fee_iqd=current.fixed_service_fee_iqd if current else 0,
        ad_hourly_rate_iqd=current.ad_hourly_rate_iqd if current else 1000,
        auto_suspend=current.auto_suspend if current else True,
    )
    provider = await session.get(Provider, provider_id)
    updated = await session.scalar(select(ProviderBillingPolicy).where(ProviderBillingPolicy.provider_id == provider_id))
    await edit_or_send(
        callback.message,
        f"✅ تم تحديث دورة فوترة <b>{safe(provider.name_ar if provider else provider_id)}</b> إلى "
        f"<b>{updated.cycle_days if updated else days} يوماً</b>.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="↩️ إعداد المنصة", callback_data=f"admin:billing_provider:{provider_id}")
        ]]),
    )


@router.callback_query(F.data.startswith("admin:billing_fee:"))
async def billing_fee_start(
    callback: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await callback.answer()
    if not callback.message or not await require_admin(callback, settings):
        return
    provider_id = int((callback.data or "").rsplit(":", 1)[1])
    await state.set_state(AdminBillingPolicyStates.fee)
    await state.update_data(billing_provider_id=provider_id)
    await edit_or_send(callback.message, "اكتب الرسم الدوري بالدينار. اكتب 0 لإعفاء المنصة:")


@router.message(AdminBillingPolicyStates.fee)
async def billing_fee_save(
    message: Message, state: FSMContext, session: AsyncSession, settings: Settings, services: Services
) -> None:
    if not await require_admin(message, settings):
        return
    data = await state.get_data(); provider_id = int(data["billing_provider_id"])
    try:
        amount = parse_money(message.text or "")
        if amount < 0:
            raise ValueError
    except Exception:
        await message.answer("اكتب مبلغاً صحيحاً مثل 25000 أو 25 ألف.")
        return
    current = await session.scalar(select(ProviderBillingPolicy).where(ProviderBillingPolicy.provider_id == provider_id))
    await services.owner_commerce.upsert_billing_policy(
        session, provider_id=provider_id, cycle_days=current.cycle_days if current else 30,
        due_hours=current.due_hours if current else 48, fixed_service_fee_iqd=amount,
        ad_hourly_rate_iqd=current.ad_hourly_rate_iqd if current else 1000,
        auto_suspend=current.auto_suspend if current else True,
    )
    await state.clear()
    await message.answer(f"✅ تم اعتماد الرسم: {_money(amount)}", reply_markup=admin_back())


@router.callback_query(F.data.startswith("admin:billing_due:"))
async def billing_due_start(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await callback.answer()
    if not callback.message or not await require_admin(callback, settings): return
    await state.set_state(AdminBillingPolicyStates.due_hours)
    await state.update_data(billing_provider_id=int((callback.data or "").rsplit(":",1)[1]))
    await edit_or_send(callback.message, "اكتب مهلة السداد بالساعات، مثال: 48")


@router.message(AdminBillingPolicyStates.due_hours)
async def billing_due_save(message: Message, state: FSMContext, session: AsyncSession, settings: Settings, services: Services) -> None:
    if not await require_admin(message, settings): return
    if not (message.text or "").strip().isdigit():
        await message.answer("أدخل عدداً صحيحاً من الساعات."); return
    hours=int((message.text or "0").strip()); data=await state.get_data(); provider_id=int(data["billing_provider_id"])
    current=await session.scalar(select(ProviderBillingPolicy).where(ProviderBillingPolicy.provider_id==provider_id))
    try:
        await services.owner_commerce.upsert_billing_policy(
            session, provider_id=provider_id, cycle_days=current.cycle_days if current else 30,
            due_hours=hours, fixed_service_fee_iqd=current.fixed_service_fee_iqd if current else 0,
            ad_hourly_rate_iqd=current.ad_hourly_rate_iqd if current else 1000,
            auto_suspend=current.auto_suspend if current else True,
        )
    except ValueError as exc:
        await message.answer(str(exc)); return
    await state.clear(); await message.answer("✅ تم تحديث المهلة.", reply_markup=admin_back())


@router.callback_query(F.data == "admin:owner_inbox")
async def owner_inbox(callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services) -> None:
    await callback.answer()
    if not callback.message or not await require_admin(callback, settings): return
    await services.owner_commerce.sync_central_inbox(session, limit=100)
    items=list((await session.scalars(
        select(OwnerInboxItem).where(OwnerInboxItem.status.in_([OwnerInboxStatus.NEW.value, OwnerInboxStatus.IN_PROGRESS.value]))
        .order_by(OwnerInboxItem.priority, OwnerInboxItem.created_at).limit(30)
    )).all())
    rows=[]
    for item in items:
        rows.append([InlineKeyboardButton(text=f"{item.kind} • {item.summary[:34]}", callback_data=f"admin:owner_inbox_item:{item.id}", style="danger" if item.priority<=20 else "primary")])
    await edit_or_send(callback.message, f"📥 <b>بريد الإدارة المركزي</b>\n\nالعناصر المفتوحة: <b>{len(items)}</b>", reply_markup=_nav(rows))


@router.callback_query(F.data.startswith("admin:owner_inbox_item:"))
async def owner_inbox_item(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not callback.message or not await require_admin(callback, settings): return
    item_id=int((callback.data or "").rsplit(":",1)[1]); item=await session.get(OwnerInboxItem,item_id)
    if not item:
        await edit_or_send(callback.message,"العنصر غير موجود.",reply_markup=admin_back()); return
    rows=[]
    if item.source_type=="business_invoice_proof":
        rows=[[InlineKeyboardButton(text="✅ تأكيد الدفع",callback_data=f"admin:invoice_proof:{item.source_id}:approve",style="success"),InlineKeyboardButton(text="❌ رفض",callback_data=f"admin:invoice_proof:{item.source_id}:reject",style="danger")]]
    elif item.source_type=="ad_campaign":
        rows=[[InlineKeyboardButton(text="✅ إطلاق الحملة",callback_data=f"admin:ad_review:{item.source_id}:approve",style="success"),InlineKeyboardButton(text="❌ رفض",callback_data=f"admin:ad_review:{item.source_id}:reject",style="danger")]]
    elif item.source_type=="reward_task_campaign":
        rows=[[InlineKeyboardButton(text="✅ تفعيل المهمة",callback_data=f"admin:reward_review:{item.source_id}:approve",style="success"),InlineKeyboardButton(text="❌ رفض",callback_data=f"admin:reward_review:{item.source_id}:reject",style="danger")]]
    elif item.source_type=="hybrid_purchase_proof":
        rows=[[InlineKeyboardButton(text="✅ تأكيد الباقة",callback_data=f"admin:hybrid_proof:{item.source_id}:approve",style="success"),InlineKeyboardButton(text="❌ رفض",callback_data=f"admin:hybrid_proof:{item.source_id}:reject",style="danger")]]
    else:
        rows=[[InlineKeyboardButton(text="✅ إغلاق كمعالج",callback_data=f"admin:owner_inbox_resolve:{item.id}",style="success")]]
    rows.append([InlineKeyboardButton(text="↩️ البريد",callback_data="admin:owner_inbox")])
    await edit_or_send(callback.message,
        f"📨 <b>{safe(item.summary)}</b>\n\nالنوع: <code>{safe(item.kind)}</code>\nالمصدر: <code>{safe(item.source_type)}#{item.source_id}</code>\nالأولوية: <b>{item.priority}</b>\nالبيانات: <code>{safe(str(item.payload_json)[:1000])}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("admin:owner_inbox_resolve:"))
async def owner_inbox_resolve(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not callback.message or not await require_admin(callback, settings): return
    item=await session.get(OwnerInboxItem,int((callback.data or "").rsplit(":",1)[1]))
    if item:
        item.status=OwnerInboxStatus.RESOLVED.value; item.resolved_at=datetime.now(UTC)
    await edit_or_send(callback.message,"✅ تم إغلاق العنصر.",reply_markup=admin_back())


async def _review_source(callback: CallbackQuery, state: FSMContext, session: AsyncSession, settings: Settings, services: Services, source: str) -> None:
    if not callback.message or not await require_admin(callback, settings): return
    parts=(callback.data or "").split(":"); source_id=int(parts[-2]); action=parts[-1]
    actor=await admin_actor(session,services,callback)
    if not actor: return
    if action=="reject":
        await state.set_state(AdminCampaignRejectStates.reason)
        await state.update_data(review_source=source, review_id=source_id)
        await edit_or_send(callback.message,"اكتب سبب الرفض الرسمي:")
        return
    if source=="invoice": await services.owner_commerce.review_invoice_proof(session,proof_id=source_id,admin_user_id=actor.id,approved=True)
    elif source=="ad": await services.owner_commerce.approve_ad_campaign(session,campaign_id=source_id,admin_user_id=actor.id,approved=True)
    elif source=="reward": await services.owner_commerce.approve_reward_campaign(session,campaign_id=source_id,admin_user_id=actor.id,approved=True)
    elif source=="hybrid": await services.owner_commerce.review_hybrid_purchase_proof(session,proof_id=source_id,admin_user_id=actor.id,approved=True)
    await edit_or_send(callback.message,"✅ تم الاعتماد بنجاح.",reply_markup=admin_back())


@router.callback_query(F.data.startswith("admin:invoice_proof:"))
async def invoice_review(callback: CallbackQuery,state:FSMContext,session:AsyncSession,settings:Settings,services:Services)->None:
    await callback.answer(); await _review_source(callback,state,session,settings,services,"invoice")
@router.callback_query(F.data.startswith("admin:ad_review:"))
async def ad_review(callback: CallbackQuery,state:FSMContext,session:AsyncSession,settings:Settings,services:Services)->None:
    await callback.answer(); await _review_source(callback,state,session,settings,services,"ad")
@router.callback_query(F.data.startswith("admin:reward_review:"))
async def reward_review(callback: CallbackQuery,state:FSMContext,session:AsyncSession,settings:Settings,services:Services)->None:
    await callback.answer(); await _review_source(callback,state,session,settings,services,"reward")
@router.callback_query(F.data.startswith("admin:hybrid_proof:"))
async def hybrid_review(callback: CallbackQuery,state:FSMContext,session:AsyncSession,settings:Settings,services:Services)->None:
    await callback.answer(); await _review_source(callback,state,session,settings,services,"hybrid")


@router.message(AdminCampaignRejectStates.reason)
async def review_reject_reason(message:Message,state:FSMContext,session:AsyncSession,settings:Settings,services:Services)->None:
    if not await require_admin(message,settings): return
    data=await state.get_data(); source=str(data["review_source"]); source_id=int(data["review_id"]); actor=await admin_actor(session,services,message)
    if not actor:return
    reason=(message.text or "").strip()[:1000]
    if source=="invoice": await services.owner_commerce.review_invoice_proof(session,proof_id=source_id,admin_user_id=actor.id,approved=False,reason=reason)
    elif source=="ad": await services.owner_commerce.approve_ad_campaign(session,campaign_id=source_id,admin_user_id=actor.id,approved=False,reason=reason)
    elif source=="reward": await services.owner_commerce.approve_reward_campaign(session,campaign_id=source_id,admin_user_id=actor.id,approved=False,reason=reason)
    elif source=="hybrid": await services.owner_commerce.review_hybrid_purchase_proof(session,proof_id=source_id,admin_user_id=actor.id,approved=False,reason=reason)
    await state.clear(); await message.answer("تم الرفض وتسجيل السبب.",reply_markup=admin_back())


@router.callback_query(F.data == "admin:owner_ads")
async def owner_ads(callback:CallbackQuery,session:AsyncSession,settings:Settings)->None:
    await callback.answer()
    if not callback.message or not await require_admin(callback,settings):return
    campaigns=list((await session.scalars(select(AdCampaign).order_by(AdCampaign.id.desc()).limit(25))).all())
    rows=[[InlineKeyboardButton(text=f"{c.title[:28]} • {c.status}",callback_data=f"admin:owner_inbox_item_by_ad:{c.id}")] for c in campaigns]
    rows.append([InlineKeyboardButton(text="↩️ مركز التجارة",callback_data="admin:owner_commerce")])
    await edit_or_send(callback.message,"📢 <b>الحملات الإعلانية</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("admin:owner_inbox_item_by_ad:"))
async def owner_ad_detail(callback:CallbackQuery,session:AsyncSession,settings:Settings)->None:
    await callback.answer()
    if not callback.message or not await require_admin(callback,settings):return
    campaign=await session.get(AdCampaign,int((callback.data or "").rsplit(":",1)[1]))
    if not campaign:return
    rows=[]
    if campaign.status in {CampaignStatus.UNDER_REVIEW.value,CampaignStatus.AWAITING_PAYMENT.value,CampaignStatus.DRAFT.value}:
        rows.append([InlineKeyboardButton(text="✅ اعتماد",callback_data=f"admin:ad_review:{campaign.id}:approve",style="success"),InlineKeyboardButton(text="❌ رفض",callback_data=f"admin:ad_review:{campaign.id}:reject",style="danger")])
    rows.append([InlineKeyboardButton(text="↩️ الحملات",callback_data="admin:owner_ads")])
    await edit_or_send(callback.message,f"📢 <b>{safe(campaign.title)}</b>\n\nالحالة: {safe(campaign.status)}\nالنوع: {safe(campaign.campaign_type)}\nالقيمة: {_money(campaign.total_iqd)}\nالجمهور: <code>{safe(str(campaign.audience_rule_json))}</code>",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "admin:coupon_campaigns")
async def coupon_campaigns(callback:CallbackQuery,session:AsyncSession,settings:Settings)->None:
    await callback.answer()
    if not callback.message or not await require_admin(callback,settings):return
    items=list((await session.scalars(select(CouponCampaign).order_by(CouponCampaign.id.desc()).limit(20))).all())
    text="🎯 <b>حملات الأكواد الموجهة</b>\n\n"+"\n".join(f"• حملة #{x.id} — {x.assigned_count} طالب" for x in items)
    await edit_or_send(callback.message,text,reply_markup=_nav([[InlineKeyboardButton(text="➕ إنشاء حملة كود",callback_data="admin:coupon_campaign_new",style="success")]]))


@router.callback_query(F.data == "admin:coupon_campaign_new")
async def coupon_new(callback:CallbackQuery,state:FSMContext,settings:Settings)->None:
    await callback.answer()
    if not callback.message or not await require_admin(callback,settings):return
    await state.set_state(AdminCouponCampaignStates.provider)
    await edit_or_send(callback.message,"اكتب رقم المنصة، أو 0 لكود عام من مالك البوت:")


@router.message(AdminCouponCampaignStates.provider)
async def coupon_provider(message:Message,state:FSMContext,settings:Settings)->None:
    if not await require_admin(message,settings):return
    if not (message.text or "").strip().isdigit():await message.answer("أدخل رقماً صحيحاً.");return
    await state.update_data(coupon_provider_id=int((message.text or "0").strip()) or None)
    await state.set_state(AdminCouponCampaignStates.audience)
    await message.answer("اكتب الجمهور بصيغة مثل: all أو college:طب أو university:بغداد أو provider_buyers:3 أو status_link_sharers")


@router.message(AdminCouponCampaignStates.audience)
async def coupon_audience(message:Message,state:FSMContext,settings:Settings)->None:
    if not await require_admin(message,settings):return
    raw=(message.text or "").strip(); parts=raw.split(":",1); rule={"type":parts[0].strip(),"limit":5000}
    if len(parts)>1:rule["value"]=parts[1].strip()
    await state.update_data(coupon_audience=rule); await state.set_state(AdminCouponCampaignStates.code); await message.answer("اكتب كود الخصم:")


@router.message(AdminCouponCampaignStates.code)
async def coupon_code(message:Message,state:FSMContext,settings:Settings)->None:
    if not await require_admin(message,settings):return
    await state.update_data(coupon_code=(message.text or "").strip().upper());await state.set_state(AdminCouponCampaignStates.kind)
    await message.answer("اكتب percent للخصم النسبي أو fixed للمبلغ الثابت:")


@router.message(AdminCouponCampaignStates.kind)
async def coupon_kind(message:Message,state:FSMContext,settings:Settings)->None:
    if not await require_admin(message,settings):return
    kind=(message.text or "").strip().lower()
    if kind not in {"percent","fixed"}:await message.answer("اكتب percent أو fixed فقط.");return
    await state.update_data(coupon_kind=kind);await state.set_state(AdminCouponCampaignStates.value);await message.answer("اكتب قيمة الخصم:")


@router.message(AdminCouponCampaignStates.value)
async def coupon_value(message:Message,state:FSMContext,session:AsyncSession,settings:Settings,services:Services)->None:
    if not await require_admin(message,settings):return
    data=await state.get_data();actor=await admin_actor(session,services,message)
    try:value=int((message.text or "0").strip())
    except ValueError:await message.answer("أدخل رقماً صحيحاً.");return
    if not actor:return
    try:
        campaign=await services.owner_commerce.create_coupon_campaign(session,code=data["coupon_code"],coupon_type=data["coupon_kind"],value_int=value,provider_id=data.get("coupon_provider_id"),created_by_user_id=actor.id,audience_rule=data["coupon_audience"])
    except ValueError as exc:await message.answer(str(exc));return
    await state.clear();await message.answer(f"✅ أُنشئت الحملة ووُزع الكود على {campaign.assigned_count} طالب.",reply_markup=admin_back())


@router.callback_query(F.data == "admin:hybrid_bundles")
async def hybrid_bundles(callback:CallbackQuery,session:AsyncSession,settings:Settings)->None:
    await callback.answer()
    if not callback.message or not await require_admin(callback,settings):return
    bundles=list((await session.scalars(select(HybridBundle).order_by(HybridBundle.id.desc()).limit(20))).all())
    rows=[[InlineKeyboardButton(text=f"{b.title[:28]} • {b.status}",callback_data=f"admin:hybrid_toggle:{b.id}")] for b in bundles]
    rows.insert(0,[InlineKeyboardButton(text="➕ إنشاء باقة هجينة",callback_data="admin:hybrid_new",style="success")])
    await edit_or_send(callback.message,"📦 <b>الباقات المدمجة والهجينة</b>",reply_markup=_nav(rows))


@router.callback_query(F.data == "admin:hybrid_new")
async def hybrid_new(callback:CallbackQuery,state:FSMContext,settings:Settings)->None:
    await callback.answer()
    if not callback.message or not await require_admin(callback,settings):return
    await state.set_state(AdminHybridBundleStates.title);await edit_or_send(callback.message,"اكتب اسم الباقة:")


@router.message(AdminHybridBundleStates.title)
async def hybrid_title(message:Message,state:FSMContext,settings:Settings)->None:
    if not await require_admin(message,settings):return
    await state.update_data(hybrid_title=(message.text or "").strip());await state.set_state(AdminHybridBundleStates.description);await message.answer("اكتب وصف الباقة:")
@router.message(AdminHybridBundleStates.description)
async def hybrid_description(message:Message,state:FSMContext,settings:Settings)->None:
    if not await require_admin(message,settings):return
    await state.update_data(hybrid_description=(message.text or "").strip());await state.set_state(AdminHybridBundleStates.price);await message.answer("اكتب السعر الإجمالي بالدينار:")
@router.message(AdminHybridBundleStates.price)
async def hybrid_price(message:Message,state:FSMContext,settings:Settings)->None:
    if not await require_admin(message,settings):return
    try:value=parse_money(message.text or "")
    except Exception:await message.answer("سعر غير صحيح.");return
    await state.update_data(hybrid_price=value);await state.set_state(AdminHybridBundleStates.bot_fee);await message.answer("اكتب رسوم البوت ضمن السعر:")
@router.message(AdminHybridBundleStates.bot_fee)
async def hybrid_fee(message:Message,state:FSMContext,settings:Settings)->None:
    if not await require_admin(message,settings):return
    try:value=parse_money(message.text or "")
    except Exception:await message.answer("مبلغ غير صحيح.");return
    await state.update_data(hybrid_fee=value);await state.set_state(AdminHybridBundleStates.components);await message.answer("اكتب كل مكون بسطر بالشكل offer_id:حصة_المنصة\nمثال:\n12:13000\n25:8000")
@router.message(AdminHybridBundleStates.components)
async def hybrid_components(message:Message,state:FSMContext,session:AsyncSession,settings:Settings,services:Services)->None:
    if not await require_admin(message,settings):return
    data=await state.get_data();components=[]
    try:
        for line in (message.text or "").splitlines():
            if not line.strip():continue
            offer_raw,share_raw=line.split(":",1);offer=await session.get(Offer,int(offer_raw.strip()))
            if not offer:raise ValueError(f"العرض {offer_raw} غير موجود")
            components.append(HybridAllocation(provider_id=offer.provider_id,offer_id=offer.id,amount_iqd=parse_money(share_raw)))
        actor=await admin_actor(session,services,message)
        if not actor:raise ValueError("تعذر تحديد المالك")
        bundle=await services.owner_commerce.create_hybrid_bundle(session,title=data["hybrid_title"],description=data["hybrid_description"],price_iqd=int(data["hybrid_price"]),bot_fee_iqd=int(data["hybrid_fee"]),components=components,created_by_user_id=actor.id)
        await services.owner_commerce.activate_hybrid_bundle(session,bundle.id)
    except (ValueError,TypeError) as exc:await message.answer(f"تعذر إنشاء الباقة: {exc}");return
    await state.clear();await message.answer(f"✅ تم إنشاء وتفعيل الباقة {bundle.title}.",reply_markup=admin_back())


@router.callback_query(F.data.startswith("admin:hybrid_toggle:"))
async def hybrid_toggle(callback:CallbackQuery,session:AsyncSession,settings:Settings,services:Services)->None:
    await callback.answer()
    if not callback.message or not await require_admin(callback,settings):return
    bundle=await session.get(HybridBundle,int((callback.data or "").rsplit(":",1)[1]))
    if not bundle:return
    if bundle.status==HybridBundleStatus.ACTIVE.value:bundle.status=HybridBundleStatus.PAUSED.value
    else:await services.owner_commerce.activate_hybrid_bundle(session,bundle.id)
    await edit_or_send(callback.message,f"تم تحديث حالة الباقة إلى {bundle.status}.",reply_markup=admin_back())


@router.callback_query(F.data == "admin:reward_campaigns")
async def reward_campaigns(callback:CallbackQuery,session:AsyncSession,settings:Settings)->None:
    await callback.answer()
    if not callback.message or not await require_admin(callback,settings):return
    campaigns=list((await session.scalars(select(RewardTaskCampaign).order_by(RewardTaskCampaign.id.desc()).limit(30))).all())
    rows=[]
    for c in campaigns:
        rows.append([InlineKeyboardButton(text=f"{c.title[:26]} • {c.status}",callback_data=f"admin:reward_detail:{c.id}")])
    await edit_or_send(callback.message,"💰 <b>حملات المهام والمكافآت</b>",reply_markup=_nav(rows))


@router.callback_query(F.data.startswith("admin:reward_detail:"))
async def reward_detail(callback:CallbackQuery,session:AsyncSession,settings:Settings)->None:
    await callback.answer()
    if not callback.message or not await require_admin(callback,settings):return
    campaign=await session.get(RewardTaskCampaign,int((callback.data or "").rsplit(":",1)[1]))
    if not campaign:return
    rows=[]
    if campaign.status in {RewardTaskStatus.UNDER_REVIEW.value,RewardTaskStatus.DRAFT.value}:
        rows.append([InlineKeyboardButton(text="✅ اعتماد",callback_data=f"admin:reward_review:{campaign.id}:approve",style="success"),InlineKeyboardButton(text="❌ رفض",callback_data=f"admin:reward_review:{campaign.id}:reject",style="danger")])
    rows.append([InlineKeyboardButton(text="↩️ الحملات",callback_data="admin:reward_campaigns")])
    await edit_or_send(callback.message,f"💰 <b>{safe(campaign.title)}</b>\n\nالمكافأة: {_money(campaign.reward_iqd)}\nالعدد: {campaign.completed_count}/{campaign.capacity_count}\nالميزانية: {_money(campaign.budget_iqd)}\nالحالة: {safe(campaign.status)}",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
