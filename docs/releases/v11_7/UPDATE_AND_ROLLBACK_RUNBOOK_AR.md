# Runbook التحديث والرجوع — V11.7

## قبل النشر
1. خذ نسخة احتياطية قابلة للتحقق من PostgreSQL.
2. تحقق أن الإصدار الحالي لا يقل عن `UPDATE_MIN_COMPATIBLE_VERSION`.
3. لا تحذف أعمدة أو جداول مستخدمة في الإصدار السابق ضمن نفس النشر.
4. أضف الحقول الجديدة بصورة nullable أو مع default آمن.
5. أبق Callback aliases القديمة خلال نافذة التوافق.
6. شغّل Validators و`ops/render_predeploy.py`.

## أثناء النشر
- ابدأ بالـMigration المتوافقة.
- دع Render يرسل SIGTERM للإصدار القديم.
- يدخل القديم وضع drain ويكمل المعالجة المحجوزة.
- أي Webhook جديد يحصل على 503 مؤقتاً ويعيد Telegram تسليمه.
- لا تعتبر النسخة جاهزة قبل `/health/ready`.

## Canary اختياري
- ابدأ بقيمة صغيرة في `UPDATE_ROLLOUT_PERCENT` للميزات الجديدة غير المالية.
- لا تستخدم rollout جزئياً لقيود قاعدة بيانات لا يمكن للإصدار السابق فهمها.

## الرجوع
- أعد نشر Image/Commit السابق أولاً.
- لا تنفذ Alembic downgrade تلقائياً في الإنتاج.
- لأن الهجرات Expand-Contract، يستطيع الإصدار السابق تجاهل الجداول والحقول الجديدة.
- نفذ Contract cleanup في إصدار منفصل بعد انتهاء نافذة الرجوع.

## حالات توقف النشر
- فشل Compatibility Contract.
- رأس Alembic غير مطابق.
- Redis أو PostgreSQL غير جاهزين.
- Worker heartbeat قديم.
- Webhook غير مطابق.
- Smoke test لا يمر.
