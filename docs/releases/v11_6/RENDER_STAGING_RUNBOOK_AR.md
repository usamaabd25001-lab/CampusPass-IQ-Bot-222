# Runbook نشر Staging على Render — V11.6

## 1. إنشاء المستودع

- أنشئ Repository جديداً أو فرع إصدار محمياً.
- ارفع محتويات حزمة GitHub إلى الجذر.
- فعّل Branch Protection وChecks قبل الدمج.

## 2. قواعد البيانات

- أنشئ PostgreSQL دائماً.
- أنشئ Redis دائماً.
- اجعل الاتصالات مشفرة.
- لا تستخدم SQLite أو ذاكرة Redis مؤقتة في Staging النهائي.

## 3. إنشاء الخدمة

استخدم `render.yaml` لإنشاء خدمة `campuspass-v11-6-staging`.

أدخل القيم السرية يدوياً:

- `BOT_TOKEN`
- `STAGING_BOT_TOKEN_FINGERPRINT`
- `ADMIN_IDS`
- `DATABASE_URL`
- `REDIS_URL`

أما مفاتيح Webhook والتشفير وAPI وMetrics فيمكن لـRender توليدها.

## 4. Pre-deploy

قبل تشغيل الإصدار ينفذ Render:

```bash
python ops/render_predeploy.py
```

يجب أن ينجح:

- اتصال PostgreSQL.
- قفل المهاجرات.
- Migration حتى V11.6.
- Seed الآمن.
- اتصال Redis.
- `getMe` للبوت.
- تسجيل نتيجة بوابة النشر.

## 5. الجاهزية

لا تعتمد على `/health/live` وحدها. يجب أن يرجع `/health/ready` نجاحاً بعد توفر:

- قاعدة البيانات.
- Redis.
- Bot Runtime.
- Webhook.
- Update Consumers.
- Worker heartbeat.
- Release readiness.
- Deployment gate.

## 6. Smoke Test

من جهاز آمن:

```bash
PUBLIC_BASE_URL=https://YOUR-STAGING.onrender.com \
API_ADMIN_TOKEN=YOUR_ADMIN_TOKEN \
python ops/render_smoke.py
```

يجب أن ينجح Ping وLive وReady وDeep، وأن يُرفض Webhook ذو Secret مزور.

## 7. اختبار Telegram الحقيقي

- `/start` مرتين للتأكد من Idempotency.
- ضغط زر بسرعة متكررة.
- إكمال الملف الشخصي.
- إنشاء طلب تجريبي ورفع وصل غير حقيقي.
- رفض وقبول عمليات اختبارية فقط.
- تجربة Restart أثناء وجود تحديث محفوظ.
- إيقاف Worker مؤقتاً والتأكد أن Ready يفشل.
- إعادة Worker والتأكد أن Ready يعود.

## 8. اختبارات الاسترداد

- نسخة احتياطية قبل Migration.
- Restore إلى قاعدة منفصلة.
- مقارنة عدد الجداول ورأس Alembic.
- التأكد من عدم فقد Ledger أو Orders أو Inbox.

## 9. الانتقال إلى Production

لا تستخدم `render.production.yaml` قبل توثيق نتائج جميع البنود السابقة. في Production يجب أن يكون Web Service منفصلاً عن Background Worker، مع أسرار مستقلة عن Staging.
