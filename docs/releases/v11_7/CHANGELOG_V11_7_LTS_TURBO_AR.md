# سجل تغييرات V11.7 — LTS Turbo & Update Safety

## الأساس
- مشتق من V11.6 من دون حذف أي مسار تجاري أو إداري سابق.
- الإصدار النهائي لهذه الحزمة: `11.7.0-lts-turbo-update-safe`.

## سرعة استقبال Telegram
- إيقاظ Consumers مباشرة بعد حفظ Webhook بدلاً من انتظار polling داخلي ثابت.
- Claim بدُفعات من صندوق PostgreSQL باستخدام `FOR UPDATE SKIP LOCKED`.
- عدد Consumers وBatch size وIdle wait قابلة للضبط.
- `orjson` لفك JSON واستجابات FastAPI.
- `uvloop` و`httptools` عند توفرهما داخل صورة Linux.
- Uvicorn backlog/concurrency/keep-alive قابلة للضبط.

## النشر بلا ضياع
- Graceful drain: رفض تحديثات جديدة بـ503 أثناء الإغلاق كي يعيد Telegram إرسالها، مع إكمال التحديثات المحجوزة قبل إنهاء العملية.
- تتبع inflight updates في Health وMetrics.
- عقود توافق للإصدار والمخطط وCallback/Event schema.
- استراتيجية Expand-Contract إلزامية للتحديثات المتوافقة.
- دعم staged rollout بواسطة نسبة ثابتة وحتمية.

## توافق الواجهة
- Callback schema version 1.
- Aliases للأزرار القديمة مع رفض صيغ مستقبلية غير معروفة بدلاً من تفسيرها خطأ.
- Middleware يطبّع الـCallbacks قبل وصولها إلى Routers.

## Cache Coherence
- Generations مشتركة في PostgreSQL للقوائم والمزايا والقوالب والهوية.
- إبطال Cache بين Web والـWorker بعد التعديل من لوحة المالك.
- قاعدة البيانات تبقى مصدر الحقيقة.

## قاعدة البيانات
- Migration: `1170_lts_turbo_update_safe`.
- الجداول الجديدة:
  - `cp_runtime_config_generations`
  - `cp_release_compatibility`
