# CampusPass IQ — نشر Render المجاني

هذه النسخة مخصصة لحساب Render المجاني:

- خدمة Web واحدة فقط.
- `RUNTIME_MODE=combined` لتشغيل البوت والمهام الدورية في نفس العملية.
- لا Background Worker مدفوع.
- لا `preDeployCommand` مدفوع؛ التطبيق ينفذ migrations الآمنة عند بدء التشغيل.
- Redis اختياري، وليس مطلوباً لبدء البوت.
- قاعدة PostgreSQL/Supabase تبقى خارجية ودائمة.

## طريقة النشر

1. ارفع محتويات الحزمة إلى جذر GitHub.
2. في Render اختر **New → Blueprint**.
3. Blueprint Path: `render.free.yaml`
4. أدخل الأسرار المطلوبة فقط:
   - `BOT_TOKEN`
   - `ADMIN_IDS`
   - `DATABASE_URL`
   - `ENCRYPTION_KEY`
   - `TELEGRAM_WEBHOOK_SECRET`
   - `API_ADMIN_TOKEN`
   - `METRICS_TOKEN`
5. لا تضف `REDIS_URL` في أول نشر.

## ملاحظة حدود الخطة المجانية

Render يوقف خدمة الويب المجانية بعد فترة خمول. عند وصول تحديث Telegram ستستيقظ الخدمة، وقد يتأخر أول رد. المهام الدورية لا تعمل أثناء نوم الخدمة، وتُستأنف بعد الاستيقاظ. هذه حدود Render المجاني وليست حذفاً لميزات البوت.
