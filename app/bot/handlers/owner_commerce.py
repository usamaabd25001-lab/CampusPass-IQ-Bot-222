from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.states import (
    HybridPurchaseProofStates,
    ProviderAdCampaignStates,
    ProviderCouponCampaignStates,
    ProviderInvoiceProofStates,
    ProviderRewardCampaignStates,
)
from app.bot.ui import edit_or_send
from app.core.config import Settings
from app.core.utils import parse_money, safe
from app.db.models import (
    AdCampaign,
    BusinessInvoice,
    BusinessInvoiceStatus,
    CampaignStatus,
    FeatureFlag,
    HybridBundle,
    HybridBundlePurchase,
    HybridBundleStatus,
    HybridPurchaseStatus,
    Offer,
    Provider,
    ProviderBillingPolicy,
    RewardTaskCampaign,
    RewardTaskCompletion,
    RewardTaskStatus,
    User,
)
from app.services.container import Services
from app.services.platform_access import effective_staff_view, resolve_provider_access

router = Router(name="owner_commerce_public")


def _home_row(callback: str = "provider:dashboard") -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="🔙 رجوع", callback_data=callback), InlineKeyboardButton(text="🏠 الرئيسية", callback_data="back_to_main")]


def _money(value: int | None) -> str:
    return f"{int(value or 0):,} د.ع"


async def _provider_context(
    session: AsyncSession,
    services: Services,
    settings: Settings,
    telegram_id: int,
    *,
    allow_paused: bool = False,
):
    context = await resolve_provider_access(
        session, settings, telegram_id, require_terms=True, allow_paused_provider=allow_paused
    )
    if not context.allowed or context.active_provider is None:
        return None, None, None
    user = await services.users.get_or_create(session, telegram_id, None, "Telegram User")
    staff = await effective_staff_view(session, context)
    return user, staff, context.active_provider


