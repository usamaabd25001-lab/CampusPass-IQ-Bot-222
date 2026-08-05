from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.bot.handlers.admin.common import admin_back, require_admin, show_admin_home
from app.bot.ui import edit_or_send, callback_notice
from app.core.config import Settings
from app.core.utils import safe
from app.db.models import (
    DeliveryJob,
    DeliveryJobStatus,
    EmailAccount,
    InventoryItem,
    Notification,
    Offer,
    Order,
    OrderStatus,
    Provider,
    RuntimeIncident,
    RuntimeIncidentStatus,
    SchemaMigration,
    SupportTicket,
    User,
)

router = Router(name="admin_core")


def _health_lines(snapshot: dict) -> list[str]:
    status_icon = {"ok": "✅", "warning": "⚠️", "error": "❌"}
    delivery = snapshot["delivery_jobs"]
    notifications = snapshot["notifications"]
    commercial = snapshot["commercial_safety"]
    evidence = snapshot.get("evidence", {})
    operations = snapshot.get("operations", {})
    release = operations.get("release", {})
    backup = operations.get("backup", {})
    runtime = snapshot.get("runtime", {})
    redis_check = snapshot.get("redis", {})
    telegram_check = snapshot.get("telegram", {})
    return [
        f"🩺 <b>صحة النظام — {status_icon.get(snapshot['status'], 'ℹ️')}</b>",
        "",
        f"الإصدار: <code>{safe(snapshot['version'])}</code>",
        f"قاعدة البيانات: {'تعمل ✅' if snapshot['database']['ok'] else 'خطأ ❌'}",
        f"آخر Migration: <code>{safe(snapshot.get('migration') or 'غير مسجل')}</code>",
        f"معرف النشر: <code>{safe(release.get('release_id') or 'غير مسجل')}</code>",
        f"وضع التشغيل: <code>{safe(release.get('runtime_mode') or 'غير معروف')}</code>",
        f"حالة النشر: <code>{safe(release.get('status') or 'غير معروفة')}</code>",
        f"النسخ الاحتياطي: <code>{safe(backup.get('status') or 'never')}</code>",
        f"نسخة احتياطية متأخرة: {'نعم ⚠️' if backup.get('stale') else 'لا ✅'}",
        "",
        "<b>الأداء اللحظي:</b>",
        f"• RAM العملية: <b>{int(runtime.get('process_rss_bytes', 0)) / 1024 / 1024:.1f} MB</b>",
        f"• CPU العملية: <b>{runtime.get('process_cpu_percent', 0)}%</b>",
        f"• ذاكرة الخادم: <b>{runtime.get('system_memory_percent', 0)}%</b>",
        f"• قرص الخادم: <b>{runtime.get('disk_percent', 0)}%</b>",
        f"• Redis: {'يعمل ✅' if redis_check.get('ok') else 'غير متاح ❌'} — {redis_check.get('latency_ms') or 0} ms",
        f"• Telegram API: {'يعمل ✅' if telegram_check.get('ok') else 'غير متاح ❌'} — {telegram_check.get('latency_ms') or 0} ms",
        f"أعطال تشغيل مفتوحة: <b>{operations.get('open_incidents', 0)}</b>",
        f"مهام مجدولة فاشلة: <b>{operations.get('failed_scheduled_runs', 0)}</b>",
        f"مهام التسليم المنتظرة: <b>{delivery['pending']}</b>",
        f"مهام التسليم العالقة: <b>{delivery['stale_processing']}</b>",
        f"مهام التسليم الفاشلة: <b>{delivery['failed']}</b>",
        f"الإشعارات المنتظرة: <b>{notifications['pending']}</b>",
        f"الإشعارات الفاشلة: <b>{notifications['failed']}</b>",
        f"مدفوعات تنتظر التدقيق: <b>{snapshot['payment_reviews']}</b>",
        f"تذاكر مفتوحة: <b>{snapshot['open_tickets']}</b>",
        f"استرجاعات معلقة: <b>{snapshot['refunds']['pending']}</b>",
        f"مخزون يحتاج تدوير/إتلاف: <b>{snapshot['inventory_remediation']['pending']}</b>",
        f"أدلة تنتظر الأرشفة: <b>{evidence.get('registered', 0)}</b>",
        f"أدلة فشلت أرشفتها: <b>{evidence.get('failed', 0)}</b>",
        f"أدلة انتهت مدة احتفاظها: <b>{evidence.get('expired', 0)}</b>",
        f"حسابات بريد تحتاج مراجعة: <b>{snapshot['email_accounts_needing_attention']}</b>",
        "",
        "<b>حماية التجارة:</b>",
        f"• نموذج الأموال: <code>{safe(commercial['money_flow_model'])}</code>",
        f"• سحب المنصات: {'مفعل ⚠️' if commercial['provider_withdrawals_enabled'] else 'متوقف ✅'}",
        f"• SSL قاعدة البيانات: <code>{safe(commercial['database_ssl_mode'])}</code>",
        f"• Redis إلزامي بالإنتاج: {'نعم' if commercial['redis_required_in_production'] else 'لا'}",
        f"• تخزين الأدلة الخارجي: {'مفعل' if commercial.get('external_evidence_storage_enabled') else 'غير مفعل'}",
        f"• التخزين الخارجي إلزامي: {'نعم' if commercial.get('external_evidence_storage_required') else 'لا'}",
        f"• سياسة الخصوصية: <code>{safe(commercial.get('privacy_policy_version') or 'غير محددة')}</code>",
        "",
        "<b>الوحدات:</b>",
    ] + [
        f"{status_icon.get(module['health'], 'ℹ️')} {safe(module['name'])} — <code>{safe(module['version'])}</code>"
        for module in snapshot["modules"]
    ]


