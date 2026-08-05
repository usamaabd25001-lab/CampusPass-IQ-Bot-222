# ابدأ من هنا — CampusPass New Bot V11.3

هذه النسخة مبنية مباشرة فوق V11.2 وتحافظ على كل ما سبق، وتضيف باقة أصدقائي فقط ونظام الضمان الآلي.

## قبل رفع GitHub

1. فك ضغط حزمة GitHub Web Upload.
2. ارفع جميع الملفات إلى مستودع خاص.
3. لا ترفع أي ملف `.env` أو مفاتيح حقيقية.
4. اربط المستودع بخدمات Render.

## مخطط Render الموصى به

استخدم `render.production.yaml` للتشغيل التجاري:

- Web Service: Telegram Bot + FastAPI/Webhook.
- Background Worker: Scheduler، انتهاء المجموعات، Delivery Outbox، IMAP وOTP.
- PostgreSQL خارجي دائم.
- Redis دائم وإلزامي في الإنتاج.

`render.yaml` مخصص للتجربة المبسطة، وليس الإطلاق التجاري النهائي.

## المتغيرات الأساسية

- `BOT_TOKEN`
- `ADMIN_IDS`
- `DATABASE_URL`
- `REDIS_URL`
- `ENCRYPTION_KEY`
- `PUBLIC_BASE_URL`
- `WEBHOOK_SECRET_TOKEN`
- `REQUIRE_EXTERNAL_DATABASE=true`
- `REQUIRE_REDIS_IN_PRODUCTION=true`
- `TIMEZONE=Asia/Baghdad`

## قاعدة البيانات

رأس Alembic الحالي:

```text
1130_friends_warranty
```

قبل التشغيل:

```bash
alembic upgrade head
```

## التحقق المحلي

بعد تثبيت المكتبات:

```bash
python scripts/validate_v11_1_student_commerce.py
python scripts/validate_v11_2_provider_operations.py
python scripts/validate_v11_3_friends_warranty.py
pytest -q tests/test_v11_foundation_domain.py \
  tests/test_v11_1_student_commerce.py \
  tests/test_v11_2_provider_operations.py \
  tests/test_v11_3_friends_warranty.py
```

## ما لا تزال النسخة تحتاجه

V11.3 مرحلة تطوير قوية، لكنها ليست النسخة النهائية الكاملة للبوت. المراحل التالية تتضمن لوحة المالك المالية الكاملة، الإعلانات، الباقات الهجينة، المهام والمكافآت، والتقارير Free/Plus/Pro النهائية.
