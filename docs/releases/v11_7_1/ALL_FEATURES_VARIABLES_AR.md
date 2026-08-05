# متغيرات الميزات الإضافية

لا تضع هذه القيم في GitHub. أضفها إلى Render Environment لكل من Web وWorker حيث يلزم.

## Gemini

```env
FEATURE_GEMINI=true
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.6-flash
```

احصل على المفتاح من Google AI Studio. إذا بقي المفتاح فارغاً، يبقى الدعم التقليدي والتذاكر شغالاً.

## بوابة Mastercard

الكود يحتوي Adapter عام، لكن القيم الدقيقة تأتي من البنك أو شركة الدفع المتعاقدة:

```env
FEATURE_MASTERCARD=true
PAYMENT_GATEWAY_CREATE_URL=
PAYMENT_GATEWAY_STATUS_URL=
PAYMENT_GATEWAY_API_KEY=
PAYMENT_GATEWAY_MERCHANT_ID=
PAYMENT_WEBHOOK_SECRET=
MONEY_FLOW_MODEL=gateway_marketplace
```

`PAYMENT_WEBHOOK_SECRET` يجب أن يكون 32 حرفاً أو أكثر.

## سحب أرباح المنصات

```env
FEATURE_PROVIDER_WITHDRAWALS=true
MONEY_FLOW_MODEL=gateway_marketplace
```

لا يصبح السحب جاهزاً إلا بعد اكتمال بوابة الدفع، لأن النظام لا يجوز أن يسمح بسحب أموال لم يحتفظ بها فعلياً.

## النسخ الاحتياطي S3

```env
BACKUP_ENABLED=true
BACKUP_STORAGE_BACKEND=s3
BACKUP_S3_ENDPOINT=
BACKUP_S3_BUCKET=
BACKUP_S3_REGION=auto
BACKUP_S3_ACCESS_KEY=
BACKUP_S3_SECRET_KEY=
```

يدعم AWS S3 وCloudflare R2 وMinIO وأي تخزين S3-compatible.

## أرشفة الأدلة الخارجية

```env
EVIDENCE_EXTERNAL_STORAGE_ENABLED=true
EVIDENCE_S3_ENDPOINT=
EVIDENCE_S3_BUCKET=
EVIDENCE_S3_REGION=auto
EVIDENCE_S3_ACCESS_KEY=
EVIDENCE_S3_SECRET_KEY=
```

يمكن استعمال نفس حساب S3، لكن يفضّل Bucket منفصل للأدلة.

## فحص الصور

يعمل محلياً مباشرة من دون مفتاح:

```env
IMAGE_MODERATION_ENABLED=true
IMAGE_MODERATION_PROVIDER=auto
IMAGE_MODERATION_FAIL_CLOSED=false
GOOGLE_VISION_API_KEY=
```

عند إضافة `GOOGLE_VISION_API_KEY` يستخدم النظام SafeSearch تلقائياً. من دون المفتاح يستمر فحص سلامة الصورة والصيغة والحجم والأبعاد محلياً.
