# إصلاح طوارئ CampusPass V4.0.1

## سبب الفشل الظاهر في Railway

المستودع الذي وصل إلى Railway كان ناقص الملفات. ظهر في التشخيص أن:

`app/services/email_codes.py`

يستورد:

`app.services.student_subscriptions`

لكن الملف `app/services/student_subscriptions.py` لم يكن موجودًا في GitHub، فتوقف التطبيق عند التشغيل وفشل Healthcheck. قاعدة PostgreSQL ليست سبب المشكلة ولا يجب حذفها.

## طريقة الإصلاح

1. فك ضغط ملف `campuspass-v4.0.1-emergency-repair.zip` على الحاسوب.
2. افتح المجلد الناتج، ثم ارفع **محتوياته كلها** إلى جذر مستودع GitHub الحالي، لا ترفع المجلد الخارجي نفسه.
3. وافق على استبدال الملفات الموجودة.
4. يجب أن يتضمن الـCommit جميع ملفات الحزمة. هذه حزمة Patch وليست النسخة الكاملة الكبيرة.
5. قبل انتظار Railway، افتح GitHub وتأكد يدويًا من وجود الملفات التالية:

   - `app/services/student_subscriptions.py`
   - `app/services/email_codes.py`
   - `app/bot/processing.py`
   - `app/bot/handlers/provider_catalog.py`
   - `app/bot/handlers/subscriptions.py`
   - `app/services/workflows.py`
   - `scripts/verify_runtime_files.py`

6. تأكد أن `VERSION.txt` يحتوي `4.0.1`.
7. لا تحذف PostgreSQL، ولا تغيّر `DATABASE_URL` أو `BOT_TOKEN` أو `ENCRYPTION_KEY`.
8. Railway سيعيد النشر تلقائيًا. أصبح Dockerfile يشغّل فحص اكتمال الملفات أثناء **Build**؛ إذا نقص ملف فسيفشل البناء مع اسم الملف بدل تشغيل نسخة ناقصة.
9. بعد نجاح النشر افتح `/health`. يجب أن يظهر الإصدار `4.0.1`.
10. أرسل `/start` في البوت لتحديث لوحة المفاتيح.

## ملاحظة

هذه الحزمة تصلح المستودع الجزئي الحالي، سواء كان على V3.2 أو يحتوي جزءًا من V4. لا ترفع ملف النسخة الكاملة ذات العدد الكبير من الملفات عبر المتصفح لهذه العملية؛ استخدم Patch الإصلاح فقط.
