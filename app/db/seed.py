from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Category,
    FeatureFlag,
    MenuButtonConfig,
    PlanEntitlement,
    SubscriptionPlan,
    SupportFAQ,
    SystemSetting,
)

DEFAULT_MENU = [
    (
        "services",
        "🛍 الاشتراكات والخدمات",
        "services",
        "primary",
        1,
        1,
        ["user", "provider", "admin"],
    ),
    ("account", "👤 حسابي", "account", "success", 1, 2, ["user", "provider", "admin"]),
    ("profile", "🪪 معلوماتي", "profile", "success", 1, 1, ["user", "provider", "admin"]),
    ("orders", "📦 طلباتي", "orders", "primary", 2, 1, ["user", "provider", "admin"]),
    (
        "subscriptions",
        "📅 اشتراكاتي",
        "subscriptions",
        "success",
        2,
        2,
        ["user", "provider", "admin"],
    ),
    ("offers", "🔥 العروض الطلابية", "offers", "danger", 3, 1, ["user", "provider", "admin"]),
    ("points", "🌟 نظام الحالة والمكافآت", "points", "success", 3, 2, ["user", "provider", "admin"]),
    ("reward_tasks", "💰 اكسب رصيد مجاني", "earn", "success", 4, 1, ["user", "provider", "admin"]),
    ("favorites", "❤️ مفضلاتي", "favorites", "danger", 4, 2, ["user", "provider", "admin"]),
    (
        "missing",
        "➕ طلب خدمة غير موجودة",
        "missing",
        "primary",
        4,
        2,
        ["user", "provider", "admin"],
    ),
    ("help", "💬 مركز المساعدة", "help", "success", 5, 1, ["user", "provider", "admin"]),
    ("provider", "🏢 لوحة المنصة", "provider_dashboard", "primary", 6, 1, ["provider", "admin"]),
    ("admin", "🛡 لوحة الإدارة", "admin_dashboard", "danger", 6, 2, ["admin"]),
]

DEFAULT_FAQS = [
    (
        "🔑",
        "الرمز لا يعمل",
        "تأكد من إدخال الرمز دون مسافات وفي نفس الحساب المرتبط بالطلب. لا تطلب رمزًا جديدًا قبل تجربة الرمز مرة واحدة.",
        "code",
    ),
    (
        "⏳",
        "انتهت صلاحية الرمز",
        "اضغط طلب رمز جديد من صفحة الطلب. يسمح النظام بعدد محدود من المحاولات ثم يحول الطلب للمزود.",
        "code",
    ),
    (
        "📧",
        "لم يصل التفعيل",
        "تحقق من البريد غير المرغوب فيه وتأكد أن البريد المسجل في الطلب صحيح.",
        "activation",
    ),
    (
        "🔐",
        "الحساب يطلب رمزًا جديدًا",
        "ارجع إلى صفحة الطلب واضغط طلب رمز جديد. لن يعيد البوت إرسال الرمز القديم.",
        "account",
    ),
    (
        "🚫",
        "الحساب لا يفتح",
        "تحقق من بيانات الدخول وعدد الأجهزة. إذا استمرت المشكلة افتح تذكرة مرتبطة بالطلب.",
        "account",
    ),
    (
        "💳",
        "مشكلة بالدفع",
        "صورة التحويل وحدها لا تعني المصادقة. انتظر تدقيق المسؤول أو أرسل رقم العملية والمبلغ.",
        "payment",
    ),
]

DEFAULT_CATEGORIES = [
    ("📚", "منصات تعليمية"),
    ("🧠", "أدوات الذكاء الاصطناعي"),
    ("💻", "برامج وتطبيقات"),
    ("🎨", "تصميم ومونتاج"),
    ("📝", "خدمات طلابية"),
    ("🎮", "ترفيه وألعاب"),
]