@router.callback_query(F.data == "provider:billing")
async def provider_billing(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    _user, staff, provider_view = await _provider_context(
        session, services, settings, callback.from_user.id, allow_paused=True
    )
    if not staff or not staff.can_view_finance or not provider_view:
        await edit_or_send(callback.message, "لا تملك صلاحية عرض الفواتير.")
        return
    provider_id = int(provider_view.provider_id)
    invoices = list((await session.scalars(
        select(BusinessInvoice).where(BusinessInvoice.provider_id == provider_id)
        .order_by(BusinessInvoice.id.desc()).limit(20)
    )).all())
    rows: list[list[InlineKeyboardButton]] = []
    lines = ["🧾 <b>رسوم البوت وفواتير المنصة</b>", ""]
    if not invoices:
        lines.append("لا توجد فواتير صادرة حالياً ✅")
    for invoice in invoices:
        remaining = max(0, invoice.total_iqd - invoice.paid_iqd)
        lines.append(f"• {safe(invoice.invoice_number)} — {_money(remaining)} — {safe(invoice.status)}")
        if invoice.status != BusinessInvoiceStatus.PAID.value:
            rows.append([InlineKeyboardButton(
                text=f"📤 رفع وصل {invoice.invoice_number}",
                callback_data=f"provider:billing_proof:{invoice.id}", style="success"
            )])
    rows.append(_home_row())
    await edit_or_send(callback.message, "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("provider:billing_proof:"))
async def provider_billing_amount(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    user, staff, provider_view = await _provider_context(
        session, services, settings, callback.from_user.id, allow_paused=True
    )
    if not user or not staff or not staff.can_view_finance or not provider_view:
        return
    invoice_id = int((callback.data or "").rsplit(":", 1)[1])
    invoice = await session.get(BusinessInvoice, invoice_id)
    if not invoice or invoice.provider_id != provider_view.provider_id:
        await edit_or_send(callback.message, "الفاتورة لا تخص منصتك.")
        return
    await state.set_state(ProviderInvoiceProofStates.amount)
    await state.update_data(provider_invoice_id=invoice.id, provider_invoice_provider_id=provider_view.provider_id)
    await edit_or_send(callback.message, f"اكتب المبلغ الذي حولته للفاتورة {safe(invoice.invoice_number)}:")


@router.message(ProviderInvoiceProofStates.amount)
async def provider_billing_amount_save(message: Message, state: FSMContext) -> None:
    try:
        amount = parse_money(message.text or "")
        if amount <= 0:
            raise ValueError
    except Exception:
        await message.answer("اكتب المبلغ بالأرقام، مثل 25000 أو 25 ألف.")
        return
    await state.update_data(provider_invoice_amount=amount)
    await state.set_state(ProviderInvoiceProofStates.proof)
    await message.answer("أرسل الآن صورة الوصل أو ملفه.")


@router.message(ProviderInvoiceProofStates.proof, F.photo | F.document)
async def provider_billing_proof_save(
    message: Message, state: FSMContext, session: AsyncSession, settings: Settings, services: Services
) -> None:
    if not message.from_user:
        return
    user, staff, provider_view = await _provider_context(
        session, services, settings, message.from_user.id, allow_paused=True
    )
    if not user or not staff or not provider_view:
        await state.clear(); return
    data = await state.get_data()
    if int(data.get("provider_invoice_provider_id") or 0) != int(provider_view.provider_id):
        await state.clear(); await message.answer("تغير سياق المنصة. أعد المحاولة."); return
    media = message.photo[-1] if message.photo else message.document
    proof = await services.owner_commerce.submit_invoice_proof(
        session,
        invoice_id=int(data["provider_invoice_id"]),
        provider_id=int(provider_view.provider_id),
        submitted_by_user_id=user.id,
        file_id=media.file_id,
        file_type="photo" if message.photo else "document",
        claimed_amount_iqd=int(data["provider_invoice_amount"]),
        file_unique_id=media.file_unique_id,
    )
    await state.clear()
    await message.answer(f"✅ تم إرسال الوصل للمراجعة. رقم الإثبات: <code>{proof.id}</code>")


@router.callback_query(F.data == "provider:ad_request")
async def provider_ad_menu(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    _user, staff, provider_view = await _provider_context(
        session, services, settings, callback.from_user.id
    )
    if not staff or not staff.can_manage_offers or not provider_view:
        await edit_or_send(callback.message, "لا تملك صلاحية إنشاء إعلان أو أن المنصة معلقة.")
        return
    rows = [
        [InlineKeyboardButton(text="📣 إعلان عام أو موجه", callback_data="provider:ad_kind:broadcast", style="primary")],
        [InlineKeyboardButton(text="📌 إعلان مثبت", callback_data="provider:ad_kind:pinned", style="danger")],
        [InlineKeyboardButton(text="🔗 إعلان مرتبط بعرض", callback_data="provider:ad_kind:offer", style="success")],
        [InlineKeyboardButton(text="🎯 إعلان مهام ومكافآت", callback_data="provider:reward_new", style="success")],
        _home_row(),
    ]
    await edit_or_send(callback.message, "📢 <b>طلب إعلان</b>\n\nاختر نوع الحملة:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("provider:ad_kind:"))
async def provider_ad_kind(callback: CallbackQuery, state: FSMContext, session: AsyncSession, settings: Settings, services: Services) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user: return
    user, staff, provider_view = await _provider_context(session, services, settings, callback.from_user.id)
    if not user or not staff or not staff.can_manage_offers or not provider_view:
        await edit_or_send(callback.message, "لا تملك صلاحية إنشاء إعلان."); return
    kind=(callback.data or "").rsplit(":",1)[1]
    await state.set_state(ProviderAdCampaignStates.title)
    await state.update_data(ad_provider_id=provider_view.provider_id, ad_kind=kind)
    await edit_or_send(callback.message, "اكتب عنوان الإعلان:")


@router.message(ProviderAdCampaignStates.title)
async def provider_ad_title(message: Message, state: FSMContext) -> None:
    title=(message.text or "").strip()
    if len(title)<3: await message.answer("العنوان قصير جداً."); return
    await state.update_data(ad_title=title); await state.set_state(ProviderAdCampaignStates.body); await message.answer("اكتب نص الإعلان:")


@router.message(ProviderAdCampaignStates.body)
async def provider_ad_body(message: Message, state: FSMContext) -> None:
    body=(message.text or "").strip()
    if len(body)<5: await message.answer("النص قصير جداً."); return
    data=await state.get_data(); await state.update_data(ad_body=body)
    if data.get("ad_kind")=="offer":
        await state.set_state(ProviderAdCampaignStates.offer_id); await message.answer("اكتب رقم العرض المرتبط بالإعلان:")
    else:
        await state.set_state(ProviderAdCampaignStates.audience); await message.answer("اختر الجمهور:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="الجميع",callback_data="provider:ad_audience:all")],
            [InlineKeyboardButton(text="عملاء منصتي",callback_data="provider:ad_audience:provider_buyers")],
            [InlineKeyboardButton(text="الأكثر شراءً",callback_data="provider:ad_audience:provider_top_buyers")],
        ]))


@router.message(ProviderAdCampaignStates.offer_id)
async def provider_ad_offer(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not (message.text or "").strip().isdigit(): await message.answer("أدخل رقم العرض."); return
    data=await state.get_data(); offer=await session.get(Offer,int((message.text or "0").strip()))
    if not offer or offer.provider_id!=int(data["ad_provider_id"]): await message.answer("العرض لا يخص منصتك."); return
    await state.update_data(ad_offer_id=offer.id); await state.set_state(ProviderAdCampaignStates.audience)
    await message.answer("اختر الجمهور:",reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="الجميع",callback_data="provider:ad_audience:all")],
        [InlineKeyboardButton(text="عملاء منصتي",callback_data="provider:ad_audience:provider_buyers")],
        [InlineKeyboardButton(text="مفضلو هذا العرض",callback_data="provider:ad_audience:favorite_offer")],
    ]))


