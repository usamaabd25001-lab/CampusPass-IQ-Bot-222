from __future__ import annotations

import asyncio
import json

from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin.common import admin_actor, admin_back, require_admin
from app.bot.states import AdminOrderCouponStates, AdminPlatformCollectionStates, AdminWithdrawalStates
from app.bot.ui import edit_or_send, callback_notice
from app.core.config import Settings
from app.core.utils import parse_money, safe
from app.db.models import (
    LedgerEntry,
    Offer,
    OfferStatus,
    Order,
    OrderCoupon,
    OrderCouponType,
    OrderEvent,
    OrderStatus,
    Provider,
    ProviderSettlement,
    ProviderStaff,
    ProviderStatus,
    SettlementStatus,
    SystemSetting,
    User,
    WithdrawalRequest,
    WithdrawalStatus,
)
from app.services.container import Services
from app.services.platform_access import mark_platform_authorization_dirty

router = Router(name="admin_finance")


@router.callback_query(F.data == "admin:finance")
async def finance_overview(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    owner_revenue = int(
        await session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount_iqd), 0)).where(
                LedgerEntry.account_code == "owner_revenue",
                LedgerEntry.direction == "credit",
                LedgerEntry.status == "posted",
            )
        )
        or 0
    )
    provider_payable = int(
        await session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount_iqd), 0)).where(
                LedgerEntry.account_code == "provider_payable",
                LedgerEntry.direction == "credit",
                LedgerEntry.status == "posted",
            )
        )
        or 0
    )
    owner_refunds = int(
        await session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount_iqd), 0)).where(
                LedgerEntry.account_code == "owner_revenue_refund",
                LedgerEntry.direction == "debit",
                LedgerEntry.status == "posted",
            )
        )
        or 0
    )
    provider_refunds = int(
        await session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount_iqd), 0)).where(
                LedgerEntry.account_code == "provider_payable_refund",
                LedgerEntry.direction == "debit",
                LedgerEntry.status == "posted",
            )
        )
        or 0
    )
    withdrawals = int(
        await session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount_iqd), 0)).where(
                LedgerEntry.account_code == "provider_withdrawal",
                LedgerEntry.direction == "debit",
                LedgerEntry.status == "posted",
            )
        )
        or 0
    )
    pending = int(
        await session.scalar(
            select(func.count())
            .select_from(WithdrawalRequest)
            .where(WithdrawalRequest.status == WithdrawalStatus.PENDING.value)
        )
        or 0
    )
    owner_collected = int(
        await session.scalar(
            select(func.coalesce(func.sum(ProviderSettlement.owner_due_iqd), 0)).where(
                ProviderSettlement.status == SettlementStatus.CONFIRMED.value
            )
        ) or 0
    )
    owner_pending_collection = int(
        await session.scalar(
            select(func.coalesce(func.sum(ProviderSettlement.remaining_due_iqd), 0)).where(
                ProviderSettlement.status.in_([
                    SettlementStatus.OPEN.value,
                    SettlementStatus.NOTIFIED.value,
                    SettlementStatus.PROOF_RECEIVED.value,
                    SettlementStatus.UNDER_REVIEW.value,
                    SettlementStatus.REJECTED.value,
                ])
            )
        ) or 0
    )
    rows = [
        [
            InlineKeyboardButton(
                text="💳 تحصيل رسوم البوت من منصة",
                callback_data="admin:collections",
                style="primary",
            )
        ],
        [
            InlineKeyboardButton(
                text="🎟 أكواد خصم الطلبات",
                callback_data="admin:order_coupons",
                style="success",
            )
        ],
    ]
    if settings.provider_withdrawals_ready:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🏦 طلبات السحب",
                    callback_data="admin:withdrawals",
                    style="success",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")])
    await edit_or_send(callback.message, 
        "💰 <b>المالية</b>\n\n"
        f"إيراد الإدارة الإجمالي: <b>{owner_revenue:,} د.ع</b>\n"
        f"عكس استرجاعات الإدارة: <b>{owner_refunds:,} د.ع</b>\n"
        f"صافي إيراد الإدارة (رسوم CampusPass المستحقة): <b>{max(0, owner_revenue - owner_refunds):,} د.ع</b>\n"
        f"تم تحصيله من المنصات: <b>{owner_collected:,} د.ع</b>\n"
        f"قيد التحصيل/المراجعة: <b>{owner_pending_collection:,} د.ع</b>\n\n"
        f"مستحقات المنصات الإجمالية: <b>{provider_payable:,} د.ع</b>\n"
        f"عكس استرجاعات المنصات: <b>{provider_refunds:,} د.ع</b>\n"
        f"السحوبات المدفوعة: <b>{withdrawals:,} د.ع</b>\n"
        f"الصافي المتبقي: <b>{max(0, provider_payable - provider_refunds - withdrawals):,} د.ع</b>\n"
        f"طلبات سحب تنتظر المراجعة: <b>{pending}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data == "admin:withdrawals")
async def withdrawals_list(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    requests = list(
        (
            await session.scalars(
                select(WithdrawalRequest).order_by(WithdrawalRequest.created_at.desc()).limit(40)
            )
        ).all()
    )
    rows = []
    for request in requests:
        style = "danger" if request.status == WithdrawalStatus.PENDING.value else "primary"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{request.public_id} — {request.amount_iqd:,} — {request.status}",
                    callback_data=f"admin:withdrawal:{request.id}",
                    style=style,
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="↩️ المالية", callback_data="admin:finance")])
    await edit_or_send(callback.message, 
        "🏦 <b>طلبات السحب</b>" if requests else "لا توجد طلبات سحب.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.regexp(r"^admin:withdrawal:\d+$"))
async def withdrawal_details(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    request = await session.get(WithdrawalRequest, int(callback.data.split(":")[2]))
    if not request:
        return
    provider = await session.get(Provider, request.provider_id)
    rows = []
    if request.status in {WithdrawalStatus.PENDING.value, WithdrawalStatus.APPROVED.value}:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        text="✅ تم التحويل وإرفاق الإثبات",
                        callback_data=f"admin:withdrawal_pay:{request.id}",
                        style="success",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ رفض",
                        callback_data=f"admin:withdrawal_reject:{request.id}",
                        style="danger",
                    )
                ],
            ]
        )
    rows.append([InlineKeyboardButton(text="↩️ السحوبات", callback_data="admin:withdrawals")])
    await edit_or_send(callback.message, 
        f"🏦 <b>{request.public_id}</b>\n"
        f"المنصة: {safe(provider.name_ar if provider else request.provider_id)}\n"
        f"المبلغ: <b>{request.amount_iqd:,} د.ع</b>\n"
        f"الطريقة: {safe(request.method)}\n"
        f"الحساب: <code>{safe(request.destination)}</code>\n"
        f"الحالة: {request.status}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("admin:withdrawal_pay:"))
async def withdrawal_pay_start(
    callback: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.update_data(withdrawal_pay_id=int(callback.data.split(":")[2]))
    await state.set_state(AdminWithdrawalStates.proof)
    await edit_or_send(callback.message, "أرسل صورة أو ملف إثبات التحويل:")


@router.message(AdminWithdrawalStates.proof)
async def withdrawal_pay_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    file_id = (
        message.photo[-1].file_id
        if message.photo
        else (message.document.file_id if message.document else None)
    )
    if not file_id:
        return await message.answer("أرسل صورة أو ملف إثبات.")
    data = await state.get_data()
    request = await session.get(WithdrawalRequest, int(data["withdrawal_pay_id"]))
    actor = await admin_actor(session, services, message)
    if not request or not actor:
        await state.clear()
        return
    await services.finance.mark_withdrawal_paid(session, request, actor, file_id)
    await state.clear()
    await message.answer("تم تسجيل السحب وإثباته في الدفتر المالي ✅", reply_markup=admin_back())


@router.callback_query(F.data.startswith("admin:withdrawal_reject:"))
async def withdrawal_reject(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings):
        return
    request = await session.get(WithdrawalRequest, int(callback.data.split(":")[2]))
    if request and request.status != WithdrawalStatus.PAID.value:
        request.status = WithdrawalStatus.REJECTED.value
        request.processed_at = datetime.now(UTC)
        request.note = "رفضه مالك النظام"
    await callback_notice(callback, "تم الرفض", show_alert=True)


@router.callback_query(F.data == "admin:reports")
async def reports_home(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    providers = list(
        (
            await session.scalars(
                select(Provider).where(Provider.is_active.is_(True)).order_by(Provider.name_ar)
            )
        ).all()
    )
    rows = [
        [
            InlineKeyboardButton(
                text=f"📊 {p.name_ar} — {p.report_plan}",
                callback_data=f"admin:report_provider:{p.id}",
                style="primary",
            )
        ]
        for p in providers
    ]
    rows.append([InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")])
    await edit_or_send(callback.message, 
        "اختر المنصة لإنشاء تقرير آخر 30 يومًا:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("admin:report_provider:"), flags={"processing_immediate": True, "report": True})
async def report_create(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    provider = await session.get(Provider, int(callback.data.split(":")[2]))
    actor = await admin_actor(session, services, callback)
    if not provider:
        return
    end = datetime.now(UTC)
    start = end - timedelta(days=30)
    try:
        report, token = await services.reports.create_provider_report(
            session, provider, start, end, actor.id if actor else None
        )
    except ValueError as exc:
        return await edit_or_send(callback.message, str(exc))
    url = services.reports.report_url(token)
    if not settings.public_base_url:
        rendered = await asyncio.to_thread(
            services.reports.render, report, ""
        )
        await callback.message.answer_document(
            BufferedInputFile(
                rendered.encode("utf-8"),
                filename=services.reports.filename(report, "html"),
            ),
            caption=f"تم إنشاء التقرير #{report.id} ✅\nملف HTML جاهز للفتح والطباعة.",
        )
        csv_text = await asyncio.to_thread(services.reports.export_csv, report)
        await callback.message.answer_document(
            BufferedInputFile(
                csv_text.encode("utf-8-sig"),
                filename=services.reports.filename(report, "csv"),
            ),
            caption="نسخة CSV للإدارة.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ التقارير", callback_data="admin:reports")]
                ]
            ),
        )
        return
    await edit_or_send(callback.message, 
        f"تم إنشاء التقرير #{report.id} ✅",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🌐 فتح التقرير", url=url, style="primary")],
                [
                    InlineKeyboardButton(
                        text="⬇️ HTML", url=services.reports.report_download_url(token, "html")
                    ),
                    InlineKeyboardButton(
                        text="⬇️ CSV", url=services.reports.report_download_url(token, "csv")
                    ),
                ],
                [InlineKeyboardButton(text="↩️ التقارير", callback_data="admin:reports")],
            ]
        ),
    )


# ---------------------------------------------------------------------------
# V8.1 owner -> provider fee collection. Provider sales remain provider-direct.
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:collections")
async def collections_home(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    providers = list((await session.scalars(select(Provider).order_by(Provider.name_ar))).all())
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅' if p.status == ProviderStatus.ACTIVE.value and p.is_active else '⛔'} {p.name_ar}",
                callback_data=f"admin:collect_provider:{p.id}",
                style="primary" if p.is_active else "danger",
            )
        ]
        for p in providers
    ]
    rows.append([InlineKeyboardButton(text="📑 طلبات التحصيل", callback_data="admin:collections:list")])
    rows.append([InlineKeyboardButton(text="↩️ المالية", callback_data="admin:finance")])
    await edit_or_send(callback.message, 
        "💳 <b>تحصيل رسوم CampusPass</b>\n\nاختر المنصة ثم أدخل المبلغ المطلوب منها. "
        "هذا النظام لا يسحب أموال مبيعات المنصة؛ يسجل فقط رسوم البوت/الإدارة المستحقة.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.regexp(r"^admin:collect_provider:\d+$"))
async def collection_amount_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    provider_id = int(callback.data.rsplit(":", 1)[1])
    provider = await session.get(Provider, provider_id)
    if not provider:
        return await edit_or_send(callback.message, "المنصة غير موجودة.")
    await state.clear()
    await state.update_data(collection_provider_id=provider_id)
    await state.set_state(AdminPlatformCollectionStates.amount)
    await edit_or_send(callback.message, 
        f"المنصة: <b>{safe(provider.name_ar)}</b>\n"
        "اكتب مبلغ رسوم البوت المطلوب تحصيله بالدينار العراقي. مثال: <code>25000</code>"
    )


@router.message(AdminPlatformCollectionStates.amount)
async def collection_amount_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    try:
        amount = parse_money(message.text or "")
    except Exception:
        return await message.answer("اكتب المبلغ بالأرقام فقط. مثال: <code>25000</code>")
    if amount is None or amount <= 0 or amount > 100_000_000:
        return await message.answer("المبلغ غير صالح.")
    data = await state.get_data()
    provider = await session.get(Provider, int(data.get("collection_provider_id", 0)))
    if not provider:
        await state.clear()
        return await message.answer("المنصة غير موجودة.")
    earned = int(
        await session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount_iqd), 0)).where(
                LedgerEntry.provider_id == provider.id,
                LedgerEntry.account_code == "owner_revenue",
                LedgerEntry.direction == "credit",
                LedgerEntry.status == "posted",
            )
        ) or 0
    )
    reversed_amount = int(
        await session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount_iqd), 0)).where(
                LedgerEntry.provider_id == provider.id,
                LedgerEntry.account_code == "owner_revenue_refund",
                LedgerEntry.direction == "debit",
                LedgerEntry.status == "posted",
            )
        ) or 0
    )
    reserved = int(
        await session.scalar(
            select(func.coalesce(func.sum(ProviderSettlement.owner_due_iqd), 0)).where(
                ProviderSettlement.provider_id == provider.id,
                ProviderSettlement.status.notin_([
                    SettlementStatus.REJECTED.value,
                    SettlementStatus.WAIVED.value,
                ]),
            )
        ) or 0
    )
    available = max(0, earned - reversed_amount - reserved)
    if amount > available:
        return await message.answer(
            f"لا يمكن طلب أكثر من رسوم البوت المستحقة فعليًا لهذه المنصة.\n"
            f"المتاح للتحصيل الآن: <b>{available:,} د.ع</b>"
        )
    settlement = await services.settlements.create_manual_due(session, provider.id, amount)
    actor = await admin_actor(session, services, message)
    await services.audit.log(
        session,
        actor,
        "provider.collection.created",
        "provider_settlement",
        str(settlement.id),
        {"provider_id": provider.id, "amount_iqd": amount},
    )
    recipients = list((await session.scalars(
        select(User).join(ProviderStaff, ProviderStaff.user_id == User.id).where(
            ProviderStaff.provider_id == provider.id,
            ProviderStaff.is_active.is_(True),
            or_(
                ProviderStaff.can_view_finance.is_(True),
                ProviderStaff.role == "OWNER",
                func.lower(ProviderStaff.title).in_(
                    ("owner", "platform_owner", "provider_owner", "مالك")
                ),
            ),
        )
    )).all())
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="💳 إرسال وصل MasterCard",
            callback_data=f"provider:settlement:{settlement.id}",
            style="primary",
        )
    ]])
    for recipient in recipients:
        await services.notifications.send_user(
            session,
            recipient,
            "مطلوب تسديد رسوم CampusPass",
            f"المنصة: {provider.name_ar}\n"
            f"المعرف: {provider.id}\n"
            f"المبلغ المطلوب: {amount:,} د.ع\n\n"
            "للاستمرار بخدمات البوت أرسل إثبات تحويل MasterCard فقط من الزر أدناه.",
            reply_markup=markup,
            idempotency_key=f"settlement:{settlement.id}:notify:{recipient.id}",
        )
    await state.clear()
    await message.answer(
        f"✅ تم إنشاء طلب التحصيل <code>{settlement.public_id}</code> بمبلغ <b>{amount:,} د.ع</b> "
        f"وإرساله إلى {len(recipients)} حساب مخول ماليًا.",
        reply_markup=admin_back(),
    )


