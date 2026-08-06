from __future__ import annotations

from functools import wraps
from typing import Callable

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import CallbackPayloadError, MAX_CALLBACK_BYTES, callback_size
from app.domain.student_commerce import format_offer_button
from app.bot.ui.button_styles import apply_button_style_policy


def validate_callback_markup(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    """Validate every outgoing callback payload before Telegram sees it.

    Dynamic IDs and legacy callback formats can silently grow over time.  This
    guard turns Telegram's vague ``BUTTON_DATA_INVALID`` response into a local,
    actionable exception during rendering/tests.
    """

    if markup is None:
        return None
    markup = apply_button_style_policy(markup)
    for row in markup.inline_keyboard:
        for button in row:
            value = button.callback_data
            if value is not None and callback_size(value) > MAX_CALLBACK_BYTES:
                raise CallbackPayloadError(
                    f"callback_data exceeds {MAX_CALLBACK_BYTES} bytes: {value!r}"
                )
    return markup


def with_navigation(
    markup: InlineKeyboardMarkup | None = None,
    *,
    back_callback: str = "nav:back",
    include_back: bool = True,
    include_home: bool = True,
) -> InlineKeyboardMarkup:
    """Return a validated keyboard with one stable navigation footer.

    Existing back/home buttons are preserved and never duplicated.  The helper
    is intentionally idempotent because the same menu can be re-rendered after
    a database update.
    """

    rows = [list(row) for row in (markup.inline_keyboard if markup else [])]
    buttons = [button for row in rows for button in row]
    has_back = any(
        "رجوع" in button.text or "تراجع" in button.text or "↩️" in button.text
        for button in buttons
    )
    has_home = any(
        "الرئيسية" in button.text or "🏠" in button.text
        for button in buttons
    )
    footer: list[InlineKeyboardButton] = []
    if include_back and not has_back:
        footer.append(InlineKeyboardButton(text="↩️ رجوع", callback_data=back_callback))
    if include_home and not has_home:
        footer.append(InlineKeyboardButton(text="🏠 الرئيسية", callback_data="back_to_main"))
    if footer:
        rows.append(footer)
    return validate_callback_markup(InlineKeyboardMarkup(inline_keyboard=rows))  # type: ignore[return-value]


def navigable_keyboard(
    factory: Callable[..., InlineKeyboardMarkup],
) -> Callable[..., InlineKeyboardMarkup]:
    """Ensure reusable inline keyboards never create a dead-end screen.

    The initial terms/consent keyboard is intentionally excluded; every other
    reusable keyboard receives an idempotent Back/Home footer and payload
    validation even when it is sent directly with ``message.answer``.
    """

    @wraps(factory)
    def wrapped(*args, **kwargs) -> InlineKeyboardMarkup:
        return with_navigation(factory(*args, **kwargs))

    return wrapped


def terms_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📄 الشروط والخصوصية", callback_data="terms:view", style="primary"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ أوافق وأبدأ التسجيل", callback_data="terms:accept", style="success"
                )
            ],
        ]
    )