@router.callback_query(F.data.startswith("provider:ad_audience:"))
async def provider_ad_audience(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:return
    data=await state.get_data(); kind=(callback.data or "").rsplit(":",1)[1]
    if kind in {"provider_buyers","provider_top_buyers"}: rule={"type":kind,"value":int(data["ad_provider_id"]),"limit":5000}
    elif kind=="favorite_offer": rule={"type":"favorite_offer","value":int(data["ad_offer_id"]),"limit":5000}
    else: rule={"type":"all","limit":5000}
    await state.update_data(ad_audience=rule); await state.set_state(ProviderAdCampaignStates.duration_hours)
    await edit_or_send(callback.message,"اكتب مدة الإعلان بالساعات، من 1 إلى 2160:")


@router.message(ProviderAdCampaignStates.duration_hours)
async def provider_ad_duration(message: Message, state: FSMContext, session: AsyncSession, settings: Settings, services: Services) -> None:
    if not message.from_user or not (message.text or "").strip().isdigit(): await message.answer("أدخل عدد ساعات صحيحاً."); return
    hours=int((message.text or "0").strip()); data=await state.get_data()
    user, staff, provider_view=await _provider_context(session,services,settings,message.from_user.id)
    if not user or not staff or not provider_view or provider_view.provider_id!=int(data["ad_provider_id"]): await state.clear();return
    policy=await session.scalar(select(ProviderBillingPolicy).where(ProviderBillingPolicy.provider_id==provider_view.provider_id))
    rate=policy.ad_hourly_rate_iqd if policy else 1000
    try:
        campaign=await services.owner_commerce.create_ad_campaign(
            session,provider_id=provider_view.provider_id,requested_by_user_id=user.id,
            campaign_type=str(data["ad_kind"]),title=str(data["ad_title"]),body=str(data["ad_body"]),
            duration_hours=hours,hourly_rate_iqd=rate,audience_rule=dict(data["ad_audience"]),
            offer_id=data.get("ad_offer_id"),idempotency_key=f"ad:{provider_view.provider_id}:{message.message_id}")
    except ValueError as exc: await message.answer(str(exc));return
    await state.update_data(ad_campaign_id=campaign.id);await state.set_state(ProviderAdCampaignStates.proof)
    await message.answer(f"🧾 تكلفة الحملة: <b>{_money(campaign.total_iqd)}</b>\nارفع وصل الدفع الآن.")


@router.message(ProviderAdCampaignStates.proof, F.photo | F.document)
async def provider_ad_proof(
    message: Message, state: FSMContext, session: AsyncSession, settings: Settings, services: Services
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    user, staff, provider_view = await _provider_context(
        session, services, settings, message.from_user.id
    )
    if (
        not user
        or not staff
        or not staff.can_manage_offers
        or not provider_view
        or int(data.get("ad_provider_id") or 0) != int(provider_view.provider_id)
    ):
        await state.clear()
        await message.answer("تغير سياق المنصة أو لا تملك الصلاحية.")
        return
    media = message.photo[-1] if message.photo else message.document
    campaign = await services.owner_commerce.submit_ad_proof(
        session, campaign_id=int(data["ad_campaign_id"]),
        provider_id=int(provider_view.provider_id), submitted_by_user_id=user.id,
        file_id=media.file_id, file_unique_id=media.file_unique_id
    )
    await state.clear()
    await message.answer(f"✅ تم إرسال الحملة للمراجعة. رقمها <code>{campaign.public_id}</code>.")


@router.callback_query(F.data == "provider:coupon_campaign")
async def provider_coupon_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession, settings: Settings, services: Services) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:return
    user,staff,provider_view=await _provider_context(session,services,settings,callback.from_user.id)
    if not user or not staff or not staff.can_manage_offers or not provider_view:return
    await state.set_state(ProviderCouponCampaignStates.audience);await state.update_data(pc_provider_id=provider_view.provider_id)
    await edit_or_send(callback.message,"اختر شريحة الطلاب:",reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="كل عملاء منصتي",callback_data="provider:coupon_audience:provider_buyers")],
        [InlineKeyboardButton(text="الأكثر شراءً",callback_data="provider:coupon_audience:provider_top_buyers")],
        [InlineKeyboardButton(text="طلاب الطب",callback_data="provider:coupon_audience:college:طب")],
        [InlineKeyboardButton(text="طلاب الهندسة",callback_data="provider:coupon_audience:college:هندسة")],
        _home_row(),
    ]))