async def _send_diagnostics(message: Message, session: AsyncSession, services) -> None:
    snapshot = await services.health.snapshot(session)
    await message.answer("\n".join(_health_lines(snapshot)), reply_markup=admin_back())


@router.message(Command("version"))
async def version_command(message: Message, settings: Settings) -> None:
    if not await require_admin(message, settings):
        return
    await message.answer(f"إصدار البوت: <code>{safe(__version__)}</code>")


@router.message(Command("diagnostics"))
@router.message(Command("system_status"))
async def diagnostics_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    services,
) -> None:
    if not await require_admin(message, settings):
        return
    await _send_diagnostics(message, session, services)


@router.message(Command("recent_errors"))
async def recent_errors_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    if not await require_admin(message, settings):
        return
    failed_jobs = list(
        (
            await session.scalars(
                select(DeliveryJob)
                .where(DeliveryJob.status == DeliveryJobStatus.FAILED.value)
                .order_by(DeliveryJob.id.desc())
                .limit(5)
            )
        ).all()
    )
    failed_notifications = list(
        (
            await session.scalars(
                select(Notification)
                .where(Notification.delivery_status == "failed")
                .order_by(Notification.id.desc())
                .limit(5)
            )
        ).all()
    )
    runtime_incidents = list(
        (
            await session.scalars(
                select(RuntimeIncident)
                .where(RuntimeIncident.status != RuntimeIncidentStatus.RESOLVED.value)
                .order_by(RuntimeIncident.last_seen_at.desc())
                .limit(5)
            )
        ).all()
    )
    lines = ["🚨 <b>آخر الأعطال المسجلة</b>"]
    if not failed_jobs and not failed_notifications and not runtime_incidents:
        lines.append("\nلا توجد أعطال مسجلة حالياً ✅")
    for incident in runtime_incidents:
        lines.append(
            f"\n• <code>{safe(incident.code)}</code> {safe(incident.summary[:100])}: "
            f"{safe((incident.details or 'لا توجد تفاصيل')[:120])}"
        )
    for job in failed_jobs:
        lines.append(
            f"\n• <code>DLV-{job.id}</code> طلب {job.order_id}: "
            f"{safe((job.last_error or 'خطأ تسليم')[:120])}"
        )
    for item in failed_notifications:
        lines.append(
            f"\n• <code>NTF-{item.id}</code> مستخدم {item.user_id}: "
            f"{safe((item.last_error or 'فشل إرسال')[:120])}"
        )
    lines.append("\n\nعند طلب المساعدة أرسل رمز العطل فقط، ولا ترسل التوكن أو كلمات المرور.")
    await message.answer("".join(lines), reply_markup=admin_back())


