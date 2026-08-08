# ابدأ من هنا — CampusPass IQ V11.6

## هدف الإصدار

V11.6 لا يضيف واجهة تجارية جديدة؛ بل يقوي طريقة تشغيل جميع الميزات التي بُنيت في V11.0–V11.5 على Render.

المبدأ الأساسي:

```text
Telegram
   ↓ Webhook موقّع
FastAPI
   ↓ حفظ أولاً
PostgreSQL Update Inbox
   ↓ Consumers + Lease + Retry
Aiogram Dispatcher
```

بهذا لا يعتمد وصول الطلبات على بقاء عملية Python نفسها حية طوال الوقت.

## قبل الرفع

- استخدم حزمة GitHub الخاصة بـV11.6 فقط.
- أنشئ قاعدة PostgreSQL خارجية دائمة وRedis دائماً.
- خصص Bot Token للتجربة لا يُستخدم في Production.
- حضّر `ADMIN_IDS` و`DATABASE_URL` و`REDIS_URL`.
- لا ترفع أي سر إلى GitHub.

## اختيار ملف Render

- `render.yaml`: Staging بخدمة Combined واحدة.
- `render.production.yaml`: Web Service وBackground Worker منفصلان.

## التحقق المحلي المتاح

```bash
python scripts/validate_v11_6_render_e2e.py
pytest -q tests/test_v11_6_render_e2e.py
```

## التحقق بعد النشر

```bash
PUBLIC_BASE_URL=https://YOUR-STAGING.onrender.com \
API_ADMIN_TOKEN=YOUR_ADMIN_TOKEN \
python ops/render_smoke.py
```

لا تُنقل بيانات Production إلى Staging. استخدم بيانات تجريبية وحسابات بريد وطرق دفع وهمية فقط.