@router.callback_query(F.data.startswith("provider:coupon_audience:"))
async def provider_coupon_audience(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:return
    data=await state.get_data();tail=(callback.data or "").split(":")[2:]
    if tail[0] in {"provider_buyers","provider_top_buyers"}:rule={"type":tail[0],"value":int(data["pc_provider_id"]),"limit":5000}
    else:rule={"type":"college","value":tail[1],"limit":5000}
    await state.update_data(pc_audience=rule);await state.set_state(ProviderCouponCampaignStates.code);await edit_or_send(callback.message,"اكتب كود الخصم:")


@router.message(ProviderCouponCampaignStates.code)
async def provider_coupon_code(message: Message, state: FSMContext) -> None:
    await state.update_data(pc_code=(message.text or "").strip().upper());await state.set_state(ProviderCouponCampaignStates.kind);await message.answer("اكتب percent أو fixed:")
@router.message(ProviderCouponCampaignStates.kind)
async def provider_coupon_kind(message: Message, state: FSMContext) -> None:
    kind=(message.text or "").strip().lower()
    if kind not in {"percent","fixed"}:await message.answer("اكتب percent أو fixed فقط.");return
    await state.update_data(pc_kind=kind);await state.set_state(ProviderCouponCampaignStates.value);await message.answer("اكتب قيمة الخصم:")
@router.message(ProviderCouponCampaignStates.value)
async def provider_coupon_value(message: Message,state:FSMContext,session:AsyncSession,settings:Settings,services:Services)->None:
    if not message.from_user:return
    data=await state.get_data();user,staff,provider_view=await _provider_context(session,services,settings,message.from_user.id)
    if not user or not staff or not provider_view or int(data["pc_provider_id"])!=provider_view.provider_id:return
    try:
        value = (
            int((message.text or "0").strip())
            if data["pc_kind"] == "percent"
            else parse_money(message.text or "")
        )
        campaign = await services.owner_commerce.create_coupon_campaign(
            session, code=data["pc_code"], coupon_type=data["pc_kind"],
            value_int=value, provider_id=provider_view.provider_id,
            created_by_user_id=user.id, audience_rule=data["pc_audience"]
        )
    except (ValueError, TypeError) as exc:
        await message.answer(str(exc) or "قيمة الخصم غير صحيحة.")
        return
    await state.clear();await message.answer(f"✅ وُزع الكود على {campaign.assigned_count} طالب.")


@router.callback_query(F.data == "provider:reward_new")
async def provider_reward_start(callback:CallbackQuery,state:FSMContext,session:AsyncSession,settings:Settings,services:Services)->None:
    await callback.answer()
    if not callback.message or not callback.from_user:return
    user,staff,provider_view=await _provider_context(session,services,settings,callback.from_user.id)
    if not user or not staff or not staff.can_manage_offers or not provider_view:return
    await state.set_state(ProviderRewardCampaignStates.title);await state.update_data(rt_provider_id=provider_view.provider_id);await edit_or_send(callback.message,"اكتب عنوان المهمة:")
@router.message(ProviderRewardCampaignStates.title)
async def rt_title(message:Message,state:FSMContext)->None:
    await state.update_data(rt_title=(message.text or "").strip());await state.set_state(ProviderRewardCampaignStates.channel_chat_id);await message.answer("اكتب رقم القناة Chat ID، مثل -1001234567890:")
@router.message(ProviderRewardCampaignStates.channel_chat_id)
async def rt_chat(message:Message,state:FSMContext)->None:
    try:chat_id=int((message.text or "").strip())
    except ValueError:await message.answer("رقم القناة غير صحيح.");return
    await state.update_data(rt_chat_id=chat_id);await state.set_state(ProviderRewardCampaignStates.channel_url);await message.answer("أرسل رابط القناة:")
@router.message(ProviderRewardCampaignStates.channel_url)
async def rt_url(message:Message,state:FSMContext)->None:
    url=(message.text or "").strip()
    if not url.startswith("https://t.me/"):await message.answer("يجب أن يكون رابط Telegram صالحاً.");return
    await state.update_data(rt_url=url);await state.set_state(ProviderRewardCampaignStates.reward_iqd);await message.answer("اكتب مكافأة كل طالب بالدينار:")
@router.message(ProviderRewardCampaignStates.reward_iqd)
async def rt_reward(message:Message,state:FSMContext)->None:
    try:value=parse_money(message.text or "")
    except Exception:await message.answer("مبلغ غير صحيح.");return
    await state.update_data(rt_reward=value);await state.set_state(ProviderRewardCampaignStates.requested_count);await message.answer("كم طالباً تريد؟")
@router.message(ProviderRewardCampaignStates.requested_count)
async def rt_count(message:Message,state:FSMContext)->None:
    if not (message.text or "").strip().isdigit():await message.answer("أدخل عدداً صحيحاً.");return
    count=int((message.text or "0").strip());data=await state.get_data();budget=count*int(data["rt_reward"])
    await state.update_data(rt_count=count,rt_budget=budget);await state.set_state(ProviderRewardCampaignStates.budget_iqd);await message.answer(f"الميزانية المحسوبة {_money(budget)}. أرسل نعم لاعتمادها أو اكتب ميزانية أعلى:")
@router.message(ProviderRewardCampaignStates.budget_iqd)
async def rt_budget(message:Message,state:FSMContext,session:AsyncSession,settings:Settings,services:Services)->None:
    if not message.from_user:return
    data = await state.get_data()
    raw = (message.text or "").strip().lower()
    try:
        budget = int(data["rt_budget"]) if raw in {"نعم", "yes", "y"} else parse_money(raw)
    except Exception:
        await message.answer("الميزانية غير صحيحة.")
        return
    user, staff, provider_view = await _provider_context(
        session, services, settings, message.from_user.id
    )
    if (
        not user or not staff or not staff.can_manage_offers or not provider_view
        or int(data.get("rt_provider_id") or 0) != int(provider_view.provider_id)
    ):
        await state.clear()
        return
    try:campaign=await services.owner_commerce.create_reward_campaign(session,provider_id=provider_view.provider_id,requested_by_user_id=user.id,title=data["rt_title"],channel_chat_id=int(data["rt_chat_id"]),channel_url=data["rt_url"],reward_iqd=int(data["rt_reward"]),requested_count=int(data["rt_count"]),budget_iqd=budget,idempotency_key=f"reward:{provider_view.provider_id}:{message.message_id}")
    except ValueError as exc:await message.answer(str(exc));return
    await state.update_data(rt_campaign_id=campaign.id);await state.set_state(ProviderRewardCampaignStates.proof);await message.answer(f"ارفع وصل تمويل الحملة بقيمة {_money(budget)}.")
@router.message(ProviderRewardCampaignStates.proof,F.photo|F.document)
async def rt_proof(message:Message,state:FSMContext,session:AsyncSession,settings:Settings,services:Services)->None:
    if not message.from_user:return
    data=await state.get_data();user,staff,provider_view=await _provider_context(session,services,settings,message.from_user.id)
    if (
        not user or not staff or not staff.can_manage_offers or not provider_view
        or int(data.get("rt_provider_id") or 0) != int(provider_view.provider_id)
    ):
        await state.clear()
        return
    media=message.photo[-1] if message.photo else message.document
    campaign=await services.owner_commerce.submit_reward_campaign_proof(session,campaign_id=int(data["rt_campaign_id"]),provider_id=provider_view.provider_id,file_id=media.file_id,file_unique_id=media.file_unique_id)
    await state.clear();await message.answer(f"✅ تم إرسال حملة المهام للمراجعة: {campaign.public_id}")


@router.callback_query(F.data == "reward:tasks")
async def reward_tasks(callback:CallbackQuery,session:AsyncSession,services:Services)->None:
    await callback.answer()
    if not callback.message or not callback.from_user:return
    if not await services.features.enabled(session,"reward_tasks",default=False):
        await edit_or_send(callback.message,"نظام المهام والمكافآت غير متاح حالياً.");return
    user=await services.users.get_or_create(session,callback.from_user.id,callback.from_user.username,callback.from_user.full_name or "Telegram User")
    completed=set((await session.scalars(select(RewardTaskCompletion.campaign_id).where(RewardTaskCompletion.user_id==user.id))).all())
    campaigns=list((await session.scalars(select(RewardTaskCampaign).where(RewardTaskCampaign.status==RewardTaskStatus.ACTIVE.value).order_by(RewardTaskCampaign.id))).all())
    rows=[]
    for c in campaigns:
        if c.id in completed:continue
        rows.append([InlineKeyboardButton(text=f"💰 {_money(c.reward_iqd)} • {c.title[:25]}",callback_data=f"reward:task:{c.id}",style="success")])
    rows.append(_home_row("back_to_main"))
    await edit_or_send(callback.message,"💰 <b>اكسب رصيداً مجانياً</b>\n\nنفذ مهمة موثوقة ثم تحقق منها:",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("reward:task:"))
async def reward_task_detail(callback:CallbackQuery,session:AsyncSession,services:Services)->None:
    await callback.answer()
    if not callback.message:return
    if not await services.features.enabled(session,"reward_tasks",default=False):
        await edit_or_send(callback.message,"نظام المهام والمكافآت غير متاح حالياً.")
        return
    campaign=await session.get(RewardTaskCampaign,int((callback.data or "").rsplit(":",1)[1]))
    if not campaign or campaign.status!=RewardTaskStatus.ACTIVE.value:return
    await edit_or_send(callback.message,f"💰 <b>{safe(campaign.title)}</b>\n\nالمكافأة: <b>{_money(campaign.reward_iqd)}</b>\nاشترك في القناة ثم اضغط التحقق.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="فتح القناة",url=campaign.channel_url,style="primary")],
        [InlineKeyboardButton(text="✅ تحقق من اشتراكي",callback_data=f"reward:verify:{campaign.id}",style="success")],
        _home_row("reward:tasks"),
    ]))