@router.message(Command("deployment_status"))
async def deployment_status_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    services,
) -> None:
    if not await require_admin(message, settings):
        return
    snapshot = await services.operations.status_snapshot(session)
    release = snapshot["release"]
    component_lines = "\n".join(
        f"• {safe(item['runtime_mode'])}: <code>{safe(item['status'])}</code>"
        for item in snapshot.get("components", [])
    ) or "• لا توجد مكونات مسجلة"
    await message.answer(
        "🚀 <b>حالة النشر</b>\n\n"
        f"الإصدار: <code>{safe(release['version'])}</code>\n"
        f"معرف النشر: <code>{safe(release['release_id'])}</code>\n"
        f"البيئة: <code>{safe(release['environment'])}</code>\n"
        f"وضع التشغيل: <code>{safe(release['runtime_mode'])}</code>\n"
        f"الحالة: <code>{safe(release['status'])}</code>\n"
        f"Git SHA: <code>{safe(release.get('git_sha') or 'غير متوفر')}</code>\n"
        f"وقت الجاهزية: <code>{safe(release.get('ready_at') or 'غير مسجل')}</code>\n\n"
        f"<b>مكونات النشر:</b>\n{component_lines}",
        reply_markup=admin_back(),
    )


@router.message(Command("backup_status"))
async def backup_status_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    services,
) -> None:
    if not await require_admin(message, settings):
        return
    backup = (await services.operations.status_snapshot(session))["backup"]
    await message.answer(
        "💾 <b>حالة النسخ الاحتياطي</b>\n\n"
        f"مفعل: {'نعم' if backup['enabled'] else 'لا'}\n"
        f"آخر حالة: <code>{safe(backup['status'])}</code>\n"
        f"المعرف: <code>{safe(backup.get('public_id') or 'لا توجد نسخة')}</code>\n"
        f"وقت التحقق: <code>{safe(backup.get('verified_at') or 'غير متوفر')}</code>\n"
        f"الحجم: <b>{int(backup.get('size_bytes') or 0):,}</b> بايت\n"
        f"آخر خطأ: <code>{safe(backup.get('last_error') or 'لا يوجد')}</code>",
        reply_markup=admin_back(),
    )


@router.message(Command("run_backup"))
async def run_backup_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    services,
) -> None:
    if not await require_admin(message, settings):
        return
    if not settings.backup_ready:
        await message.answer(
            "النسخ الاحتياطي مفعل لكنه ينتظر إعداد S3. لا تضع المفاتيح داخل المحادثة؛ أضفها في متغيرات Render."
        )
        return
    actor = await services.users.get(message.from_user.id) if message.from_user else None
    await message.answer("⏳ بدأ إنشاء نسخة مشفرة والتحقق منها...")
    run = await services.backups.create(session, actor_user_id=actor.id if actor else None)
    if run.status == "verified":
        await message.answer(
            f"✅ تم إنشاء النسخة والتحقق منها\n"
            f"المعرف: <code>{safe(run.public_id)}</code>\n"
            f"الحجم: <b>{run.size_bytes:,}</b> بايت"
        )
    else:
        await message.answer(
            f"❌ فشل النسخ الاحتياطي <code>{safe(run.public_id)}</code>\n"
            f"الخطأ: <code>{safe(run.last_error or 'غير معروف')}</code>"
        )


@router.message(Command("rotate_keys"))
async def rotate_keys_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    services,
) -> None:
    if not await require_admin(message, settings):
        return
    if settings.encryption_key_version <= 1 or not settings.encryption_keyring:
        await message.answer(
            "لا يوجد تدوير مهيأ. يجب إضافة المفتاح القديم إلى ENCRYPTION_KEYRING "
            "ووضع المفتاح الجديد في ENCRYPTION_KEY ورفع ENCRYPTION_KEY_VERSION."
        )
        return
    result = await services.key_rotation.rotate_batch(session)
    await message.answer(
        "🔐 تم تنفيذ دفعة تدوير مفاتيح\n"
        f"الملفات الشخصية: {result['profiles']}\n"
        f"الطلبات: {result['orders']}\n"
        f"الأدلة: {result['evidence']}\n"
        "كرر الأمر حتى تصبح الأعداد صفراً، وبعدها فقط يمكن إزالة المفتاح القديم."
    )


