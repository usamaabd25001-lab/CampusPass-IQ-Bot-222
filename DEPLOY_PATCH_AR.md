# نشر Emergency Stabilization Patch

## 1. Backup قبل التحديث

1. أوقف أي deploy موازٍ وتأكد أن Replicas = 1.
2. شغّل النسخ الاحتياطي المدمج إن كان مفعلاً:

```bash
python ops/backup_now.py
```

3. أو أنشئ PostgreSQL dump باستخدام متغير البيئة دون طباعته في logs:

```bash
pg_dump "$DATABASE_URL" --format=custom --file=campuspass_before_1070.dump
```

## 2. تطبيق الملفات

من جذر المشروع، فك ZIP مع الحفاظ على المسارات واستبدال الملفات الموجودة. لا تحذف ملفات المشروع الأخرى.

```bash
unzip -o CampusPass-IQ-Emergency-Stabilization-Patch.zip -d .
sha256sum -c PATCH_SHA256SUMS.txt
```

## 3. Migration

في البيئات التي تستخدم Alembic:

```bash
alembic upgrade head
alembic heads
```

يجب أن يكون الرأس:

```text
1070_emergency_stabilization
```

التطبيق يحتوي أيضاً migration runner داخلياً guarded، لذلك startup يبقى متوافقاً مع طريقة النشر الحالية.

## 4. Railway

- Replicas: `1`.
- لا تشغّل نسخة أخرى بنفس BOT_TOKEN.
- Healthcheck: `/health/live`.
- `/health/ready` يبقى للتشخيص التفصيلي ولا يُستخدم لإسقاط deploy أثناء migrations/runtime lease.
- `GOOGLE_VISION_API_KEY` غير مطلوب ويمكن حذفه؛ إن بقي فهو مهمل.

## 5. Preflight وRestart

```bash
python -m compileall -q app alembic scripts
python scripts/validate_v10_7_emergency_stabilization.py
python scripts/verify_v10_railway_turbo.py
```

ثم أعد تشغيل خدمة واحدة فقط.

## 6. Smoke Test

- `/start` لمستخدم جديد ومسجل؛ ReplyKeyboard يظهر على رسالة الرئيسية نفسها.
- فتح Inline ثم Back ثم Home.
- OWNER وSTAFF بصلاحيات مختلفة.
- منصة واحدة وعدة منصات، وcallback قديم.
- متجر → إضافة عرض/عروضي/تنظيم المتجر.
- شعار → رفع/معاينة/إلغاء/تأكيد.
- Admin → تعديل رسالة `/start` ثم فتح `/start` من حساب آخر.
- افحص `/health/live` و`/health/ready` وRuntime Logs.