@router.callback_query(F.data.startswith("reward:verify:"))
async def reward_verify(callback:CallbackQuery,session:AsyncSession,services:Services)->None:
    await callback.answer("جاري التحقق...")
    if not callback.message or not callback.from_user:return
    if not await services.features.enabled(session,"reward_tasks",default=False):
        await callback.answer("نظام المهام غير متاح حالياً.",show_alert=True)
        return
    campaign=await session.get(RewardTaskCampaign,int((callback.data or "").rsplit(":",1)[1]))
    if not campaign or campaign.status != RewardTaskStatus.ACTIVE.value:return
    try:
        member=await callback.bot.get_chat_member(campaign.channel_chat_id,callback.from_user.id)
        member_status = getattr(member.status, "value", str(member.status))
        verified=member_status in {"member","administrator","creator"}
    except Exception:
        await callback.answer("تعذر التحقق. تأكد أن البوت مشرف في القناة.",show_alert=True);return
    user=await services.users.get_or_create(session,callback.from_user.id,callback.from_user.username,callback.from_user.full_name or "Telegram User")
    try:completion=await services.owner_commerce.reward_verified_student(session,campaign_id=campaign.id,user_id=user.id,verified=verified)
    except ValueError as exc:await callback.answer(str(exc),show_alert=True);return
    await edit_or_send(callback.message,f"✅ تم التحقق وإضافة <b>{_money(campaign.reward_iqd)}</b> إلى محفظتك.\nرقم العملية: <code>{completion.id}</code>")


