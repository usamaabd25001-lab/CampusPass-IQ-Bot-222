# نشر الحزمة الكاملة على Railway

1. أوقف أي نسخة أخرى تعمل بنفس `BOT_TOKEN` على Railway أو Render أو VPS.
2. اجعل Replicas = 1.
3. فك ZIP وارفع محتوياته إلى جذر GitHub.
4. تحقق من وجود الملفات التالية في الجذر:
   - `Dockerfile`
   - `railway.json`
   - `requirements.txt`
   - `alembic.ini`
   - مجلد `app`
5. في Railway استخدم Dockerfile Builder.
6. Health Check يجب أن يكون `/health/live`.
7. شغّل migration:

```bash
alembic upgrade head
```

8. أعد التشغيل وراقب السجل حتى تظهر جاهزية السيرفر والبوت.

إذا ظهر `Another active CampusPass instance still owns Telegram polling` فأوقف النسخة القديمة أو المشروع الآخر الذي يستخدم التوكن نفسه، ثم أعد تشغيل نسخة واحدة فقط.
