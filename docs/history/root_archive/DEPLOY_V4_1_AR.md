# نشر CampusPass IQ 4.1.0 على Railway

## قبل الرفع

1. خذ Backup من PostgreSQL.
2. احتفظ بقيمة `ENCRYPTION_KEY` الحالية دون أي تغيير إذا عندك مخزون أو حسابات بريد مشفرة.
3. ارفع محتويات ZIP إلى جذر مستودع GitHub، وليس داخل مجلد فرعي.
4. تأكد أن `VERSION.txt` يحتوي `4.1.0`.

## الأسرار المطلوبة

شغّل محليًا:

```bash
python scripts/generate_secrets.py
```

انسخ القيم الناتجة إلى Railway Variables. عند ترقية نظام مستخدم فعليًا، لا تستبدل `ENCRYPTION_KEY` القديم؛ استخدم السكربت فقط للقيم الجديدة الأخرى أو لنشر جديد.

المتغيرات الإلزامية في Production:

- `BOT_TOKEN`
- `ADMIN_IDS`
- `DATABASE_URL` من PostgreSQL
- `PUBLIC_BASE_URL` كرابط HTTPS الحقيقي للخدمة
- `ENCRYPTION_KEY`
- `REPORT_SECRET_KEY`
- `API_ADMIN_TOKEN`

يوصى بإضافة خدمة Redis ووضع رابطها في `REDIS_URL`.

## الدفع بالبطاقة

ابقِ `FEATURE_MASTERCARD=false` حتى تستلم عقد وSchema البوابة الحقيقي. عند التفعيل اضبط:

- `PAYMENT_GATEWAY_CREATE_URL`
- `PAYMENT_GATEWAY_API_KEY`
- `PAYMENT_GATEWAY_MERCHANT_ID`
- `PAYMENT_WEBHOOK_SECRET`

سجل Webhook لدى البوابة على:

```text
https://YOUR-DOMAIN/webhooks/payments/mastercard
```

يجب أن ترسل البوابة توقيع HMAC SHA-256 في Header باسم `X-Signature`. إذا كانت البوابة تستخدم خوارزمية أو أسماء حقول مختلفة، عدّل فقط `app/integrations/payments/mastercard.py` حسب وثائق البنك.

## فحوصات ما بعد النشر

افتح:

```text
/health/live
/health/ready
```

لفحص التفاصيل استخدم:

```bash
curl -H "Authorization: Bearer $API_ADMIN_TOKEN" https://YOUR-DOMAIN/admin/health
```

لإلغاء رابط تقرير مسرّب أو قديم:

```bash
curl -X POST -H "Authorization: Bearer $API_ADMIN_TOKEN" \
  https://YOUR-DOMAIN/admin/reports/REPORT_ID/revoke
```

نفذ طلبًا تجريبيًا منخفض القيمة، ثم اختبر:

1. إنشاء الطلب وحجز المخزون.
2. الدفع أو رفع الإثبات.
3. تأكيد الطلب وتسليمه.
4. إكمال الطلب وظهور التقييم.
5. فتح تقرير والتأكد أن البريد مخفي جزئيًا.

## الرجوع الآمن

يمكن الرجوع إلى كود 4.0.1 لأن V4.1 لا تحذف الجداول القديمة. لا تحذف الجداول الجديدة أثناء الرجوع؛ اتركها حتى تعود إلى 4.1.0. أوقف `FEATURE_MASTERCARD` أولًا إذا كان سبب الرجوع متعلقًا بالبوابة.
