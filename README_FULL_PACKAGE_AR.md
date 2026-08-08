# CampusPass IQ V10.7 — الحزمة الكاملة الجاهزة لـ Railway

هذه حزمة مشروع كاملة وليست Patch منفصلاً. تحتوي مباشرة على:

- `app/`
- `alembic/`
- `tests/`
- `scripts/`
- `Dockerfile`
- `railway.json`
- `requirements.txt`

## الرفع الصحيح

1. فك ضغط الملف محلياً.
2. ارفع **محتويات المجلد المفكوك** إلى جذر مستودع GitHub.
3. تأكد أن `Dockerfile` و`railway.json` و`requirements.txt` ظاهرة في جذر المستودع، وليست داخل مجلد إضافي.
4. اربط المستودع بخدمة Railway واجعل عدد Replicas يساوي 1.
5. استخدم Health Check: `/health/live`.
6. شغّل ترقية قاعدة البيانات وفق تعليمات `RAILWAY_DEPLOYMENT_TURBO_AR.md`.

لا ترفع ملف Emergency Patch السابق وحده إلى Railway؛ كان يحتوي ملفات التحديث فقط.
