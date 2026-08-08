from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin.common import admin_actor, admin_back, require_admin
from app.bot.states import (
    AdminAnnouncementStates,
    AdminCustomButtonStates,
    AdminSystemPriceStates,
)
from app.bot.keyboards.inline import with_navigation
from app.bot.ui import edit_or_send, callback_notice
from app.core.config import Settings
from app.core.utils import safe
from app.db.models import (
    Announcement,
    AnnouncementStatus,
    BotIssueReport,
    FeatureBillingMode,
    MenuContentType,
    SystemSetting,
    UserRole,
)
from app.services.container import Services

router = Router(name="admin_v5")


def _markup(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return with_navigation(InlineKeyboardMarkup(inline_keyboard=rows))


PRICE_KEYS: dict[str, str] = {
    "service_fee_iqd": "رسوم خدمة البوت لكل طلب",
    "report_standard_monthly": "التقرير الاعتيادي شهريًا",
    "report_plus_monthly": "تقارير Plus شهريًا",
    "report_pro_monthly": "تقارير Pro شهريًا",
    "report_standard_yearly": "التقرير الاعتيادي سنويًا",
    "report_plus_yearly": "تقارير Plus سنويًا",
    "report_pro_yearly": "تقارير Pro سنويًا",
    "email_codes_monthly": "خدمة جلب رموز البريد شهريًا",
    "menu_builder_monthly": "منشئ القوائم شهريًا",
    "announcements_monthly": "الإعلانات المثبتة شهريًا",
}

FEATURE_NAMES: dict[str, str] = {
    "reports.standard": "التقارير الاعتيادية",
    "reports.plus": "تقارير Plus",
    "reports.pro": "تقارير Pro",
    "email_codes": "جلب رموز البريد",
    "menu_builder": "منشئ القوائم",
    "announcements": "الإعلانات والتحديثات",
    "extra_staff": "الموظفون الإضافيون",
    "advanced_exports": "التصدير المتقدم",
}

FEATURE_KEY_TOKENS = {key: str(index) for index, key in enumerate(FEATURE_NAMES, start=1)}
FEATURE_KEYS_BY_TOKEN = {token: key for key, token in FEATURE_KEY_TOKENS.items()}
FEATURE_MODE_VALUES = (
    FeatureBillingMode.FREE.value,
    FeatureBillingMode.ONE_TIME.value,
    FeatureBillingMode.MONTHLY.value,
    FeatureBillingMode.YEARLY.value,
    FeatureBillingMode.TRIAL.value,
    FeatureBillingMode.HIDDEN.value,
)
FEATURE_MODE_TOKENS = {mode: str(index) for index, mode in enumerate(FEATURE_MODE_VALUES, start=1)}
FEATURE_MODES_BY_TOKEN = {token: mode for mode, token in FEATURE_MODE_TOKENS.items()}


# ---------------- Owner-controlled prices ----------------
@router.callback_query(F.data == "admin:prices")
async def admin_prices(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await callback_notice(callback, "جاري تحميل الأسعار...")
    rows: list[list[InlineKeyboardButton]] = []
    lines = [
        "💰 <b>أسعار النظام تحت سيطرة المالك</b>\n",
        "المنصة تغيّر سعر عروضها فقط. أسعار البوت والميزات والتقارير يغيّرها المالك هنا.",
    ]
    for key, label in PRICE_KEYS.items():
        value = await services.pricing.get_system_price(session, key, 0)
        lines.append(f"\n• {safe(label)}: <b>{value:,} د.ع</b>")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"✏️ {label}", callback_data=f"admin:price_edit:{key}", style="primary"
                )
            ]
        )
    minimum = await services.pricing.minimum_offer_price(session)
    lines.append(f"\n• حد التحذير لسعر العرض: <b>{minimum:,} د.ع</b>")
    rows.append(
        [
            InlineKeyboardButton(
                text="⚠️ تعديل حد تحذير السعر",
                callback_data="admin:price_edit:minimum_offer_price_iqd",
                style="danger",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🧩 تسعير الميزات",
                callback_data="admin:feature_prices",
                style="success",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")])
    await edit_or_send(callback.message, "".join(lines), reply_markup=_markup(rows))


@router.callback_query(F.data.startswith("admin:price_edit:"))
async def admin_price_edit_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    key = (callback.data or "").split(":", 2)[2]
    if key not in PRICE_KEYS and key != "minimum_offer_price_iqd":
        await edit_or_send(callback.message, "السعر غير معروف.")
        return
    await state.clear()
    await state.update_data(price_key=key)
    await state.set_state(AdminSystemPriceStates.value)
    await edit_or_send(callback.message, 
        "💰 اكتب السعر بالدينار كاملًا.\n\n"
        "مثال صحيح: <code>10000</code> = عشرة آلاف دينار\n"
        "مثال خاطئ: <code>10</code> = عشرة دنانير فقط\n\n"
        "اكتب <code>0</code> لجعل الميزة مجانية."
    )


@router.message(AdminSystemPriceStates.value)
async def admin_price_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    try:
        value = services.pricing.parse_iqd(message.text or "", allow_zero=True)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    suspicious = 0 < value < 1000
    rows = [
        [
            InlineKeyboardButton(
                text="✅ حفظ السعر", callback_data="admin:price_confirm", style="success"
            )
        ],
        [InlineKeyboardButton(text="✏️ كتابة السعر من جديد", callback_data="admin:price_retry")],
        [InlineKeyboardButton(text="⬅️ رجوع للأسعار", callback_data="admin:prices")],
    ]
    await state.update_data(price_value=value)
    await state.set_state(AdminSystemPriceStates.confirm)
    warning = (
        "\n\n⚠️ <b>تنبيه:</b> الرقم أقل من 1,000. إذا كنت تقصد عشرة آلاف اكتب 10000 وليس 10."
        if suspicious
        else ""
    )
    await message.answer(
        "📋 <b>مراجعة السعر</b>\n\n"
        f"الرقم: <b>{value:,} د.ع</b>\n"
        f"كتابةً: <b>{services.pricing.iqd_words(value)}</b>"
        f"{warning}",
        reply_markup=_markup(rows),
    )


@router.callback_query(F.data == "admin:price_retry")
async def admin_price_retry(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminSystemPriceStates.value)
    if callback.message:
        await edit_or_send(callback.message, "اكتب الرقم من جديد، مثل 10000:")


@router.callback_query(F.data == "admin:price_confirm")
async def admin_price_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await callback_notice(callback, "تم الحفظ ✅")
    data = await state.get_data()
    key = str(data.get("price_key") or "")
    value = int(data.get("price_value") or 0)
    actor = await admin_actor(session, services, callback)
    if key == "minimum_offer_price_iqd":
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if not row:
            row = SystemSetting(key=key, value=str(value), updated_by_user_id=actor.id if actor else None)
            session.add(row)
        else:
            row.value = str(value)
            row.updated_by_user_id = actor.id if actor else None
    else:
        await services.pricing.set_system_price(session, key, value, actor, "تعديل من لوحة v5")
    await state.clear()
    await edit_or_send(callback.message, 
        f"✅ تم اعتماد السعر: <b>{value:,} د.ع</b>",
        reply_markup=admin_back(),
    )


@router.callback_query(F.data == "admin:feature_prices")
async def feature_prices(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    rows = []
    lines = ["🧩 <b>حالة تسعير الميزات</b>"]
    for key, name in FEATURE_NAMES.items():
        row = await services.pricing.feature_price(session, key, name)
        lines.append(f"\n• {name}: <code>{row.billing_mode}</code>")
        rows.append(
            [InlineKeyboardButton(text=f"⚙️ {name}", callback_data=f"admin:feature_price:{key}")]
        )
    rows.append([InlineKeyboardButton(text="↩️ الأسعار", callback_data="admin:prices")])
    await edit_or_send(callback.message, "".join(lines), reply_markup=_markup(rows))


@router.callback_query(F.data.startswith("admin:feature_price:"))
async def feature_price_details(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    key = (callback.data or "").split(":", 2)[2]
    if key not in FEATURE_NAMES:
        return
    row = await services.pricing.feature_price(session, key, FEATURE_NAMES[key])
    options = [
        ("🆓 مجاني", FeatureBillingMode.FREE.value, "success"),
        ("💳 دفعة واحدة", FeatureBillingMode.ONE_TIME.value, "primary"),
        ("📅 شهري", FeatureBillingMode.MONTHLY.value, "primary"),
        ("🗓 سنوي", FeatureBillingMode.YEARLY.value, "primary"),
        ("🎁 تجريبي", FeatureBillingMode.TRIAL.value, "success"),
        ("🙈 مخفي", FeatureBillingMode.HIDDEN.value, "danger"),
    ]
    rows = [
        [InlineKeyboardButton(text=text, callback_data=f"a:fm:{FEATURE_KEY_TOKENS[key]}:{FEATURE_MODE_TOKENS[mode]}", style=style)]
        for text, mode, style in options
    ]
    rows.append([InlineKeyboardButton(text="↩️ الميزات", callback_data="admin:feature_prices")])
    await edit_or_send(callback.message, 
        f"🧩 <b>{safe(row.name_ar)}</b>\nالحالة الحالية: <code>{row.billing_mode}</code>\n\n"
        "السعر الفعلي يُقرأ من قسم الأسعار ولا يثبت داخل الكود.",
        reply_markup=_markup(rows),
    )


@router.callback_query(F.data.startswith("a:fm:"))
@router.callback_query(F.data.startswith("admin:feature_mode:"))
async def feature_mode_set(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    parts = (callback.data or "").split(":")
    if parts[0] == "a":
        key = FEATURE_KEYS_BY_TOKEN.get(parts[2], "")
        mode = FEATURE_MODES_BY_TOKEN.get(parts[3], "")
    else:
        key, mode = parts[2], parts[3]
    if key not in FEATURE_NAMES or mode not in {item.value for item in FeatureBillingMode}:
        return
    row = await services.pricing.feature_price(session, key, FEATURE_NAMES[key])
    actor = await admin_actor(session, services, callback)
    row.billing_mode = mode
    row.is_enabled = mode != FeatureBillingMode.HIDDEN.value
    row.updated_by_user_id = actor.id if actor else None
    await callback_notice(callback, "تم التحديث ✅", show_alert=True)
    await edit_or_send(callback.message, 
        f"تم تغيير {safe(row.name_ar)} إلى <code>{mode}</code>.", reply_markup=admin_back()
    )


# ---------------- Timed pinned announcements ----------------
@router.callback_query(F.data == "admin:announcements")
async def announcements_home(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    rows = list(
        (
            await session.scalars(
                select(Announcement).order_by(Announcement.created_at.desc()).limit(12)
            )
        ).all()
    )
    lines = [
        "📣 <b>الإعلانات المثبتة</b>\n\n",
        "ينرسل الإعلان للمستخدم ثم يثبت أعلى محادثة البوت، "
        "وبعد انتهاء المدة ينفك تلقائيًا.\n",
    ]
    buttons = [
        [
            InlineKeyboardButton(
                text="➕ إنشاء إعلان مثبت", callback_data="admin:announcement_add", style="success"
            )
        ]
    ]
    if not rows:
        lines.append("\nلا توجد إعلانات سابقة.")
    for item in rows:
        pin_label = "📌" if item.pin_message else "📨"
        lines.append(f"\n{pin_label} #{item.id} {safe(item.title)} — {item.status}")
        if item.status in {AnnouncementStatus.ACTIVE.value, AnnouncementStatus.SCHEDULED.value}:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"⏹ إيقاف الإعلان #{item.id}",
                        callback_data=f"admin:ann_stop:{item.id}",
                        style="danger",
                    )
                ]
            )
    buttons.append([InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")])
    await edit_or_send(callback.message, "".join(lines), reply_markup=_markup(buttons))


@router.callback_query(F.data.startswith("admin:ann_stop:"))
async def announcement_stop(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    try:
        announcement_id = int((callback.data or "").split(":")[-1])
    except ValueError:
        await callback_notice(callback, "رقم الإعلان غير صحيح.", show_alert=True)
        return
    stopped = await services.announcements.stop_by_id(session, announcement_id)
    if not stopped:
        await callback_notice(callback, "الإعلان غير موجود.", show_alert=True)
        return
    await callback_notice(callback, "تم إيقاف الإعلان وفك تثبيته ✅", show_alert=True)
    await edit_or_send(callback.message, 
        f"⏹ تم إيقاف الإعلان رقم <code>{announcement_id}</code> وفك تثبيته عن المحادثات.",
        reply_markup=admin_back(),
    )


@router.callback_query(F.data == "admin:announcement_add")
async def announcement_add(
    callback: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.set_state(AdminAnnouncementStates.title)
    await edit_or_send(callback.message, "اكتب عنوان الإعلان أو اسم التحديث:")


@router.message(AdminAnnouncementStates.title)
async def announcement_title(message: Message, state: FSMContext, settings: Settings) -> None:
    if not await require_admin(message, settings):
        return
    title = " ".join((message.text or "").split())
    if not 3 <= len(title) <= 220:
        await message.answer("العنوان يجب أن يكون بين 3 و220 حرفًا.")
        return
    await state.update_data(announcement_title=title)
    await state.set_state(AdminAnnouncementStates.body)
    await message.answer(
        "أرسل نص الإعلان، أو أرسل صورة/فيديو/ملف مع وصف.\n"
        "لن تلغي هذه الرسالة أي عملية أخرى للمستخدم عند وصولها."
    )


@router.message(AdminAnnouncementStates.body)
async def announcement_body(message: Message, state: FSMContext, settings: Settings) -> None:
    if not await require_admin(message, settings):
        return
    media_type = media_file_id = None
    body = (message.text or message.caption or "").strip()
    if message.photo:
        media_type, media_file_id = "photo", message.photo[-1].file_id
    elif message.video:
        media_type, media_file_id = "video", message.video.file_id
    elif message.document:
        media_type, media_file_id = "document", message.document.file_id
    if not body:
        body = "إعلان جديد من CampusPass IQ"
    await state.update_data(
        announcement_body=body[:4000],
        announcement_media_type=media_type,
        announcement_media_file_id=media_file_id,
    )
    await state.set_state(AdminAnnouncementStates.target_scope)
    await message.answer(
        "اختر المستلمين:",
        reply_markup=_markup(
            [
                [InlineKeyboardButton(text="👥 الجميع", callback_data="admin:ann_target:all", style="primary")],
                [InlineKeyboardButton(text="🎓 الطلاب", callback_data="admin:ann_target:students")],
                [InlineKeyboardButton(text="🏢 أصحاب وموظفو المنصات", callback_data="admin:ann_target:providers")],
                [InlineKeyboardButton(text="🛡 الأدمن فقط", callback_data="admin:ann_target:admins")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("admin:ann_target:"))
async def announcement_target(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    scope = (callback.data or "").split(":")[-1]
    if scope not in {"all", "students", "providers", "admins"} or not callback.message:
        return
    await state.update_data(announcement_target_scope=scope)
    await state.set_state(AdminAnnouncementStates.duration_hours)
    await edit_or_send(callback.message, 
        "اختر مدة التثبيت أو اكتب عدد الساعات يدويًا.\n"
        "مثال: <code>12</code> يعني يبقى مثبتًا 12 ساعة.\n"
        "الرقم <code>0</code> يعني يبقى حتى توقفه يدويًا.",
        reply_markup=_markup(
            [
                [
                    InlineKeyboardButton(text="1 ساعة", callback_data="admin:ann_duration:1"),
                    InlineKeyboardButton(text="6 ساعات", callback_data="admin:ann_duration:6"),
                ],
                [
                    InlineKeyboardButton(text="12 ساعة", callback_data="admin:ann_duration:12"),
                    InlineKeyboardButton(text="24 ساعة", callback_data="admin:ann_duration:24"),
                ],
                [
                    InlineKeyboardButton(text="3 أيام", callback_data="admin:ann_duration:72"),
                    InlineKeyboardButton(text="📌 دائم", callback_data="admin:ann_duration:0", style="danger"),
                ],
            ]
        ),
    )


@router.callback_query(F.data.startswith("admin:ann_duration:"))
async def announcement_duration_button(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    try:
        hours = int((callback.data or "").split(":")[-1])
    except ValueError:
        await callback_notice(callback, "المدة غير صحيحة.", show_alert=True)
        return
    await state.update_data(announcement_duration_hours=hours)
    await state.set_state(AdminAnnouncementStates.pin)
    await edit_or_send(callback.message, 
        "هل يثبت الإعلان أعلى المحادثة؟",
        reply_markup=_markup(
            [
                [InlineKeyboardButton(text="📌 نعم، تثبيت", callback_data="admin:ann_pin:yes", style="success")],
                [InlineKeyboardButton(text="بدون تثبيت", callback_data="admin:ann_pin:no")],
            ]
        ),
    )


@router.message(AdminAnnouncementStates.duration_hours)
async def announcement_duration(message: Message, state: FSMContext, settings: Settings) -> None:
    if not await require_admin(message, settings):
        return
    try:
        hours = int(services_digits(message.text or ""))
    except ValueError:
        await message.answer("اكتب عدد الساعات فقط، مثل 12.")
        return
    if not 0 <= hours <= 24 * 90:
        await message.answer("المدة يجب أن تكون بين 0 و2160 ساعة.")
        return
    await state.update_data(announcement_duration_hours=hours)
    await state.set_state(AdminAnnouncementStates.pin)
    await message.answer(
        "هل يثبت الإعلان أعلى المحادثة؟",
        reply_markup=_markup(
            [
                [InlineKeyboardButton(text="📌 نعم، تثبيت", callback_data="admin:ann_pin:yes", style="success")],
                [InlineKeyboardButton(text="بدون تثبيت", callback_data="admin:ann_pin:no")],
            ]
        ),
    )


def services_digits(value: str) -> str:
    return value.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")).strip()


@router.callback_query(F.data.startswith("admin:ann_pin:"))
async def announcement_pin(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    pin = (callback.data or "").endswith(":yes")
    await state.update_data(announcement_pin=pin)
    await state.set_state(AdminAnnouncementStates.button)
    await edit_or_send(callback.message, 
        "أرسل زر الإعلان بأحد الشكلين:\n"
        "🌐 رابط خارجي: <code>مشاهدة العرض | https://example.com</code>\n"
        "🤖 زر داخل البوت: <code>مشاهدة العروض | action:offers</code>\n\n"
        "الأوامر الداخلية المتاحة: <code>services</code>، <code>offers</code>، "
        "<code>orders</code>، <code>subscriptions</code>، <code>profile</code>، "
        "<code>favorites</code>، <code>points</code>، <code>help</code>.\n"
        "أو أرسل <code>-</code> بدون زر."
    )


@router.message(AdminAnnouncementStates.button)
async def announcement_button(message: Message, state: FSMContext, settings: Settings) -> None:
    if not await require_admin(message, settings):
        return
    raw = (message.text or "").strip()
    button_text = button_url = None
    if raw != "-":
        parts = [part.strip() for part in raw.split("|", 1)]
        allowed_actions = {
            "services",
            "offers",
            "orders",
            "subscriptions",
            "profile",
            "favorites",
            "points",
            "help",
        }
        if len(parts) != 2:
            await message.answer("الصيغة غير صحيحة. استخدم: اسم الزر | الرابط أو action:offers")
            return
        target = parts[1]
        if target.startswith("action:"):
            action = target.removeprefix("action:").strip()
            if action not in allowed_actions:
                await message.answer(
                    "الأمر الداخلي غير مدعوم. استخدم واحدًا من: "
                    "services, offers, orders, subscriptions, profile, favorites, points, help"
                )
                return
            button_url = f"action:{action}"
        elif target.startswith(("https://", "http://")):
            button_url = target[:2000]
        else:
            await message.answer(
                "الرابط يجب أن يبدأ بـ https:// أو يكون أمرًا داخليًا مثل action:offers"
            )
            return
        button_text = parts[0][:120]
    await state.update_data(announcement_button_text=button_text, announcement_button_url=button_url)
    await state.set_state(AdminAnnouncementStates.confirm)
    data = await state.get_data()
    hours = int(data.get("announcement_duration_hours") or 0)
    await message.answer(
        "📋 <b>معاينة الإعلان</b>\n\n"
        f"📣 <b>{safe(data.get('announcement_title'))}</b>\n\n"
        f"{safe(data.get('announcement_body'))}\n\n"
        f"المستلمون: <code>{safe(data.get('announcement_target_scope'))}</code>\n"
        f"المدة: {'دائم حتى الإيقاف' if hours == 0 else str(hours) + ' ساعة'}\n"
        f"التثبيت: {'نعم' if data.get('announcement_pin') else 'لا'}",
        reply_markup=_markup(
            [
                [InlineKeyboardButton(text="✅ نشر الآن", callback_data="admin:ann_confirm", style="success")],
                [InlineKeyboardButton(text="❌ إلغاء", callback_data="admin:ann_cancel", style="danger")],
            ]
        ),
    )


@router.callback_query(F.data == "admin:ann_confirm")
async def announcement_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await callback_notice(callback, "جاري النشر...")
    data = await state.get_data()
    actor = await admin_actor(session, services, callback)
    hours = int(data.get("announcement_duration_hours") or 0)
    now = datetime.now(UTC)
    row = Announcement(
        title=str(data.get("announcement_title") or "إعلان"),
        body=str(data.get("announcement_body") or ""),
        media_type=data.get("announcement_media_type"),
        media_file_id=data.get("announcement_media_file_id"),
        button_text=data.get("announcement_button_text"),
        button_url=data.get("announcement_button_url"),
        target_scope=str(data.get("announcement_target_scope") or "all"),
        starts_at=now,
        ends_at=now + timedelta(hours=hours) if hours else None,
        pin_message=bool(data.get("announcement_pin")),
        status=AnnouncementStatus.ACTIVE.value,
        created_by_user_id=actor.id if actor else None,
    )
    session.add(row)
    await session.flush()
    success, failed, pinned, pin_failed = await services.announcements.dispatch(session, row)
    await state.clear()
    await edit_or_send(callback.message, 
        f"✅ تم نشر الإعلان.\n"
        f"وصل إلى: {success:,}\n"
        f"تعذر الإرسال: {failed:,}\n"
        f"تم تثبيته: {pinned:,}\n"
        f"تعذر التثبيت: {pin_failed:,}\n"
        "سيُفك التثبيت تلقائيًا بعد انتهاء المدة، أو يمكن إيقافه من قائمة الإعلانات.",
        reply_markup=admin_back(),
    )


@router.callback_query(F.data == "admin:ann_cancel")
async def announcement_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await edit_or_send(callback.message, "تم إلغاء الإعلان.")


# ---------------- Menu builder ----------------
@router.callback_query(F.data == "admin:menu_builder")
async def menu_builder_home(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    custom = [item for item in await services.menus.list_buttons(session) if item.action == "custom_content"]
    lines = [
        "🧱 <b>منشئ القوائم v5</b>\n",
        "يمكن إنشاء زر نص أو صورة أو فيديو أو ملف أو رابط أو قائمة فرعية. "
        "ويمكن تحويل أي زر بين لوحة الكيبورد والزر الشفاف وإخفائه من مدير الواجهة.",
    ]
    for item in custom:
        lines.append(f"\n• <code>{item.key}</code> — {safe(item.text)} — {item.surface}")
    rows = [
        [InlineKeyboardButton(text="➕ إنشاء زر جديد", callback_data="admin:menu_custom_add", style="success")],
        [InlineKeyboardButton(text="🎛 إدارة كل الأزرار", callback_data="admin:menu_manager", style="primary")],
        [InlineKeyboardButton(text="👁 معاينة الواجهة", callback_data="admin:menu_preview")],
        [InlineKeyboardButton(text="💾 حفظ نسخة الواجهة", callback_data="admin:menu_revision_save", style="success")],
        [InlineKeyboardButton(text="🕘 سجل النسخ والاستعادة", callback_data="admin:menu_revision_list", style="primary")],
        [InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")],
    ]
    await edit_or_send(callback.message, "".join(lines), reply_markup=_markup(rows))


@router.callback_query(F.data == "admin:menu_custom_add")
async def menu_custom_add(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.set_state(AdminCustomButtonStates.key)
    await edit_or_send(callback.message, 
        "اكتب معرفًا داخليًا للزر بالإنجليزي، مثل <code>activation_help</code>. "
        "لا يظهر هذا المعرف للمستخدم."
    )


@router.message(AdminCustomButtonStates.key)
async def menu_custom_key(message: Message, state: FSMContext, settings: Settings) -> None:
    if not await require_admin(message, settings):
        return
    key = (message.text or "").strip().lower()
    if not 3 <= len(key) <= 80:
        await message.answer("المعرف قصير أو طويل.")
        return
    await state.update_data(custom_key=key)
    await state.set_state(AdminCustomButtonStates.text)
    await message.answer("اكتب اسم الزر الذي سيظهر للمستخدم، مع الإيموجي:")


@router.message(AdminCustomButtonStates.text)
async def menu_custom_text(message: Message, state: FSMContext, settings: Settings) -> None:
    if not await require_admin(message, settings):
        return
    text = " ".join((message.text or "").split())
    if not 1 <= len(text) <= 120:
        await message.answer("اسم الزر غير صالح.")
        return
    await state.update_data(custom_text=text)
    await state.set_state(AdminCustomButtonStates.content_type)
    options = [
        ("📝 نص", "text"),
        ("🖼 صورة", "photo"),
        ("🎞 فيديو", "video"),
        ("📎 ملف", "document"),
        ("🔗 رابط", "link"),
        ("📂 قائمة فرعية", "submenu"),
    ]
    await message.answer(
        "اختر وظيفة الزر:",
        reply_markup=_markup(
            [[InlineKeyboardButton(text=label, callback_data=f"admin:custom_type:{value}")] for label, value in options]
        ),
    )


@router.callback_query(F.data.startswith("admin:custom_type:"))
async def menu_custom_type(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    content_type = (callback.data or "").split(":")[-1]
    if content_type not in {"text", "photo", "video", "document", "link", "submenu"}:
        return
    await state.update_data(custom_content_type=content_type)
    if content_type == "submenu":
        await state.update_data(custom_content_text="", custom_media_file_id=None, custom_url=None)
        await state.set_state(AdminCustomButtonStates.roles)
        await _ask_custom_roles(callback.message, in_place=True)
        return
    await state.set_state(AdminCustomButtonStates.content)
    prompts = {
        "text": "اكتب النص الذي يظهر عند ضغط الزر:",
        "photo": "أرسل الصورة مع وصف اختياري:",
        "video": "أرسل الفيديو مع وصف اختياري:",
        "document": "أرسل الملف مع وصف اختياري:",
        "link": "أرسل الرابط كاملًا مثل https://example.com:",
    }
    await edit_or_send(callback.message, prompts[content_type])


@router.message(AdminCustomButtonStates.content)
async def menu_custom_content(message: Message, state: FSMContext, settings: Settings) -> None:
    if not await require_admin(message, settings):
        return
    data = await state.get_data()
    kind = str(data.get("custom_content_type") or "")
    text = media_file_id = url = None
    if kind == "text" and message.text:
        text = message.text.strip()[:10000]
    elif kind == "photo" and message.photo:
        media_file_id, text = message.photo[-1].file_id, (message.caption or "").strip()[:4000]
    elif kind == "video" and message.video:
        media_file_id, text = message.video.file_id, (message.caption or "").strip()[:4000]
    elif kind == "document" and message.document:
        media_file_id, text = message.document.file_id, (message.caption or "").strip()[:4000]
    elif kind == "link" and message.text and message.text.startswith(("https://", "http://")):
        url = message.text.strip()[:2000]
        text = "فتح الرابط"
    else:
        await message.answer("المحتوى لا يطابق نوع الزر. أرسله من جديد.")
        return
    await state.update_data(
        custom_content_text=text or "", custom_media_file_id=media_file_id, custom_url=url
    )
    await state.set_state(AdminCustomButtonStates.roles)
    await _ask_custom_roles(message)


async def _ask_custom_roles(
    message: Message,
    *,
    in_place: bool = False,
) -> None:
    async def render(
        text: str,
        *,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        if in_place:
            await edit_or_send(message, text, reply_markup=reply_markup)
        else:
            await message.answer(text, reply_markup=reply_markup)

    await render(
        "من يستطيع رؤية الزر؟",
        reply_markup=_markup(
            [
                [InlineKeyboardButton(text="🎓 الطلاب", callback_data="admin:custom_roles:user")],
                [InlineKeyboardButton(text="🏢 المنصات", callback_data="admin:custom_roles:provider")],
                [InlineKeyboardButton(text="🛡 الأدمن", callback_data="admin:custom_roles:admin")],
                [InlineKeyboardButton(text="👥 الجميع", callback_data="admin:custom_roles:all", style="success")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("admin:custom_roles:"))
async def menu_custom_roles(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    scope = (callback.data or "").split(":")[-1]
    roles = [UserRole.USER.value, UserRole.PROVIDER.value, UserRole.ADMIN.value] if scope == "all" else [scope]
    if any(role not in {item.value for item in UserRole} for role in roles):
        return
    await state.update_data(custom_roles=roles)
    await state.set_state(AdminCustomButtonStates.surface)
    await edit_or_send(callback.message, 
        "أين يظهر الزر؟",
        reply_markup=_markup(
            [
                [InlineKeyboardButton(text="⌨️ لوحة كيبورد", callback_data="admin:custom_surface:reply", style="primary")],
                [InlineKeyboardButton(text="🔘 زر شفاف تحت النص", callback_data="admin:custom_surface:inline", style="primary")],
                [InlineKeyboardButton(text="🔁 في المكانين", callback_data="admin:custom_surface:both", style="success")],
                [InlineKeyboardButton(text="🙈 مخفي حاليًا", callback_data="admin:custom_surface:hidden", style="danger")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("admin:custom_surface:"))
async def menu_custom_surface(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    surface = (callback.data or "").split(":")[-1]
    if surface not in {"reply", "inline", "both", "hidden"}:
        return
    await state.update_data(custom_surface=surface)
    await state.set_state(AdminCustomButtonStates.parent)
    await edit_or_send(callback.message, 
        "اكتب معرف القائمة الأب ليكون زرًا فرعيًا، أو أرسل <code>-</code> ليظهر بالقائمة الرئيسية:"
    )


@router.message(AdminCustomButtonStates.parent)
async def menu_custom_parent(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    raw = (message.text or "").strip()
    parent = None if raw == "-" else raw
    if parent:
        parent_content = await services.menus.content(session, parent)
        if not parent_content or parent_content.content_type != MenuContentType.SUBMENU.value:
            await message.answer("معرف القائمة الأب غير موجود أو ليس قائمة فرعية. اكتب - أو معرفًا صحيحًا.")
            return
    await state.update_data(custom_parent=parent)
    await state.set_state(AdminCustomButtonStates.confirm)
    data = await state.get_data()
    await message.answer(
        "📋 <b>مراجعة الزر</b>\n\n"
        f"الاسم: {safe(data.get('custom_text'))}\n"
        f"المعرف: <code>{safe(data.get('custom_key'))}</code>\n"
        f"النوع: <code>{safe(data.get('custom_content_type'))}</code>\n"
        f"المكان: <code>{safe(data.get('custom_surface'))}</code>\n"
        f"القائمة الأب: <code>{safe(parent or 'الرئيسية')}</code>",
        reply_markup=_markup(
            [
                [InlineKeyboardButton(text="✅ إنشاء الزر", callback_data="admin:custom_confirm", style="success")],
                [InlineKeyboardButton(text="❌ إلغاء", callback_data="admin:custom_cancel", style="danger")],
            ]
        ),
    )


@router.callback_query(F.data == "admin:custom_confirm")
async def menu_custom_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    data = await state.get_data()
    actor = await admin_actor(session, services, callback)
    try:
        button = await services.menus.create_custom_button(
            session,
            key=str(data.get("custom_key") or ""),
            text=str(data.get("custom_text") or ""),
            content_type=str(data.get("custom_content_type") or "text"),
            roles=list(data.get("custom_roles") or [UserRole.USER.value]),
            parent_key=data.get("custom_parent"),
            content_text=str(data.get("custom_content_text") or ""),
            media_file_id=data.get("custom_media_file_id"),
            url=data.get("custom_url"),
            row_number=50,
            position=1,
            surface=str(data.get("custom_surface") or "inline"),
            actor_user_id=actor.id if actor else None,
        )
    except ValueError as exc:
        await edit_or_send(callback.message, str(exc))
        return
    await state.clear()
    await edit_or_send(callback.message, 
        f"✅ تم إنشاء الزر <b>{safe(button.text)}</b>. يمكن تغيير اللون والمكان والإخفاء من إدارة الواجهة.",
        reply_markup=admin_back(),
    )


@router.callback_query(F.data == "admin:custom_cancel")
async def menu_custom_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await edit_or_send(callback.message, "تم إلغاء إنشاء الزر.")


# ---------------- Bot-only issue inbox ----------------
@router.callback_query(F.data == "admin:bot_issues")
async def admin_bot_issues(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    issues = list(
        (
            await session.scalars(
                select(BotIssueReport)
                .where(BotIssueReport.status.in_(["open", "in_progress"]))
                .order_by(BotIssueReport.created_at.desc())
                .limit(30)
            )
        ).all()
    )
    if not issues:
        await edit_or_send(callback.message, "لا توجد بلاغات مفتوحة.", reply_markup=admin_back())
        return
    rows = [
        [
            InlineKeyboardButton(
                text=f"🐞 {item.public_id} — {item.category}",
                callback_data=f"admin:bot_issue:{item.id}",
                style="danger" if item.status == "open" else "primary",
            )
        ]
        for item in issues
    ]
    rows.append([InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")])
    await edit_or_send(callback.message, "🐞 <b>بلاغات مشاكل البوت — للمالك فقط</b>", reply_markup=_markup(rows))


@router.callback_query(F.data.startswith("admin:bot_issue:"))
async def admin_bot_issue_details(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    issue = await session.get(BotIssueReport, int((callback.data or "").split(":")[2]))
    if not issue:
        return
    await edit_or_send(callback.message, 
        f"🐞 <b>{issue.public_id}</b>\n"
        f"الفئة: {safe(issue.category)}\n"
        f"الحالة: {safe(issue.status)}\n"
        f"آخر إجراء: {safe(issue.last_action, 'غير متوفر')}\n"
        f"حالة المحادثة: <code>{safe(issue.conversation_state, 'لا توجد')}</code>\n\n"
        f"{safe(issue.description)}",
        reply_markup=_markup(
            [
                [InlineKeyboardButton(text="🛠 قيد المعالجة", callback_data=f"admin:bot_issue_status:{issue.id}:in_progress")],
                [InlineKeyboardButton(text="✅ تم الحل", callback_data=f"admin:bot_issue_status:{issue.id}:resolved", style="success")],
                [InlineKeyboardButton(text="↩️ البلاغات", callback_data="admin:bot_issues")],
            ]
        ),
    )
    if issue.file_id:
        try:
            if issue.file_type == "photo":
                await callback.message.answer_photo(issue.file_id)
            elif issue.file_type == "video":
                await callback.message.answer_video(issue.file_id)
            else:
                await callback.message.answer_document(issue.file_id)
        except Exception:
            pass


@router.callback_query(F.data.startswith("admin:bot_issue_status:"))
async def admin_bot_issue_status(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    parts = (callback.data or "").split(":")
    issue = await session.get(BotIssueReport, int(parts[2]))
    status = parts[3]
    if not issue or status not in {"in_progress", "resolved"}:
        return
    issue.status = status
    issue.updated_at = datetime.now(UTC)
    await callback_notice(callback, "تم التحديث ✅", show_alert=True)
    await edit_or_send(callback.message, "تم تحديث حالة البلاغ.", reply_markup=admin_back())
