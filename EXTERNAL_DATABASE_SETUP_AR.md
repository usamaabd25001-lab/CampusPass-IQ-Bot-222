# تشغيل CampusPass IQ بقاعدة PostgreSQL خارج Railway

هذه النسخة تجعل Railway مسؤولاً عن تشغيل الكود فقط، بينما تبقى بيانات الطلاب والمنصات والطلبات والمحافظ في PostgreSQL خارجي ثابت. عند تبديل حساب Railway، ترفع نفس الكود وتضع نفس `DATABASE_URL` و`BOT_TOKEN` و`ENCRYPTION_KEY`؛ فلا يحتاج المستخدمون إلى إعادة التسجيل.

## 1) أنشئ PostgreSQL خارجياً

يمكن استعمال Supabase أو Neon أو أي PostgreSQL مُدار. من لوحة مزود القاعدة انسخ **Connection string** الخاص بالخادم أو الـSession pooler. لا تضع مفتاح Supabase العام أو رابط REST مكان `DATABASE_URL`؛ المطلوب رابط PostgreSQL يبدأ بـ`postgresql://` أو `postgres://`.

مثال شكلي فقط:

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/postgres?sslmode=require
```

إذا كان الرابط يحتوي `channel_binding=require` أو `sslmode=require` فالنسخة تنظفه تلقائياً لـasyncpg وتطبق SSL من `DB_SSL_MODE`.

## 2) Variables في Railway

انسخ محتوى `RAILWAY_EXTERNAL_VARIABLES.txt` إلى Variables. أهم القيم:

```env
BOT_TOKEN=...
ADMIN_IDS=...
DATABASE_URL=postgresql://...
ENVIRONMENT=production
REQUIRE_EXTERNAL_DATABASE=true
DB_SSL_MODE=require
ENCRYPTION_KEY=نفس_المفتاح_الدائم
```

لا تستعمل:

```env
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

لأن هذا يعيد ربط البوت بقاعدة Railway الداخلية.

## 3) نقل قاعدة Railway الحالية

أوقف استقبال الطلبات أو فعّل:

```env
MAINTENANCE_MODE=true
```

على جهاز يحتوي PostgreSQL client tools (`pg_dump`, `pg_restore`, `psql`) شغّل:

```bash
export SOURCE_DATABASE_URL='رابط قاعدة Railway القديمة'
export TARGET_DATABASE_URL='رابط PostgreSQL الخارجي الجديد'
export MIGRATION_CONFIRM='MIGRATE_CAMPUSPASS_DATABASE'
python ops/migrate_external_postgres.py
```

الأداة تنشئ dump، تستعيده في الهدف، ثم تتحقق من وجود جداول CampusPass. **قاعدة الهدف تُنظف قبل الاستعادة**؛ استعمل قاعدة فارغة ومخصصة للبوت.

## 4) فحص القاعدة قبل فتح البوت

ضع Variables نفسها محلياً أو في جلسة الطرفية ثم:

```bash
python scripts/external_db_check.py
```

سيعرض اسم المضيف والقاعدة وعدد جداول CampusPass وعدد المستخدمين، بدون إظهار كلمة المرور.

## 5) افتح الخدمة

بعد نجاح الفحص:

```env
MAINTENANCE_MODE=false
```

افحص:

- `/health/live` للتأكد أن العملية تعمل.
- `/health/ready` للتأكد أن البوت متصل بالقاعدة وأكمل التهيئة.

## إعدادات الاتصال المقترحة للبداية

```env
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
DB_PREPARED_STATEMENT_CACHE_SIZE=0
DB_SSL_MODE=require
DB_STARTUP_RETRIES=8
DB_STARTUP_RETRY_SECONDS=5
```

القيم الصغيرة مناسبة للخطة المجانية وتقلل استهلاك الاتصالات. إذا استعملت PostgreSQL مباشر بدون pooler، يمكن رفع prepared statement cache لاحقاً بعد الاختبار.

## قواعد لا تتغير عند تبديل Railway

احتفظ دائماً بنفس:

- `BOT_TOKEN`
- `DATABASE_URL`
- `ENCRYPTION_KEY`
- `REPORT_SECRET_KEY` إذا كان محدداً
- أسرار بوابة الدفع إن فُعّلت

تغيير `ENCRYPTION_KEY` قد يمنع قراءة البيانات الحساسة المشفرة حتى لو بقيت الجداول موجودة.
