# CampusPass IQ v4.3.0 — GitHub Operations Ready

هذا الإصدار لا يغيّر الدفع الإلكتروني ولا Hotmail. يركّز فقط على الاعتمادية عندما يتبدل السيرفر ويكون النشر مربوطًا بـGitHub.

## الإضافات

- نسخة PostgreSQL احتياطية يومية من GitHub Actions.
- تشفير النسخة بـGPG AES-256 قبل رفعها.
- تخزين النسخ داخل Release خاص بالمستودع، وليس على قرص السيرفر.
- تنظيف النسخ القديمة مع الاحتفاظ بآخر النسخ.
- Workflow لفحص النسخة أو استعادتها إلى قاعدة منفصلة.
- Workflow لاختبار مئات أو آلاف الطلبات المتزامنة على نفس المخزون.
- حماية تمنع تشغيل اختبار الضغط على قاعدة لا يحمل اسمها load/test/staging/qa.
- دليل متغيرات GitHub ومتغيرات السيرفر المتبدل.

## أسرار GitHub المطلوبة

```text
BACKUP_DATABASE_URL
BACKUP_ENCRYPTION_KEY
LOAD_TEST_DATABASE_URL
RESTORE_DATABASE_URL   # اختياري
```

## الفحوصات المحلية

- اختبارات البوت: 33/33 ناجحة.
- Ruff: ناجح.
- Compileall: ناجح.
- ملفات GitHub Workflow: YAML صالح.

لم يُشغّل اختبار الضغط الحقيقي هنا لعدم توفر قاعدة PostgreSQL خارجية مخصصة في بيئة البناء. يتم تشغيله من GitHub Actions بعد إضافة `LOAD_TEST_DATABASE_URL`.