@router.message(Command("resolve_incident"))
async def resolve_incident_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    services,
) -> None:
    if not await require_admin(message, settings):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("الاستخدام: <code>/resolve_incident SCH-MAIN</code>")
        return
    resolved = await services.operations.resolve_incident(session, parts[1].strip())
    await message.answer("تم إغلاق العطل ✅" if resolved else "رمز العطل غير موجود.")


@router.message(Command("admin"))
@router.message(F.text == "🛡 لوحة الإدارة")
async def admin_home_message(
    message: Message, settings: Settings, state: FSMContext
) -> None:
    if not await require_admin(message, settings):
        return
    rendered = await show_admin_home(message)
    if rendered is not None:
        await state.clear()


@router.callback_query(F.data == "admin:home")
async def admin_home_callback(
    callback: CallbackQuery, settings: Settings, state: FSMContext
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings):
        return
    rendered = await show_admin_home(callback)
    if rendered is not None:
        await state.clear()


@router.callback_query(F.data == "admin:stats")
async def admin_stats(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    models = [
        ("المستخدمون", User),
        ("المنصات", Provider),
        ("العروض", Offer),
        ("الطلبات", Order),
        ("التذاكر", SupportTicket),
        ("الإيميلات", EmailAccount),
        ("عناصر المخزون", InventoryItem),
    ]
    lines = ["📊 <b>نظرة عامة</b>"]
    for title, model in models:
        count = int(await session.scalar(select(func.count()).select_from(model)) or 0)
        lines.append(f"\n• {title}: <b>{count:,}</b>")
    review_count = int(
        await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(Order.status == OrderStatus.PAYMENT_REVIEW.value)
        )
        or 0
    )
    lines.append(f"\n• مدفوعات تنتظر التدقيق: <b>{review_count:,}</b>")
    await edit_or_send(callback.message, "".join(lines), reply_markup=admin_back())


@router.callback_query(F.data == "admin:settings")
async def admin_settings(callback: CallbackQuery, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    rows = [
        [
            InlineKeyboardButton(
                text="💵 رسوم الخدمة",
                callback_data="admin:setting:service_fee_iqd",
                style="success",
            )
        ],
        [
            InlineKeyboardButton(
                text="🔧 وضع الصيانة", callback_data="admin:flag:maintenance", style="danger"
            )
        ],
        [InlineKeyboardButton(text="🧩 الميزات", callback_data="admin:features", style="primary")],
        [InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")],
    ]
    await edit_or_send(callback.message, 
        "⚙️ <b>إعدادات النظام</b>\n\n"
        "الأسرار مثل BOT_TOKEN ومفاتيح الدفع تبقى في Railway Variables ولا تظهر داخل البوت.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data == "admin:system_info")
async def admin_system_info(
    callback: CallbackQuery, settings: Settings, session: AsyncSession, services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    latest_migration = await session.scalar(
        select(SchemaMigration).order_by(SchemaMigration.applied_at.desc()).limit(1)
    )
    migration_text = latest_migration.version if latest_migration else "غير مسجل"
    module_count = len(await services.modules.list(session))
    await edit_or_send(callback.message, 
        "ℹ️ <b>معلومات النظام</b>\n\n"
        f"الإصدار: <code>{safe(__version__)}</code>\n"
        f"قاعدة البيانات: <code>{safe(migration_text)}</code>\n"
        f"البيئة: <code>{safe(settings.environment)}</code>\n"
        f"المنطقة الزمنية: <code>{safe(settings.timezone)}</code>\n"
        f"التقارير: {'مفعلة' if settings.feature_reports else 'متوقفة من Variables'}\n"
        f"الإيميلات: {'مفعلة' if settings.feature_email_codes else 'متوقفة من Variables'}\n"
        f"Gemini: {'جاهز' if settings.gemini_ready else 'مفعل وينتظر GEMINI_API_KEY'}\n"
        f"Mastercard: {'جاهز' if settings.mastercard_ready else 'مفعل وينتظر بيانات البوابة'}\n"
        f"الوحدات المسجلة: <b>{module_count}</b>",
        reply_markup=admin_back(),
    )


@router.callback_query(F.data == "admin:health")
async def admin_health(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await callback_notice(callback, "جاري فحص قاعدة البيانات والوحدات...")
    snapshot = await services.health.snapshot(session)
    await edit_or_send(callback.message, "\n".join(_health_lines(snapshot)), reply_markup=admin_back())
