# V11.6 — Render Staging, E2E and Production Hardening

## الجديد

- Webhook موثّق بـSecret Token.
- Durable Telegram Update Inbox.
- Consumers متعددة مع `SKIP LOCKED` وLease وRetry وDead Letter.
- فحص Pre-deploy لقاعدة البيانات وRedis وTelegram والمهاجرات.
- Readiness ديناميكية مرتبطة بحالة الـWorker والـWebhook والإصدار.
- سجلات Deployment Gate في PostgreSQL.
- Smoke Test بعد النشر.
- Blueprint مستقل للتجربة وBlueprint منقسم للإنتاج.
- Cleanup دوري لسجلات تحديثات Telegram المكتملة.
- Release ID مستقر بين عمليات الخدمة التابعة لنفس Git Commit.

## ما لم يتغير

كل ميزات الطالب والمنصة والمالك والضمان والأصدقاء والتقارير والهوية بقيت موروثة من V11.5.