@router.callback_query(F.data == "hybrid:list")
async def hybrid_list(callback:CallbackQuery,session:AsyncSession)->None:
    await callback.answer()
    if not callback.message:return
    bundles=list((await session.scalars(select(HybridBundle).where(HybridBundle.status==HybridBundleStatus.ACTIVE.value).order_by(HybridBundle.id.desc()))).all())
    rows=[[InlineKeyboardButton(text=f"📦 {b.title[:28]} — {_money(b.price_iqd)}",callback_data=f"hybrid:view:{b.id}",style="success")] for b in bundles]
    rows.append(_home_row("back_to_main"));await edit_or_send(callback.message,"📦 <b>الباقات المدمجة والهجينة</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("hybrid:view:"))
async def hybrid_view(callback:CallbackQuery,session:AsyncSession)->None:
    await callback.answer()
    if not callback.message:return
    b=await session.get(HybridBundle,int((callback.data or "").rsplit(":",1)[1]))
    if not b or b.status!=HybridBundleStatus.ACTIVE.value:return
    await edit_or_send(callback.message,f"📦 <b>{safe(b.title)}</b>\n\n{safe(b.description)}\n\nالسعر الإجمالي: <b>{_money(b.price_iqd)}</b>\nرسوم البوت ضمن السعر: <b>{_money(b.bot_fee_iqd)}</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 شراء الباقة",callback_data=f"hybrid:buy:{b.id}",style="success")],_home_row("hybrid:list")]))


