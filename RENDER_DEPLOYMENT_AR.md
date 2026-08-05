# CampusPass IQ V10 — نشر Render + Supabase

## نوع الخدمة

أنشئ **Web Service** من المستودع، واختر Docker. الملف `render.yaml` موجود وجاهز، ومسار فحص الصحة هو `/ping`.

## المتغيرات الإلزامية في Render

- `BOT_TOKEN`: توكن البوت من BotFather.
- `ADMIN_IDS`: رقم Telegram الرقمي للإدارة. يمكن كتابة أكثر من رقم مفصولًا بفاصلة، مثال: `123456789,987654321`.
- `DATABASE_URL`: استخدم رابط **Supabase Transaction Pooler**، ويفضل المنفذ `6543`، وليس رابط Session Pooler. الصيغة العامة:
  `postgresql://postgres.PROJECT_REF:PASSWORD@HOST.pooler.supabase.com:6543/postgres`
- `ENCRYPTION_KEY`: ينشئه Render تلقائيًا عند استخدام Blueprint. لا تغيّره بعد بدء استخدام البوت حتى تبقى الأسرار القديمة قابلة لفك التشفير.

## متغيرات موصى بها

- `DB_SSL_MODE=require`
- `DB_PREPARED_STATEMENT_CACHE_SIZE=0`
- `REQUIRE_EXTERNAL_DATABASE=true`
- `RUNTIME_MODE=combined`
- `FEATURE_DISPUTES=false` لتفعيل مسار الدعم المباشر بدل النزاعات القديمة.
- `REDIS_URL` اختياري. عند عدم توفيره يعمل البوت بذاكرة داخلية، لكن Redis أفضل إذا شغلت أكثر من instance.

## UptimeRobot

بعد اكتمال النشر، أضف مراقبة HTTP(s) كل 5 دقائق على:

`https://YOUR-SERVICE.onrender.com/ping`

الاستجابة لا تستعلم من قاعدة البيانات أو Telegram، لذلك هي خفيفة جدًا ومناسبة لفحص بقاء خدمة الويب.

## تنبيه مهم عن Render Free

المسار `/ping` جاهز لـ UptimeRobot، لكن سياسات الاستضافة المجانية قد تتغير، ولا يمكن للكود وحده ضمان تشغيل مجاني 24/7 إذا فرضت المنصة حدودًا أو إيقافًا على مستوى الحساب.