DEFAULT_PLANS = [
    {
        "code": "free",
        "name_ar": "المجانية",
        "name_en": "Free",
        "description": "للبداية وإدارة الطلبات الأساسية.",
        "price_iqd": 0,
        "billing_days": 30,
        "grace_days": 3,
        "sort_order": 1,
        "features": {
            "orders.view": (True, None),
            "payments.review": (True, None),
            "support.manage": (True, None),
            "withdrawals.request": (True, None),
            "sales.accept": (True, None),
            "offers.manage": (True, None),
            "inventory.manage": (False, None),
            "emails.manage": (False, None),
            "reports.basic": (True, None),
            "reports.advanced": (False, None),
            "reports.export": (False, None),
            "staff.manage": (True, None),
            "broadcasts.send": (False, None),
            "gemini.support": (False, None),
            "api.access": (False, None),
            "offers.max": (True, 10),
            "staff.max": (True, 1),
            "reports.monthly": (True, 1),
            "emails.max": (True, 0),
            "broadcasts.monthly": (True, 0),
            "orders.monthly": (True, 500),
            "report_history_days": (True, 7),
        },
    },
    {
        "code": "lite",
        "name_ar": "Reports Lite",
        "name_en": "Reports Lite",
        "description": "تقارير HTML وهوية المنصة وحدود أكبر.",
        "price_iqd": 2000,
        "billing_days": 30,
        "grace_days": 3,
        "sort_order": 2,
        "features": {
            "orders.view": (True, None),
            "payments.review": (True, None),
            "support.manage": (True, None),
            "withdrawals.request": (True, None),
            "sales.accept": (True, None),
            "offers.manage": (True, None),
            "inventory.manage": (True, None),
            "emails.manage": (True, None),
            "reports.basic": (True, None),
            "reports.advanced": (True, None),
            "reports.export": (False, None),
            "staff.manage": (True, None),
            "broadcasts.send": (False, None),
            "gemini.support": (False, None),
            "api.access": (False, None),
            "offers.max": (True, 100),
            "staff.max": (True, 3),
            "reports.monthly": (True, 4),
            "emails.max": (True, 10),
            "broadcasts.monthly": (True, 0),
            "orders.monthly": (True, 5000),
            "report_history_days": (True, 90),
        },
    },
    {
        "code": "pro",
        "name_ar": "الاحترافية",
        "name_en": "Pro",
        "description": "جميع أدوات الإدارة والتقارير والتكاملات المتقدمة.",
        "price_iqd": 10000,
        "billing_days": 30,
        "grace_days": 5,
        "sort_order": 3,
        "features": {
            "orders.view": (True, None),
            "payments.review": (True, None),
            "support.manage": (True, None),
            "withdrawals.request": (True, None),
            "sales.accept": (True, None),
            "offers.manage": (True, None),
            "inventory.manage": (True, None),
            "emails.manage": (True, None),
            "reports.basic": (True, None),
            "reports.advanced": (True, None),
            "reports.export": (True, None),
            "staff.manage": (True, None),
            "broadcasts.send": (True, None),
            "gemini.support": (True, None),
            "api.access": (True, None),
            "offers.max": (True, -1),
            "staff.max": (True, 20),
            "reports.monthly": (True, -1),
            "emails.max": (True, -1),
            "broadcasts.monthly": (True, 10),
            "orders.monthly": (True, -1),
            "report_history_days": (True, 365),
        },
    },
]

DEFAULT_FLAGS = [
    ("gemini", True, "المساعد الذكي للأسئلة المخصصة"),
    ("email_codes", False, "التقاط أكواد التحقق من الإيميلات"),
    ("mastercard", True, "الدفع ببطاقات Mastercard عبر بوابة خارجية"),
    ("reports", True, "تقارير HTML"),
    ("referrals", True, "نظام الحالة والمكافآت"),
    ("reward_tasks", False, "نظام المهام مقابل رصيد المحفظة"),
    ("colored_buttons", True, "ألوان أزرار Telegram"),
    ("maintenance", False, "وضع الصيانة"),
]


async def seed_defaults(session: AsyncSession) -> None:
    existing_menu_keys = {
        key for key in (await session.scalars(select(MenuButtonConfig.key))).all()
    }
    for key, text, action, style, row, position, roles in DEFAULT_MENU:
        if key in existing_menu_keys:
            continue
        session.add(
            MenuButtonConfig(
                key=key,
                text=text,
                action=action,
                style=style,
                row_number=row,
                position=position,
                role_scope=roles,
            )
        )
    if not (await session.scalar(select(SupportFAQ.id).limit(1))):
        session.add_all(
            [
                SupportFAQ(emoji=e, question=q, answer=a, category=c, sort_order=i)
                for i, (e, q, a, c) in enumerate(DEFAULT_FAQS)
            ]
        )
    if not (await session.scalar(select(Category.id).limit(1))):
        session.add_all(
            [
                Category(emoji=emoji, name=name, sort_order=i)
                for i, (emoji, name) in enumerate(DEFAULT_CATEGORIES)
            ]
        )
    existing_plans = {x for x in (await session.scalars(select(SubscriptionPlan.code))).all()}
    for plan_data in DEFAULT_PLANS:
        if plan_data["code"] in existing_plans:
            continue
        feature_data = plan_data["features"]
        plan = SubscriptionPlan(
            code=plan_data["code"],
            name_ar=plan_data["name_ar"],
            name_en=plan_data["name_en"],
            description=plan_data["description"],
            price_iqd=plan_data["price_iqd"],
            billing_days=plan_data["billing_days"],
            grace_days=plan_data["grace_days"],
            sort_order=plan_data["sort_order"],
            is_system=True,
        )
        session.add(plan)
        await session.flush()
        session.add_all(
            [
                PlanEntitlement(
                    plan_id=plan.id,
                    feature_key=key,
                    is_enabled=enabled,
                    limit_value=limit_value,
                )
                for key, (enabled, limit_value) in feature_data.items()
            ]
        )

    existing_flags = {x for x in (await session.scalars(select(FeatureFlag.key))).all()}
    for key, enabled, description in DEFAULT_FLAGS:
        if key not in existing_flags:
            session.add(FeatureFlag(key=key, is_enabled=enabled, description=description))
    if not await session.scalar(
        select(SystemSetting.id).where(SystemSetting.key == "service_fee_iqd")
    ):
        session.add(SystemSetting(key="service_fee_iqd", value="500"))
    await session.commit()