@router.callback_query(F.data.startswith("hybrid:buy:"))
async def hybrid_buy(callback:CallbackQuery,state:FSMContext,session:AsyncSession,services:Services)->None:
    await callback.answer()
    if not callback.message or not callback.from_user:return
    user=await services.users.get_or_create(session,callback.from_user.id,callback.from_user.username,callback.from_user.full_name or "Telegram User")
    purchase=await services.owner_commerce.create_hybrid_purchase(session,bundle_id=int((callback.data or "").rsplit(":",1)[1]),user_id=user.id,idempotency_key=f"hybrid-buy:{user.id}:{callback.id}")
    await state.set_state(HybridPurchaseProofStates.amount);await state.update_data(hybrid_purchase_id=purchase.id)
    await edit_or_send(callback.message,f"🧾 قيمة الباقة: <b>{_money(purchase.total_iqd)}</b>\n\nحوّل المبلغ وفق تعليمات الدفع الرسمية ثم اكتب المبلغ الذي حولته.")


@router.message(HybridPurchaseProofStates.amount)
async def hybrid_amount(message:Message,state:FSMContext)->None:
    try:amount=parse_money(message.text or "")
    except Exception:await message.answer("مبلغ غير صحيح.");return
    await state.update_data(hybrid_amount=amount);await state.set_state(HybridPurchaseProofStates.proof);await message.answer("أرسل صورة أو ملف وصل الدفع.")
@router.message(HybridPurchaseProofStates.proof,F.photo|F.document)
async def hybrid_proof(message:Message,state:FSMContext,session:AsyncSession,services:Services)->None:
    if not message.from_user:return
    data=await state.get_data();user=await services.users.get_or_create(session,message.from_user.id,message.from_user.username,message.from_user.full_name or "Telegram User");media=message.photo[-1] if message.photo else message.document
    try:proof=await services.owner_commerce.submit_hybrid_purchase_proof(session,purchase_id=int(data["hybrid_purchase_id"]),user_id=user.id,file_id=media.file_id,file_type="photo" if message.photo else "document",file_unique_id=media.file_unique_id,claimed_amount_iqd=int(data["hybrid_amount"]))
    except ValueError as exc:await message.answer(str(exc));return
    await state.clear();await message.answer(f"✅ تم إرسال الوصل للمراجعة. رقم الإثبات <code>{proof.id}</code>.")
