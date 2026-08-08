# نشر CampusPass IQ V10.7 — Emergency Stabilization

## القاعدة الذهبية

هذه الحزمة تحديث لنفس البوت وليست بوتًا جديدًا. احتفظ بالقيم الحالية التالية دون تغيير:

- `BOT_TOKEN`
- `DATABASE_URL`
- `ENCRYPTION_KEY`
- `ADMIN_IDS`

تغيير `DATABASE_URL` يجعل البوت يرى قاعدة مختلفة، وتغيير `ENCRYPTION_KEY` قد يمنع قراءة البيانات القديمة المشفرة.

## أسرع تحديث لخدمة Railway الحالية

1. فك الملف الخارجي فقط.
2. ارفع الملفات الموجودة داخله إلى جذر مستودع GitHub الخاص بالخدمة.
3. لا تفك `source_bundle.zip` داخل GitHub.
4. تأكد أن `Dockerfile` و`railway.json` و`source_bundle.zip` ظاهرة في الصفحة الرئيسية للمستودع.
5. افتح Railway > خدمة البوت > Variables، ولا تحذف القيم القديمة.
6. أضف قيم الأداء من `RAILWAY_TURBO_VARIABLES_BASE.txt`.
7. اختر ملف قاعدة البيانات المناسب:
   - قاعدة داخل نفس مشروع Railway: `RAILWAY_TURBO_INTERNAL_DB_PROFILE.txt`.
   - Supabase/Neon/قاعدة خارجية: `RAILWAY_TURBO_EXTERNAL_DB_PROFILE.txt`.
8. افتح Settings وأطفئ **Serverless/App Sleeping** للحصول على استجابة ثابتة بلا cold start.
9. اترك Replicas = 1 لأن البوت يعمل Long Polling. لا تشغّل نسختين بنفس التوكن.
10. شغّل Deploy وانتظر حتى ينجح `/health/live`.


## متغيرات V10.7 الضرورية

```text
IMAGE_MODERATION_ENABLED=false
REFERRAL_WALLET_REWARD_IQD=0
REFERRAL_INVITES_PER_COUPON=3
```

لا يحتاج مسار شعار المنصة إلى Google Vision أو Gemini؛ يفحص ملف Telegram محلياً ثم يحفظ `file_id` بعد التأكيد. لا تغيّر `DATABASE_URL` أو `ENCRYPTION_KEY` أثناء التحديث.

## إعداد قاعدة Railway الداخلية

من خدمة البوت افتح Variables ثم Add Reference Variable واختر `DATABASE_URL` من خدمة PostgreSQL. الصيغة تكون مثل:

```text
${{Postgres.DATABASE_URL}}
```

استعمل الشبكة الداخلية ولا تستعمل `DATABASE_PUBLIC_URL` بين خدمتين داخل نفس مشروع Railway.

## اختبار النجاح

في Logs يجب أن يظهر:

```text
CampusPass IQ started
Polling turbo profile enabled update_concurrency=96 telegram_http_limit=120
```

ثم اختبر في Telegram:

```text
/start
/admin
/version
```

وافحص رابط Railway:

```text
https://YOUR-DOMAIN.up.railway.app/health/live
```

## قراءة سجل البطء

أي زر يتجاوز 750ms داخل التطبيق سيظهر بهذا الشكل:

```text
Slow Telegram update: 1250 ms user=... event=...
```

وجود السطر يعني أن التأخير في handler أو قاعدة البيانات أو خدمة خارجية. عدم وجوده مع تأخر واجهة Telegram يرجح الشبكة أو Telegram API.

## ما تم ضبطه للحمل

- حد أقصى 96 تحديث Telegram قيد المعالجة بدل مهام بلا حد.
- 120 اتصال HTTP إلى Telegram.
- حماية الضغط المتكرر لكل طالب 350ms؛ لا تمنع 200 طالب مختلفين من الضغط معًا.
- AI بخمس مهام، IMAP بثمانٍ، التقارير بأربع، والعمليات الثقيلة العامة باثنتي عشرة مهمة؛ الزائد ينتظر بطابور ولا يجمد القوائم.
- Cache لمسارات المستخدم والحظر والقوائم والميزات والإعلانات.
- إزالة استعلامات N+1 من تقييمات المنصات وتقليل backfill الكتالوج المتكرر.
- Railway restart policy = ALWAYS، وoverlap = 0 لمنع تشغيل Poller قديم وجديد بالتوكن نفسه أثناء النشر.

## ملاحظة واقعية

لا توجد منصة أو شفرة تضمن رد Telegram بأقل من 1ms، لأن الطلب يمر عبر الإنترنت وTelegram وقاعدة البيانات. الهدف العملي للأزرار الخفيفة بعد ضبط المنطقة والقاعدة هو استجابة محسوسة عادةً تحت ثانية، بينما IMAP وAI والتقارير تعتمد على خدمات خارجية وتظهر لها رسالة المعالجة فورًا.

> يبقى `/health/ready` للفحص التشخيصي الكامل بعد أن تصبح قاعدة البيانات وTelegram والـworkers جاهزة.
