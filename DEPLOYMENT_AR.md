# نشر وتحديث V6.9 Phase 5

## قاعدة ذهبية
قاعدة PostgreSQL وRedis والتخزين الخارجي تبقى خارج Railway. تغيير حساب Railway لا يغير البيانات إذا استخدمت المتغيرات نفسها.

## قبل أول نشر V6.9
1. احتفظ بـ`DATABASE_URL` و`ENCRYPTION_KEY`.
2. أعطِ النشر معرفاً فريداً في `RELEASE_ID`.
3. ابدأ بـ`RUNTIME_MODE=combined`.
4. شغل `python ops/preflight.py` داخل CI/Docker.
5. لا تجعل `REQUIRE_PRE_DEPLOY_BACKUP=true` قبل تجهيز S3 وتجربة أول Backup.

## إعداد Staging
- أنشئ Bot جديداً من BotFather.
- استخدم قاعدة وRedis منفصلين إن أمكن.
- `ENVIRONMENT=staging`.
- احسب SHA-256 لتوكن الإنتاج وضعه في `STAGING_BOT_TOKEN_FINGERPRINT`.
- ضع توكن الاختبار في `BOT_TOKEN`.
- النظام يرفض تشغيل Staging بتوكن الإنتاج.

## إعداد Backup
1. أنشئ Bucket خاصاً غير عام في R2/S3/MinIO.
2. فعّل `BACKUP_ENABLED=true`.
3. أضف متغيرات `BACKUP_S3_*`.
4. نفذ `/run_backup`.
5. يجب أن تظهر `verified`.
6. جرّب Restore إلى قاعدة منفصلة بواسطة `ops/restore_backup.py`.
7. بعد نجاح التجربة فعّل `REQUIRE_PRE_DEPLOY_BACKUP=true`.

## تحديث عادي
1. خذ Backup متحققاً.
2. أنشئ `RELEASE_ID` جديداً وسجل القديم في `PREVIOUS_RELEASE_ID`.
3. انشر الحزمة.
4. افتح `/health/ready`.
5. افتح `/deployment_status` و`/diagnostics`.
6. جرّب طلباً تجريبياً فقط.

## الرجوع
- ارجع إلى Docker image/commit السابق.
- استخدم قاعدة البيانات نفسها؛ Migration V6.9 إضافية.
- لا تنفذ Restore إلا إذا ثبت تلف البيانات، وبعد تجربة على نسخة منفصلة.
- لا تحذف جداول V6.9 يدوياً.

## فصل الخدمات عند زيادة الحمل
- خدمة Telegram: `RUNTIME_MODE=bot`.
- خدمة العامل: `RUNTIME_MODE=worker`.
- كلاهما يستخدمان نفس DB وRedis ومفاتيح التشفير.
- يجب أن توجد خدمة bot واحدة فقط للتوكن نفسه.