@router.callback_query(F.data == "admin:collections:list")
async def collections_list(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    items = list((await session.scalars(
        select(ProviderSettlement).order_by(ProviderSettlement.created_at.desc()).limit(50)
    )).all())
    rows = [
        [InlineKeyboardButton(
            text=f"{x.public_id} — {x.remaining_due_iqd:,} — {x.status}",
            callback_data=f"admin:collection:{x.id}",
            style="danger" if x.status in {SettlementStatus.NOTIFIED.value, SettlementStatus.PROOF_RECEIVED.value, SettlementStatus.REJECTED.value} else "success",
        )]
        for x in items
    ]
    rows.append([InlineKeyboardButton(text="↩️ التحصيل", callback_data="admin:collections")])
    await edit_or_send(callback.message, 
        "📑 <b>طلبات التحصيل</b>" if items else "لا توجد طلبات تحصيل حتى الآن.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.regexp(r"^admin:collection:\d+$"))
async def collection_details(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    settlement = await session.get(ProviderSettlement, int(callback.data.rsplit(":", 1)[1]))
    if not settlement:
        return await edit_or_send(callback.message, "طلب التحصيل غير موجود.")
    provider = await session.get(Provider, settlement.provider_id)
    rows = []
    if settlement.proof_file_id and settlement.status != SettlementStatus.CONFIRMED.value:
        rows.extend([
            [InlineKeyboardButton(text="✅ تأكيد الدفع", callback_data=f"admin:collection_approve:{settlement.id}", style="success")],
            [InlineKeyboardButton(text="❌ رفض الوصل", callback_data=f"admin:collection_reject:{settlement.id}", style="danger")],
        ])
    if provider and provider.status != ProviderStatus.SUSPENDED.value:
        rows.append([InlineKeyboardButton(text="🚫 حظر المنصة", callback_data=f"admin:collection_ban:{settlement.id}", style="danger")])
    rows.append([InlineKeyboardButton(text="↩️ الطلبات", callback_data="admin:collections:list")])
    text = (
        f"💳 <b>{settlement.public_id}</b>\n"
        f"المنصة: {safe(provider.name_ar if provider else settlement.provider_id)}\n"
        f"المطلوب: <b>{settlement.owner_due_iqd:,} د.ع</b>\n"
        f"المتبقي: <b>{settlement.remaining_due_iqd:,} د.ع</b>\n"
        f"الحالة: <code>{settlement.status}</code>"
    )
    if settlement.proof_file_id:
        try:
            await callback.message.answer_photo(
                settlement.proof_file_id,
                caption=text + "\n\nوصل MasterCard المرسل من المنصة.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            )
            return
        except Exception:
            pass
    await edit_or_send(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def _notify_provider_finance(
    session: AsyncSession, services: Services, provider_id: int, title: str, body: str, key: str
) -> None:
    recipients = list((await session.scalars(
        select(User).join(ProviderStaff, ProviderStaff.user_id == User.id).where(
            ProviderStaff.provider_id == provider_id,
            ProviderStaff.is_active.is_(True),
            or_(
                ProviderStaff.can_view_finance.is_(True),
                ProviderStaff.role == "OWNER",
                func.lower(ProviderStaff.title).in_(
                    ("owner", "platform_owner", "provider_owner", "مالك")
                ),
            ),
        )
    )).all())
    for recipient in recipients:
        await services.notifications.send_user(
            session, recipient, title, body, idempotency_key=f"{key}:{recipient.id}"
        )


@router.callback_query(F.data.regexp(r"^admin:collection_approve:\d+$"))
async def collection_approve(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings):
        return
    settlement = await session.get(ProviderSettlement, int(callback.data.rsplit(":", 1)[1]))
    actor = await admin_actor(session, services, callback)
    if not settlement:
        return await callback_notice(callback, "الطلب غير موجود", show_alert=True)
    if not settlement.proof_file_id:
        return await callback_notice(callback, "لم تستلم صورة وصل بعد.", show_alert=True)
    await services.settlements.review(session, settlement, actor.id if actor else 0, True)
    provider = await session.get(Provider, settlement.provider_id)
    reason_key = f"provider.suspension_reason.{settlement.provider_id}"
    reason_row = await session.scalar(select(SystemSetting).where(SystemSetting.key == reason_key))
    expected_reason = f"settlement:{settlement.id}:nonpayment"
    if provider and provider.status == ProviderStatus.SUSPENDED.value and reason_row and reason_row.value == expected_reason:
        provider.status = ProviderStatus.ACTIVE.value
        provider.is_active = True
        offers_key = f"provider.suspension_offers.{provider.id}"
        offers_row = await session.scalar(select(SystemSetting).where(SystemSetting.key == offers_key))
        try:
            offer_ids = [int(x) for x in json.loads(offers_row.value)] if offers_row else []
        except (TypeError, ValueError, json.JSONDecodeError):
            offer_ids = []
        if offer_ids:
            suspended_offers = list((await session.scalars(select(Offer).where(Offer.id.in_(offer_ids)))).all())
            for offer in suspended_offers:
                offer.is_active = True
                if offer.status == OfferStatus.PAUSED.value:
                    offer.status = OfferStatus.ACTIVE.value
        reason_row.value = "resolved"
        await session.flush()
        mark_platform_authorization_dirty(session, provider_id=provider.id)
    await services.audit.log(session, actor, "provider.collection.approved", "provider_settlement", str(settlement.id), {})
    await _notify_provider_finance(
        session, services, settlement.provider_id, "تم تأكيد دفع رسوم CampusPass",
        f"تم تأكيد الوصل للطلب {settlement.public_id}. تستمر المنصة بخدمات البوت بصورة طبيعية.",
        f"settlement:{settlement.id}:approved",
    )
    await callback_notice(callback, "تم تأكيد الدفع ✅", show_alert=True)


@router.callback_query(F.data.regexp(r"^admin:collection_reject:\d+$"))
async def collection_reject(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings):
        return
    settlement = await session.get(ProviderSettlement, int(callback.data.rsplit(":", 1)[1]))
    actor = await admin_actor(session, services, callback)
    if not settlement:
        return await callback_notice(callback, "الطلب غير موجود", show_alert=True)
    await services.settlements.review(session, settlement, actor.id if actor else 0, False, "وصل غير مقبول")
    await services.audit.log(session, actor, "provider.collection.rejected", "provider_settlement", str(settlement.id), {})
    await _notify_provider_finance(
        session, services, settlement.provider_id, "تم رفض وصل رسوم CampusPass",
        f"تم رفض الوصل للطلب {settlement.public_id}. أعد إرسال وصل MasterCard صحيح من نفس الطلب.",
        f"settlement:{settlement.id}:rejected",
    )
    await callback_notice(callback, "تم رفض الوصل.", show_alert=True)


@router.callback_query(F.data.regexp(r"^admin:collection_ban:\d+$"))
async def collection_ban_provider(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings):
        return
    settlement = await session.get(ProviderSettlement, int(callback.data.rsplit(":", 1)[1]))
    actor = await admin_actor(session, services, callback)
    if not settlement:
        return await callback_notice(callback, "الطلب غير موجود", show_alert=True)
    provider = await session.get(Provider, settlement.provider_id)
    if not provider:
        return await callback_notice(callback, "المنصة غير موجودة", show_alert=True)
    provider.status = ProviderStatus.SUSPENDED.value
    provider.is_active = False
    await session.flush()
    mark_platform_authorization_dirty(session, provider_id=provider.id)
    offers = list((await session.scalars(select(Offer).where(Offer.provider_id == provider.id))).all())
    hidden_offer_ids = []
    for offer in offers:
        if offer.is_active or offer.status == OfferStatus.ACTIVE.value:
            hidden_offer_ids.append(offer.id)
        offer.is_active = False
        if offer.status == OfferStatus.ACTIVE.value:
            offer.status = OfferStatus.PAUSED.value
    for setting_key, setting_value in (
        (f"provider.suspension_reason.{provider.id}", f"settlement:{settlement.id}:nonpayment"),
        (f"provider.suspension_offers.{provider.id}", json.dumps(hidden_offer_ids)),
    ):
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == setting_key))
        if row:
            row.value = setting_value
        else:
            session.add(SystemSetting(key=setting_key, value=setting_value))
    terminal = {
        OrderStatus.COMPLETED.value, OrderStatus.CANCELLED.value,
        OrderStatus.REFUNDED.value, OrderStatus.PAYMENT_REJECTED.value,
    }
    open_orders = list((await session.scalars(
        select(Order).where(Order.provider_id == provider.id, Order.status.notin_(terminal))
    )).all())
    for order in open_orders:
        old = order.status
        order.status = OrderStatus.CANCELLED.value
        session.add(OrderEvent(
            order_id=order.id,
            actor_user_id=actor.id if actor else None,
            old_status=old,
            new_status=OrderStatus.CANCELLED.value,
            note="أوقف الطلب بسبب حظر المنصة من CampusPass",
            metadata_json={"provider_suspended": True, "settlement_id": settlement.id},
        ))
        user = await session.get(User, order.user_id)
        if user:
            contact = f"@{provider.contact_username}" if provider.contact_username else "بيانات التواصل المسجلة للمنصة"
            await services.notifications.send_user(
                session,
                user,
                "تم إيقاف الطلب بسبب حظر المنصة",
                f"تم حظر منصة {provider.name_ar} (ID: {provider.id}) لعدم امتثالها لشروط CampusPass. "
                f"تم إيقاف الطلب {order.public_id}. إذا كنت قد أرسلت مبلغًا للمنصة فتواصل مباشرة معها عبر {contact}. "
                "إدارة CampusPass لا تستلم مبلغ الخدمة نيابةً عن المنصة.",
                idempotency_key=f"provider:{provider.id}:ban:order:{order.id}",
            )
    await services.audit.log(
        session, actor, "provider.suspended.nonpayment", "provider", str(provider.id),
        {"settlement_id": settlement.id, "hidden_offers": len(offers), "cancelled_orders": len(open_orders)},
    )
    await _notify_provider_finance(
        session, services, provider.id, "تم حظر المنصة",
        "تم تعليق المنصة وإخفاء عروضها وإيقاف الطلبات المفتوحة بسبب عدم الامتثال لشروط ورسوم CampusPass. "
        "راجع إدارة البوت لمعالجة الحالة.",
        f"provider:{provider.id}:suspended:{settlement.id}",
    )
    await callback_notice(callback, "تم حظر المنصة وإخفاء عروضها وإيقاف الطلبات المفتوحة.", show_alert=True)


# ---------------------------------------------------------------------------
# V8.1 student purchase discount codes: global or provider-specific.
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:order_coupons")
async def order_coupons_home(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    coupons = list((await session.scalars(
        select(OrderCoupon).order_by(OrderCoupon.created_at.desc()).limit(25)
    )).all())
    lines = [
        f"• <code>{c.code}</code> — {'عام' if c.provider_id is None else f'منصة #{c.provider_id}'} — "
        f"{c.value_int}{'%' if c.coupon_type == OrderCouponType.PERCENT.value else ' د.ع'} — "
        f"{'فعال' if c.is_active else 'متوقف'}"
        for c in coupons
    ]
    rows = [
        [InlineKeyboardButton(text="➕ كود عام", callback_data="admin:order_coupon_new:global", style="success")],
        [InlineKeyboardButton(text="🏢 كود لمنصة", callback_data="admin:order_coupon_new:provider", style="primary")],
        [InlineKeyboardButton(text="↩️ المالية", callback_data="admin:finance")],
    ]
    await edit_or_send(callback.message, 
        "🎟 <b>أكواد خصم طلبات الطلاب</b>\n\n" + ("\n".join(lines) if lines else "لا توجد أكواد بعد."),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data == "admin:order_coupon_new:global")
async def order_coupon_global_start(
    callback: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.update_data(order_coupon_provider_id=None)
    await state.set_state(AdminOrderCouponStates.code)
    await edit_or_send(callback.message, "اكتب كود الخصم العام، مثال: <code>STUDENT500</code>")


@router.callback_query(F.data == "admin:order_coupon_new:provider")
async def order_coupon_provider_pick(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    providers = list((await session.scalars(select(Provider).order_by(Provider.name_ar))).all())
    rows = [
        [InlineKeyboardButton(text=p.name_ar, callback_data=f"admin:order_coupon_provider:{p.id}", style="primary")]
        for p in providers
    ]
    rows.append([InlineKeyboardButton(text="↩️ الأكواد", callback_data="admin:order_coupons")])
    await edit_or_send(callback.message, "اختر المنصة:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.regexp(r"^admin:order_coupon_provider:\d+$"))
async def order_coupon_provider_start(
    callback: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.update_data(order_coupon_provider_id=int(callback.data.rsplit(":", 1)[1]))
    await state.set_state(AdminOrderCouponStates.code)
    await edit_or_send(callback.message, "اكتب كود الخصم المخصص لهذه المنصة:")


@router.message(AdminOrderCouponStates.code)
async def order_coupon_code(
    message: Message, state: FSMContext, settings: Settings
) -> None:
    if not await require_admin(message, settings):
        return
    code = (message.text or "").strip().upper()
    if not 3 <= len(code) <= 40:
        return await message.answer("الكود يجب أن يكون من 3 إلى 40 حرفًا.")
    await state.update_data(order_coupon_code=code)
    await message.answer(
        "اختر نوع الخصم:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💵 مبلغ ثابت", callback_data="admin:order_coupon_kind:fixed", style="primary")],
            [InlineKeyboardButton(text="% نسبة مئوية", callback_data="admin:order_coupon_kind:percent", style="success")],
        ]),
    )


@router.callback_query(F.data.in_({"admin:order_coupon_kind:fixed", "admin:order_coupon_kind:percent"}))
async def order_coupon_kind(
    callback: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    kind = callback.data.rsplit(":", 1)[1]
    await state.update_data(order_coupon_kind=kind)
    await state.set_state(AdminOrderCouponStates.value)
    await edit_or_send(callback.message, 
        "اكتب قيمة الخصم بالأرقام. مثال: <code>500</code> للمبلغ أو <code>10</code> للنسبة."
    )


@router.message(AdminOrderCouponStates.value)
async def order_coupon_value(
    message: Message, state: FSMContext, settings: Settings
) -> None:
    if not await require_admin(message, settings):
        return
    raw = parse_money(message.text or "")
    if raw is None or raw <= 0:
        return await message.answer("اكتب قيمة صحيحة أكبر من صفر.")
    data = await state.get_data()
    if data.get("order_coupon_kind") == "percent" and raw > 100:
        return await message.answer("النسبة يجب ألا تتجاوز 100.")
    await state.update_data(order_coupon_value=raw)
    await state.set_state(AdminOrderCouponStates.max_uses)
    await message.answer("اكتب أقصى عدد استخدامات للكود، أو اكتب <code>0</code> لغير محدود:")


@router.message(AdminOrderCouponStates.max_uses)
async def order_coupon_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    raw_text = (message.text or "").strip()
    if raw_text == "0":
        raw = 0
    else:
        raw = parse_money(raw_text)
    if raw is None or raw < 0:
        return await message.answer("اكتب 0 أو رقمًا صحيحًا.")
    data = await state.get_data()
    actor = await admin_actor(session, services, message)
    try:
        coupon = await services.order_coupons.create(
            session,
            code=str(data.get("order_coupon_code", "")),
            coupon_type=str(data.get("order_coupon_kind", "fixed")),
            value_int=int(data.get("order_coupon_value", 0)),
            provider_id=data.get("order_coupon_provider_id"),
            created_by_user_id=actor.id if actor else None,
            max_uses=None if raw == 0 else raw,
        )
    except ValueError as exc:
        return await message.answer(str(exc))
    await services.audit.log(
        session, actor, "order_coupon.created", "order_coupon", str(coupon.id),
        {"code": coupon.code, "provider_id": coupon.provider_id, "value": coupon.value_int},
    )
    await state.clear()
    await message.answer(
        f"✅ تم إنشاء كود <code>{coupon.code}</code> بنجاح.",
        reply_markup=admin_back(),
    )