def platform_terms_keyboard() -> InlineKeyboardMarkup:
    """One-time platform-owner consent barrier; no unrelated navigation buttons."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ أوافق وأبدأ العمل",
                    callback_data="provider:terms:accept",
                    style="success",
                ),
                InlineKeyboardButton(
                    text="❌ لا أوافق",
                    callback_data="provider:terms:reject",
                    style="danger",
                ),
            ]
        ]
    )


@navigable_keyboard
def back_keyboard(callback_data: str = "nav:back") -> InlineKeyboardMarkup:
    return with_navigation(
        InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="↩️ رجوع", callback_data=callback_data)]]
        ),
        back_callback=callback_data,
    )


@navigable_keyboard
def categories_keyboard(categories: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in categories:
        builder.button(
            text=f"{item.emoji} {item.name}", callback_data=f"cat:{item.id}", style="primary"
        )
    builder.button(text="❤️ المفضلة", callback_data="favorites:list", style="primary")
    builder.adjust(2)
    return builder.as_markup()


@navigable_keyboard
def offers_keyboard(offers: list, back: str = "catalog:categories") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in offers:
        builder.button(
            text=format_offer_button(
                service_name=item.title,
                duration_label=(
                    "شهر واحد" if item.duration_days == 30 else
                    "3 أشهر" if item.duration_days == 90 else
                    "سنة" if item.duration_days == 365 else
                    f"{item.duration_days} يوم" if item.duration_days else "حسب العرض"
                ),
                price_iqd=item.price_iqd,
            ),
            callback_data=f"offer:{item.id}",
            style="primary",
        )
    builder.button(text="↩️ رجوع", callback_data=back)
    builder.adjust(1)
    return builder.as_markup()


@navigable_keyboard
def offer_keyboard(
    offer_id: int,
    back: str = "catalog:categories",
    *,
    friends_enabled: bool = False,
) -> InlineKeyboardMarkup:
    rows = [
            [
                InlineKeyboardButton(
                    text="📖 طريقة التسجيل والتفعيل",
                    callback_data=f"guide:view:offer:{offer_id}",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛒 اشترك الآن", callback_data=f"buy:{offer_id}", style="success"
                )
            ],
    ]
    if friends_enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🤝 باقة أصدقائي فقط",
                    callback_data=f"friend:create:{offer_id}",
                    style="primary",
                )
            ]
        )
    rows.extend([
            [
                InlineKeyboardButton(
                    text="❤️ إضافة للمفضلة", callback_data=f"favorite:offer:{offer_id}", style="danger"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏢 معلومات المنصة", callback_data=f"provider:info:{offer_id}"
                )
            ],
            [InlineKeyboardButton(text="↩️ رجوع", callback_data=back)],
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@navigable_keyboard
def purchase_confirmation_keyboard(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ أوافق وأنشئ الطلب",
                    callback_data=f"purchase:confirm:{offer_id}",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ إعادة إدخال البيانات",
                    callback_data=f"purchase:restart:{offer_id}",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ إلغاء",
                    callback_data="purchase:cancel",
                    style="danger",
                )
            ],
        ]
    )


@navigable_keyboard
def coupon_prompt_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎟 نعم، لدي كود خصم",
                    callback_data=f"coupon:apply:{order_id}",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(
                    text="➡️ لا، متابعة الدفع",
                    callback_data=f"coupon:skip:{order_id}",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ إلغاء الطلب",
                    callback_data=f"order:cancel:{order_id}",
                    style="danger",
                )
            ],
        ]
    )


@navigable_keyboard
def payment_methods_keyboard(methods: list, order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for method in methods:
        builder.button(
            text=f"{method.icon} {method.name}",
            callback_data=f"paymethod:{order_id}:{method.id}",
            style="primary",
        )
    builder.button(text="🎟 كود خصم", callback_data=f"coupon:apply:{order_id}", style="success")
    builder.button(text="❌ إلغاء الطلب", callback_data=f"order:cancel:{order_id}", style="danger")
    builder.adjust(1)
    return builder.as_markup()


@navigable_keyboard
def manual_payment_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 رفعت التحويل", callback_data=f"proof:start:{order_id}", style="success"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❓ كيف أستخرج الوصل؟", callback_data=f"proof:guide:{order_id}", style="primary"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ إلغاء الطلب", callback_data=f"order:cancel:{order_id}", style="danger"
                )
            ],
        ]
    )


@navigable_keyboard
def order_actions_keyboard(order, allow_code: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if allow_code and order.status in {"delivered", "waiting_code", "needs_support"}:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔑 طلب رمز التحقق",
                    callback_data=f"code:new:{order.id}",
                    style="primary",
                )
            ]
        )
    if order.status == "delivered":
        if not getattr(order, "delivery_acknowledged_at", None):
            rows.extend(
                [
                    [
                        InlineKeyboardButton(
                            text="📥 استلمت بيانات الخدمة",
                            callback_data=f"order:ack_delivery:{order.id}",
                            style="success",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="❌ لم تصلني البيانات / ناقصة",
                            callback_data=f"order:problem:{order.id}",
                            style="danger",
                        )
                    ],
                ]
            )
        else:
            rows.extend(
                [
                    [
                        InlineKeyboardButton(
                            text="✅ جرّبت ونجح التفعيل",
                            callback_data=f"order:complete:{order.id}",
                            style="success",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="❌ توجد مشكلة في التفعيل",
                            callback_data=f"order:problem:{order.id}",
                            style="danger",
                        )
                    ],
                ]
            )
    if order.status in {"delivered", "completed", "needs_support"}:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🎧 دعم مباشر مع المزود",
                    callback_data=f"support:direct:{order.id}",
                    style="danger",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="💬 مركز المساعدة", callback_data=f"support:order:{order.id}")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@navigable_keyboard
def rating_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{rating} ⭐",
                    callback_data=f"review:rate:{order_id}:{rating}",
                    style="success" if rating >= 4 else "primary",
                )
                for rating in range(1, 6)
            ]
        ]
    )


@navigable_keyboard
def payment_review_keyboard(order_id: int, amount_iqd: int | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=(f"✅ تأكيد استلام ({amount_iqd:,})" if amount_iqd is not None else "✅ تأكيد الاستلام"),
                    callback_data=f"review:confirm:{order_id}",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ رفض الوصل مع سبب", callback_data=f"review:reject:{order_id}", style="danger"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔎 فتح الطلب", callback_data=f"admin:order:{order_id}", style="primary"
                )
            ],
        ]
    )


@navigable_keyboard
def payment_confirm_keyboard(order_id: int, amount_iqd: int | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=(f"✅ نعم، تأكيد ({amount_iqd:,} د.ع)" if amount_iqd is not None else "✅ نعم، تأكيد نهائي"),
                    callback_data=f"review:final:{order_id}",
                    style="success",
                )
            ],
            [InlineKeyboardButton(text="↩️ تراجع", callback_data=f"admin:order:{order_id}")],
        ]
    )


@navigable_keyboard
def support_faq_keyboard(faqs: list, order_id: int | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for faq in faqs:
        suffix = f":{order_id}" if order_id else ""
        builder.button(text=f"{faq.emoji} {faq.question}", callback_data=f"faq:{faq.id}{suffix}")
    builder.button(
        text="❓ سؤال مخصص", callback_data=f"support:custom:{order_id or 0}", style="primary"
    )
    builder.button(
        text="🐞 الإبلاغ عن مشكلة في البوت",
        callback_data="bot_issue:start",
        style="danger",
    )
    builder.button(text="🎫 تذاكري", callback_data="tickets:mine")
    builder.adjust(1)
    return builder.as_markup()


@navigable_keyboard
def solved_keyboard(order_id: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تم حل المشكلة", callback_data="support:solved", style="success"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ لم تُحل", callback_data=f"support:unresolved:{order_id}", style="danger"
                )
            ],
        ]
    )


def ai_support_result_keyboard(job_id: int, *, failed: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if not failed:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ تم حل المشكلة", callback_data="support:solved", style="success"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="🎫 فتح تذكرة دعم",
                callback_data=f"support:aiunresolved:{int(job_id)}",
                style="danger" if failed else "primary",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@navigable_keyboard
def admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    """Compact owner dashboard: two actions per row, inline-only."""

    rows = [
        [("📊 نظرة عامة", "admin:stats", "primary"), ("🏢 المنصات", "admin:providers", "success")],
        [("🛍 العروض", "admin:offers", "primary"), ("📦 الطلبات", "admin:orders", "primary")],
        [("💳 المدفوعات", "admin:payments", "danger"), ("📧 الإيميلات", "admin:emails", "primary")],
        [("🔑 المخزون", "admin:inventory", "success"), ("📊 التقارير", "admin:reports", "primary")],
        [("💰 المالية", "admin:finance", "success"), ("🏦 السحوبات", "admin:withdrawals", "success")],
        [("🎫 الدعم", "admin:tickets", "primary"), ("📣 الإشعارات", "admin:broadcast", "danger")],
        [("🎛 واجهة الأزرار", "admin:menu_manager", "primary"), ("👁 معاينة الواجهة", "admin:menu_preview", "success")],
        [("📁 مكتبة الملفات", "admin:media", "primary"), ("🧩 الميزات", "admin:features", "success")],
        [("✍️ تعديل رسالة /start", "admin:start_message", "primary"), ("🩺 صحة النظام", "admin:health", "success")],
        [("📝 قوالب الرسائل", "admin:message_templates", "primary"), ("📦 باقات المنصات", "admin:plans", "primary")],
        [("🎟 كوبونات المنصات", "admin:coupons", "success"), ("👨‍💼 موظفو المنصات", "admin:staff", "primary")],
        [("⚙️ الإعدادات", "admin:settings", "primary"), ("💰 الأسعار والخصائص", "admin:prices", "success")],
        [("🏢 مركز التجارة والسيادة", "admin:owner_commerce", "success")],
        [("📌 الإعلانات المثبتة", "admin:announcements", "danger"), ("🧱 ترتيب القوائم", "admin:menu_builder", "primary")],
        [("🐞 بلاغات البوت", "admin:bot_issues", "danger"), ("👥 المستخدمون والحظر", "admin:users", "danger")],
        [("ℹ️ معلومات النظام", "admin:system_info", "primary")],
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t, callback_data=c, style=s) for t, c, s in row]
            for row in rows
        ]
    )


@navigable_keyboard
def provider_dashboard_keyboard(access=None) -> InlineKeyboardMarkup:
    """Provider dashboard filtered by effective permissions.

    ``access`` is intentionally duck-typed to keep this keyboard module free of
    service-layer imports. OWNER and SUPER_ADMIN contexts already contain all
    effective permissions. Legacy callers without a context retain the complete
    dashboard until they are migrated.
    """

    effective = set(getattr(access, "effective_permissions", ()) or ()) if access is not None else None

    def allowed(permission: str | None) -> bool:
        return effective is None or permission is None or permission in effective

    actions = [
        ("📥 بريد الطلبات والإثباتات", "provider:inbox", "danger", "can_support"),
        ("🛍 متجري والعروض", "provider:catalog", "success", "can_manage_offers"),
        ("📦 الطلبات", "provider:orders", "primary", "can_review_payments"),
        ("💳 تدقيق المدفوعات", "provider:payments", "danger", "can_review_payments"),
        ("💳 طرق الدفع", "provider:payment_methods", "primary", "can_manage_payout_accounts"),
        ("🕒 ساعات العمل", "provider:working_hours", "primary", "can_manage_offers"),
        ("📊 طلب تقرير", "provider:report", "success", "can_view_reports"),
        ("💰 أرباح المنصة وسحب الرصيد", "provider:finance", "success", "can_view_finance"),
        ("📨 حسابات البريد وOTP", "provider:emails", "primary", "can_manage_inventory"),
        ("🎧 الدعم", "provider:tickets", "primary", "can_support"),
        ("💼 اشتراكي", "provider:subscription", "success", None),
        ("🎟 استخدام كوبون", "provider:coupon", "primary", None),
        ("📢 طلب إعلان", "provider:ad_request", "primary", "can_manage_offers"),
        ("🎟 إطلاق أكواد للطلاب", "provider:coupon_campaign", "success", "can_manage_offers"),
        ("🧾 رسوم البوت والفواتير", "provider:billing", "danger", "can_view_finance"),
        ("🖼 شعار المنصة", "provider:branding", "success", "can_manage_branding"),
        ("🛡 مخزون يحتاج معالجة", "provider:remediations", "danger", "can_manage_inventory"),
        ("🔄 تغيير المنصة", "provider:choose", "primary", None),
    ]
    visible = [(t, c, st) for t, c, st, permission in actions if allowed(permission)]
    rows = [visible[index:index + 2] for index in range(0, len(visible), 2)]
    rows.append([("🏠 الرئيسية", "back_to_main", "primary")])
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t, callback_data=c, style=style) for t, c, style in row]
            for row in rows
        ]
    )



@navigable_keyboard
def menu_buttons_keyboard(buttons: list, operation: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in buttons:
        builder.button(
            text=item.text,
            callback_data=f"admin:{operation}:{item.id}",
            style=item.style if item.style != "default" else None,
        )
    builder.button(text="↩️ لوحة الإدارة", callback_data="admin:home")
    builder.adjust(1)
    return builder.as_markup()


@navigable_keyboard
def style_keyboard(key: str | int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔵 أزرق", callback_data=f"admin:setstyle:{key}:primary", style="primary"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🟢 أخضر", callback_data=f"admin:setstyle:{key}:success", style="success"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔴 أحمر", callback_data=f"admin:setstyle:{key}:danger", style="danger"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚪ افتراضي", callback_data=f"admin:setstyle:{key}:default"
                )
            ],
        ]
    )


@navigable_keyboard
def feature_flags_keyboard(flags: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for flag in flags:
        symbol = "✅" if flag.is_enabled else "❌"
        builder.button(text=f"{symbol} {flag.key}", callback_data=f"admin:flag:{flag.id}")
    builder.button(text="🧩 الإضافات البرمجية", callback_data="admin:plugins", style="primary")
    builder.button(text="↩️ لوحة الإدارة", callback_data="admin:home")
    builder.adjust(1)
    return builder.as_markup()


@navigable_keyboard
def menu_manager_keyboard(buttons: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    surface_icons = {"reply": "⌨️", "inline": "🪟", "both": "🔀", "hidden": "🙈"}
    for item in buttons:
        enabled = "✅" if item.is_enabled else "❌"
        icon = surface_icons.get(item.surface, "⌨️")
        builder.button(
            text=f"{enabled} {icon} {item.text}",
            callback_data=f"admin:menu_button:{item.id}",
            style=item.style if item.style != "default" else None,
        )
    builder.button(
        text="⌨️ توحيد: كيبورد سفلي", callback_data="admin:menu_preset:reply", style="primary"
    )
    builder.button(
        text="🪟 توحيد: داخل الرسائل", callback_data="admin:menu_preset:inline", style="primary"
    )
    builder.button(text="👁 معاينة", callback_data="admin:menu_preview", style="success")
    builder.button(text="↩️ لوحة الإدارة", callback_data="admin:home")
    builder.adjust(1)
    return builder.as_markup()


@navigable_keyboard
def menu_button_editor_keyboard(item) -> InlineKeyboardMarkup:
    toggle_text = "❌ تعطيل الزر" if item.is_enabled else "✅ تفعيل الزر"
    toggle_style = "danger" if item.is_enabled else "success"
    rows = [
            [
                InlineKeyboardButton(
                    text="✏️ تغيير الاسم",
                    callback_data=f"admin:menu_edit_text:{item.id}",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="🎨 تغيير اللون",
                    callback_data=f"admin:menu_edit_style:{item.id}",
                    style="success",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔀 تغيير نوع الزر",
                    callback_data=f"admin:menu_edit_surface:{item.id}",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="🧭 تحريك الزر",
                    callback_data=f"admin:menu_move_panel:{item.id}",
                    style="primary",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=toggle_text,
                    callback_data=f"admin:menu_toggle:{item.id}",
                    style=toggle_style,
                )
            ],
        ]
    if getattr(item, "content_type", "system_action") != "system_action":
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 حذف الزر المخصص",
                    callback_data=f"admin:menu_delete_prompt:{item.id}",
                    style="danger",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="↩️ جميع الأزرار", callback_data="admin:menu_manager")])
    return InlineKeyboardMarkup(inline_keyboard=rows)



@navigable_keyboard
def menu_move_keyboard(key: str | int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬆️", callback_data=f"admin:menu_move:{key}:up", style="primary")],
            [
                InlineKeyboardButton(text="⬅️", callback_data=f"admin:menu_move:{key}:left", style="primary"),
                InlineKeyboardButton(text="👁 معاينة", callback_data="admin:menu_preview", style="success"),
                InlineKeyboardButton(text="➡️", callback_data=f"admin:menu_move:{key}:right", style="primary"),
            ],
            [InlineKeyboardButton(text="⬇️", callback_data=f"admin:menu_move:{key}:down", style="primary")],
            [InlineKeyboardButton(text="✅ تم", callback_data=f"admin:menu_button:{key}", style="success")],
        ]
    )

@navigable_keyboard
def menu_surface_keyboard(key: str | int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⌨️ داخل الكيبورد السفلي",
                    callback_data=f"admin:setsurface:{key}:reply",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🪟 داخل الرسالة (شفاف/داخلي)",
                    callback_data=f"admin:setsurface:{key}:inline",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔀 في المكانين",
                    callback_data=f"admin:setsurface:{key}:both",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🙈 إخفاء الزر",
                    callback_data=f"admin:setsurface:{key}:hidden",
                    style="danger",
                )
            ],
            [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"admin:menu_button:{key}")],
        ]
    )


@navigable_keyboard
def promotion_providers_keyboard(providers: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for provider in providers:
        builder.button(
            text=f"🔥 {provider.name_ar}",
            callback_data=f"promo:provider:{provider.id}",
            style="danger",
        )
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="↩️ رجوع", callback_data="back_to_main"))
    return builder.as_markup()


@navigable_keyboard
def promotion_offers_keyboard(offers: list, provider_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for offer in offers:
        total = int(offer.price_iqd or 0) + int(offer.service_fee_iqd or 0)
        builder.button(
            text=f"🔥 {offer.title} — {total:,} د.ع",
            callback_data=f"offer:{offer.id}:promo:{provider_id}",
            style="danger",
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="↩️ رجوع", callback_data="promo:root"))
    return builder.as_markup()


@navigable_keyboard
def providers_keyboard(providers: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for provider in providers:
        average = float(getattr(provider, "_rating_average", 0) or 0)
        count = int(getattr(provider, "_rating_count", 0) or 0)
        subscribers = int(getattr(provider, "_subscriber_count", 0) or 0)
        stars = getattr(provider, "_rating_stars", "☆☆☆☆☆")
        rating_text = f" {stars} {average:.1f} ({count})" if count else " ☆☆☆☆☆ جديد"
        subscriber_text = f" 👥 {subscribers}" if subscribers else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🏢 {provider.name_ar}{rating_text}{subscriber_text}",
                    callback_data=f"store:provider:{provider.id}",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="❤️",
                    callback_data=f"favorite:provider:{provider.id}",
                    style="danger",
                ),
            ]
        )
    rows.append([InlineKeyboardButton(text="❤️ مفضلاتي", callback_data="favorites:v11", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@navigable_keyboard
def provider_sections_keyboard(sections: list, provider_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for section in sections:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{section.emoji} {section.name}",
                    callback_data=f"store:section:{provider_id}:{section.id}",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="❤️",
                    callback_data=f"favorite:section:{section.id}",
                    style="danger",
                ),
            ]
        )
    rows.append([InlineKeyboardButton(text="↩️ المنصات", callback_data="store:providers")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@navigable_keyboard
def service_items_keyboard(
    services: list, provider_id: int, section_id: int
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in services:
        builder.button(
            text=f"{item.emoji} {item.name}",
            callback_data=f"svc:{item.id}",
            style="primary",
        )
    builder.button(text="↩️ الأقسام", callback_data=f"store:provider:{provider_id}")
    builder.adjust(2)
    return builder.as_markup()


@navigable_keyboard
def service_offers_keyboard(
    offers: list, provider_id: int, section_id: int
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in offers:
        builder.button(
            text=format_offer_button(
                service_name=item.title,
                duration_label=(
                    "شهر واحد" if item.duration_days == 30 else
                    "3 أشهر" if item.duration_days == 90 else
                    "سنة" if item.duration_days == 365 else
                    f"{item.duration_days} يوم" if item.duration_days else "حسب العرض"
                ),
                price_iqd=item.price_iqd,
            ),
            callback_data=f"offer:{item.id}",
            style="primary",
        )
    builder.button(
        text="↩️ الخدمات",
        callback_data=f"store:section:{provider_id}:{section_id}",
    )
    builder.adjust(1)
    return builder.as_markup()


@navigable_keyboard
def profile_webapp_keyboard(url: str, *, complete: bool = False) -> InlineKeyboardMarkup:
    label = "✏️ تعديل معلوماتي" if complete else "📝 إكمال معلوماتي"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url), style="primary")],
        ]
    )


@navigable_keyboard
def favorites_v11_keyboard(grouped: dict[str, list]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for provider in grouped.get("provider", []):
        rows.append([InlineKeyboardButton(
            text=f"🏢 {provider.name_ar}",
            callback_data=f"store:provider:{provider.id}",
            style="primary",
        )])
    for section in grouped.get("section", []):
        rows.append([InlineKeyboardButton(
            text=f"{section.emoji} {section.name}",
            callback_data=f"store:section:{section.provider_id}:{section.id}",
            style="primary",
        )])
    for offer in grouped.get("offer", []):
        rows.append([InlineKeyboardButton(
            text=format_offer_button(
                service_name=offer.title,
                duration_label=(
                    "شهر واحد" if offer.duration_days == 30 else
                    "3 أشهر" if offer.duration_days == 90 else
                    "سنة" if offer.duration_days == 365 else
                    f"{offer.duration_days} يوم" if offer.duration_days else "حسب العرض"
                ),
                price_iqd=offer.price_iqd,
            ),
            callback_data=f"offer:{offer.id}",
            style="primary",
        )])
    if not rows:
        rows.append([InlineKeyboardButton(text="🛍 تصفح المتجر", callback_data="store:providers", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@navigable_keyboard
def subscriptions_keyboard(
    subscriptions: list,
    *,
    filter_key: str = "all",
    page: int = 0,
    total: int | None = None,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    status_icon = {
        "active": "✅",
        "expiring": "⚠️",
        "expired": "⌛",
        "waiting_activation": "⏳",
        "pending": "🕓",
        "needs_support": "🆘",
    }
    for item in subscriptions:
        icon = status_icon.get(item.status, "📅")
        end_text = item.ends_at.strftime("%d/%m/%Y") if item.ends_at else "غير محدد"
        builder.button(
            text=f"{icon} {item.offer_name_snapshot} — {end_text}",
            callback_data=f"subscription:view:{item.id}",
            style="success" if item.status == "active" else "primary",
        )
    builder.adjust(1)
    total_value = len(subscriptions) if total is None else max(0, int(total))
    page = max(0, int(page))
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀️ الأحدث",
                callback_data=f"subscriptions:list:{filter_key}:{page - 1}",
            )
        )
    if (page + 1) * page_size < total_value:
        nav.append(
            InlineKeyboardButton(
                text="الأقدم ▶️",
                callback_data=f"subscriptions:list:{filter_key}:{page + 1}",
            )
        )
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="↩️ أقسام الاشتراكات", callback_data="subscriptions:categories"))
    return builder.as_markup()


@navigable_keyboard
def subscription_details_keyboard(
    subscription,
    allow_code: bool = False,
    *,
    warranty_enabled: bool = False,
) -> InlineKeyboardMarkup:
    rows = []
    if allow_code and subscription.status in {"active", "expiring", "waiting_activation"}:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔑 طلب رمز التحقق",
                    callback_data=f"subscription:code:{subscription.id}",
                    style="primary",
                )
            ]
        )
    if warranty_enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🛠️ المطالبة بالضمان",
                    callback_data=f"warranty:start:{subscription.id}",
                    style="danger",
                )
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="🧾 عرض الوصل",
                    callback_data=f"subscription:receipt:{subscription.id}",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 تجديد الاشتراك",
                    callback_data=f"subscription:renew:{subscription.id}",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎧 دعم مباشر مع المزود",
                    callback_data=f"dispute:subscription:{subscription.id}",
                    style="danger",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💬 الإبلاغ عن مشكلة",
                    callback_data=f"subscription:problem:{subscription.id}",
                    style="danger",
                )
            ],
            [InlineKeyboardButton(text="↩️ اشتراكاتي", callback_data="subscriptions:list")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@navigable_keyboard
def activation_problem_keyboard(order_id: int) -> InlineKeyboardMarkup:
    reasons = [
        ("🔑 الرمز غير صحيح", "invalid_code", "1"),
        ("⏳ انتهت صلاحية الرمز", "expired_code", "2"),
        ("📧 لم يصل رمز جديد", "no_code", "3"),
        ("🔐 البريد أو كلمة المرور لا يعملان", "credentials", "4"),
        ("📱 تجاوز عدد الأجهزة", "devices", "5"),
        ("🚫 الحساب موقوف", "blocked", "6"),
        ("❓ سبب آخر", "other", "7"),
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=f"opr:{order_id}:{token}",
                    style="danger" if reason in {"credentials", "blocked"} else "primary",
                )
            ]
            for text, reason, token in reasons
        ]
    )


@navigable_keyboard
def user_orders_keyboard(
    orders: list,
    *,
    page: int = 0,
    total: int | None = None,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    status_icons = {
        "waiting_payment": "💳",
        "payment_review": "🔎",
        "payment_rejected": "❌",
        "paid": "✅",
        "waiting_fulfillment": "⏳",
        "processing": "🛠",
        "delivered": "📨",
        "completed": "🎉",
        "needs_support": "🆘",
        "cancelled": "🚫",
        "refunded": "↩️",
        "disputed": "⚖️",
    }
    for order in orders:
        icon = status_icons.get(order.status, "📦")
        title = order.offer.title if getattr(order, "offer", None) else order.public_id
        builder.button(
            text=f"{icon} {title} — {order.public_id}",
            callback_data=f"order:view:{order.id}",
            style="primary"
            if order.status not in {"payment_rejected", "needs_support"}
            else "danger",
        )
    builder.adjust(1)
    total_value = len(orders) if total is None else max(0, int(total))
    page = max(0, int(page))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ الأحدث", callback_data=f"orders:list:{page - 1}"))
    if (page + 1) * page_size < total_value:
        nav.append(InlineKeyboardButton(text="الأقدم ▶️", callback_data=f"orders:list:{page + 1}"))
    if nav:
        builder.row(*nav)
    return builder.as_markup()


@navigable_keyboard
def user_order_details_keyboard(order, has_subscription: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if order.status in {"waiting_payment", "payment_rejected"}:
        rows.append(
            [
                InlineKeyboardButton(
                    text="❌ إلغاء الطلب",
                    callback_data=f"order:cancel:{order.id}",
                    style="danger",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="📖 طريقة التسجيل والتفعيل",
                callback_data=f"guide:view:order:{order.id}",
                style="primary",
            )
        ]
    )
    if order.status == "delivered":
        rows.extend(order_actions_keyboard(order).inline_keyboard[:-1])
    if order.status == "completed":
        rows.append(
            [
                InlineKeyboardButton(
                    text="🎧 دعم مباشر مع المزود",
                    callback_data=f"support:direct:{order.id}",
                    style="danger",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="⭐ قيّم الطلب",
                    callback_data=f"review:open:{order.id}",
                    style="success",
                )
            ]
        )
    if has_subscription:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📅 فتح الاشتراك",
                    callback_data=f"order:subscription:{order.id}",
                    style="success",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="💬 الدعم", callback_data=f"support:order:{order.id}", style="primary"
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="↩️ طلباتي", callback_data="orders:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@navigable_keyboard
def provider_orders_keyboard(orders: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        style = "danger" if order.status in {"payment_review", "needs_support"} else "primary"
        builder.button(
            text=f"{order.public_id} — {order.status}",
            callback_data=f"provider:order:{order.id}",
            style=style,
        )
    builder.adjust(1)
    return builder.as_markup()


@navigable_keyboard
def provider_contexts_keyboard(staff_rows: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in staff_rows:
        provider = getattr(item, "provider", None)
        provider_id = getattr(item, "provider_id", None) or getattr(provider, "id", None)
        provider_name = getattr(item, "provider_name", None) or getattr(provider, "name_ar", None)
        if not provider_id or not provider_name:
            continue
        average = float(getattr(provider, "_rating_average", 0) or 0) if provider else 0.0
        count = int(getattr(provider, "_rating_count", 0) or 0) if provider else 0
        stars = getattr(provider, "_rating_stars", "☆☆☆☆☆") if provider else "☆☆☆☆☆"
        rating_text = f" {stars} {average:.1f} ({count})" if count else ""
        status = getattr(item, "provider_status", None)
        paused = " ⏸" if status and status != "active" else ""
        builder.button(
            text=f"🏢 {provider_name}{rating_text}{paused}",
            callback_data=f"provider:select:{int(provider_id)}",
            style="primary",
        )
    builder.adjust(1)
    return builder.as_markup()



@navigable_keyboard
def subscription_categories_keyboard(counts: dict[str, int]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✅ الفعالة ({counts.get('active', 0)})",
                    callback_data="subscriptions:list:active",
                    style="success",
                ),
                InlineKeyboardButton(
                    text=f"⚠️ تنتهي قريبًا ({counts.get('expiring', 0)})",
                    callback_data="subscriptions:list:expiring",
                    style="danger",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"⏳ بانتظار التفعيل ({counts.get('pending', 0)})",
                    callback_data="subscriptions:list:pending",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"⌛ المنتهية ({counts.get('expired', 0)})",
                    callback_data="subscriptions:list:expired",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"📅 جميع الاشتراكات ({counts.get('all', 0)})",
                    callback_data="subscriptions:list:all",
                    style="primary",
                )
            ],
        ]
    )


@navigable_keyboard
def dispute_reasons_keyboard(order_id: int) -> InlineKeyboardMarkup:
    reasons = [
        ("🔐 بيانات الدخول لا تعمل", "credentials"),
        ("📦 لم أستلم الخدمة", "not_received"),
        ("❌ الخدمة مختلفة عن الوصف", "wrong_service"),
        ("⏳ انتهت أو توقفت بسرعة", "early_expiry"),
        ("💳 مشكلة دفع أو مبلغ", "payment"),
        ("❓ سبب آخر", "other"),
    ]
    rows = [
        [
            InlineKeyboardButton(
                text=text,
                callback_data=f"dispute:reason:{order_id}:{code}",
                style="danger" if code in {"credentials", "not_received"} else "primary",
            )
        ]
        for text, code in reasons
    ]
    rows.append([InlineKeyboardButton(text="↩️ رجوع", callback_data=f"order:view:{order_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@navigable_keyboard
def user_disputes_keyboard(
    disputes: list,
    *,
    page: int = 0,
    total: int | None = None,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    icon = {
        "open": "🆕",
        "under_review": "🔎",
        "waiting_user": "👤",
        "waiting_provider": "🏢",
        "resolved": "✅",
        "rejected": "❌",
        "cancelled": "🚫",
        "closed": "🔒",
    }
    builder = InlineKeyboardBuilder()
    for item in disputes:
        builder.button(
            text=f"{icon.get(item.status, '⚖️')} {item.public_id}",
            callback_data=f"dispute:view:{item.id}",
            style="primary",
        )
    builder.adjust(1)
    total_value = len(disputes) if total is None else max(0, int(total))
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ الأحدث", callback_data=f"disputes:mine:{page - 1}"))
    if (page + 1) * page_size < total_value:
        nav.append(InlineKeyboardButton(text="الأقدم ➡️", callback_data=f"disputes:mine:{page + 1}"))
    rows = [list(row) for row in builder.as_markup().inline_keyboard]
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔎 البحث برقم النزاع", callback_data="disputes:search_help")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@navigable_keyboard
def dispute_details_keyboard(dispute, refund=None, is_user: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if is_user and dispute.status in {"open", "waiting_user"} and refund is None:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🚫 إلغاء النزاع",
                    callback_data=f"dispute:cancel:{dispute.id}",
                    style="danger",
                )
            ]
        )
    if is_user and refund is not None and refund.status == "transfer_reported":
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ استلمت مبلغ الاسترجاع",
                    callback_data=f"refund:confirm:{refund.id}",
                    style="success",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="💬 فتح التذكرة", callback_data=f"ticket:view:{dispute.support_ticket_id}")])
    rows.append([InlineKeyboardButton(text="↩️ نزاعاتي", callback_data="disputes:mine:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@navigable_keyboard
def provider_disputes_keyboard(disputes: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in disputes:
        builder.button(
            text=f"⚖️ {item.public_id} — {item.status}",
            callback_data=f"provider:dispute:{item.id}",
            style="danger" if item.status in {"open", "under_review"} else "primary",
        )
    builder.adjust(1)
    return builder.as_markup()


@navigable_keyboard
def provider_dispute_actions_keyboard(dispute, refund=None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if getattr(dispute, "evidence_asset_id", None):
        rows.append([
            InlineKeyboardButton(
                text="📎 عرض دليل النزاع",
                callback_data=f"provider:dispute:evidence:{dispute.id}",
                style="primary",
            )
        ])
    if dispute.status in {"open", "under_review", "waiting_provider"} and refund is None:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        text="💰 استرجاع كامل",
                        callback_data=f"provider:dispute:refund_full:{dispute.id}",
                        style="danger",
                    ),
                    InlineKeyboardButton(
                        text="💵 استرجاع جزئي",
                        callback_data=f"provider:dispute:refund_partial:{dispute.id}",
                        style="primary",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="➕ تمديد الاشتراك",
                        callback_data=f"provider:dispute:extend:{dispute.id}",
                        style="success",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ رفض مع توضيح",
                        callback_data=f"provider:dispute:reject:{dispute.id}",
                        style="danger",
                    )
                ],
            ]
        )
    if refund is not None and refund.status == "approved":
        rows.append(
            [
                InlineKeyboardButton(
                    text="📤 تسجيل تحويل الاسترجاع",
                    callback_data=f"provider:refund:transfer:{refund.id}",
                    style="success",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="↩️ النزاعات", callback_data="provider:disputes")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@navigable_keyboard
def provider_remediations_keyboard(items: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        label = getattr(item, "_dispute_public", f"#{item.dispute_id}")
        builder.button(
            text=f"🔄 {label} — {item.status}",
            callback_data=f"provider:remediation:{item.id}",
            style="danger",
        )
    builder.adjust(1)
    return builder.as_markup()


@navigable_keyboard
def provider_remediation_actions_keyboard(item) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تم تدوير بيانات المورد",
                    callback_data=f"provider:remediation:rotated:{item.id}",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 تم إتلاف المورد نهائياً",
                    callback_data=f"provider:remediation:retired:{item.id}",
                    style="danger",
                )
            ],
            [InlineKeyboardButton(text="↩️ القائمة", callback_data="provider:remediations")],
        ]
    )
