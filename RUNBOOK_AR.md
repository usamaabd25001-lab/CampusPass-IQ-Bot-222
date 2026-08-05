# دليل الطوارئ — V6.9

## البوت لا يرد
1. افتح `/health/live`.
2. افتح `/health/ready`.
3. داخل البوت استخدم `/deployment_status` و`/diagnostics`.
4. لا تحذف قاعدة البيانات ولا تغيّر `ENCRYPTION_KEY`.
5. إذا وضع التشغيل `worker` فقط، طبيعي ألا يرد Telegram؛ خدمة bot يجب أن تكون موجودة.

## فشل تحديث جديد
1. لا تشغل Migration يدوياً.
2. راجع آخر Backup بواسطة `/backup_status`.
3. ارجع في الاستضافة إلى صورة الإصدار السابق.
4. أبقِ قاعدة البيانات نفسها؛ تغييرات V6.9 إضافية.
5. افحص `/health/ready`.
6. أرسل `RELEASE_ID` ورمز العطل، لا ترسل الأسرار.

## لا توجد نسخة احتياطية
- افحص `BACKUP_ENABLED` وS3 variables.
- تأكد أن Docker يحتوي `pg_dump`.
- نفذ `/run_backup`.
- لا تعتبر العملية ناجحة إلا إذا كانت الحالة `verified`.

## فشل النسخ الاحتياطي
- استخدم `/backup_status`.
- رمز العطل المتوقع `BKP-LATEST`.
- افحص صلاحيات bucket والمساحة و`BACKUP_MAX_BYTES`.
- لا تخفض الحماية ولا ترفع ملفاً غير مشفر يدوياً.

## تجربة الاستعادة
- لا تجرب على قاعدة الإنتاج.
- أنشئ قاعدة PostgreSQL فارغة منفصلة.
- استخدم `ops/restore_backup.py`.
- أدخل Storage Key وSHA-256 من سجل النسخة.
- استخدم `--confirm RESTORE-CAMPUSPASS`.
- بعد الاستعادة شغل الفحوص على قاعدة الاختبار.

## تدوير مفتاح التشفير
1. لا تحذف المفتاح القديم.
2. ضع الجديد في `ENCRYPTION_KEY`.
3. ضع القديم في `ENCRYPTION_KEYRING`.
4. ارفع `ENCRYPTION_KEY_VERSION`.
5. أعد التشغيل.
6. نفذ `/rotate_keys` حتى تصبح الأعداد صفراً في عدة محاولات.
7. خذ Backup جديداً وتحقق منه.
8. بعدها فقط احذف المفتاح القديم في تحديث لاحق.

## Staging لا يعمل
- يجب أن يكون له Bot Token مختلف.
- ضع SHA-256 لتوكن الإنتاج في `STAGING_BOT_TOKEN_FINGERPRINT`.
- لا تضع توكن الإنتاج نفسه في Staging.

## Scheduler متعطل
- افتح `/recent_errors`.
- رمز `SCH-MAIN` يعني فشل دورة العامل.
- افحص خدمة worker وDB.
- بعد إصلاح السبب استخدم `/resolve_incident SCH-MAIN`.

## نقل البوت من Railway
1. لا تنقل قاعدة البيانات إذا كانت Neon خارجية.
2. استخدم نفس `DATABASE_URL`, `REDIS_URL`, `ENCRYPTION_KEY` وKeyring.
3. أعطِ النشر الجديد `RELEASE_ID` جديداً.
4. شغل `python ops/preflight.py`.
5. ابدأ نسخة واحدة `combined` أو افصل `bot` و`worker`.
6. لا تشغل خدمتي bot بالتوكن نفسه.
