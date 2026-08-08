# دليل الترقية الآمنة إلى V4

## ما الذي يبقى محفوظًا؟

- المستخدمون والملفات الدراسية.
- المنصات والموظفون.
- العروض والطلبات وإثباتات الدفع.
- المخزون القديم والإيميلات والتذاكر والمالية.
- إعدادات الأزرار والباقات والكوبونات.

العروض القديمة تُربط تلقائيًا بقسم وخدمة وسياسة مدة افتراضية مبنية على `duration_days`.

## متغيرات جديدة

```env
PURCHASE_RESERVATION_MINUTES=15
DELIVERY_RETRY_SECONDS=30
DELIVERY_MAX_ATTEMPTS=3
PROCESSING_INDICATOR_DELAY_MS=650
PROCESSING_MESSAGE_TEXT=⏳ جاري معالجة طلبك، يرجى الانتظار...
EMAIL_POLL_SECONDS=20
EMAIL_RESERVATION_MINUTES=10
EMAIL_AMBIGUITY_POLICY=review
MAX_CODE_ATTEMPTS=3
MAINTENANCE_MODE=false
```

القيم الافتراضية موجودة داخل الكود، لكن إضافتها إلى Railway يجعل التشغيل واضحًا ويمكن التحكم به دون Patch.

## قاعدة البيانات

V4 يستخدم ثلاثة IDs للترقية:

```text
3.2.0-ui-manager
3.3.0-catalog-subscriptions-outbox
4.0.0-platform-foundation
```

كل ID ينفذ مرة واحدة فقط ويُحفظ في `cp_schema_migrations`.

## اختبار ترقية منفذ

تم إنشاء قاعدة SQLite بهيكل V3.2 وفيها:

- طالب حقيقي الاسم.
- منصة.
- عرض قديم.
- طلب بانتظار الدفع.

ثم شُغلت V4. النتيجة:

- بقيت السجلات الأربعة دون تغيير.
- أُنشئ القسم والخدمة وربط العرض.
- أُنشئت سياسة 30 يومًا من العرض القديم.
- أُنشئ Workflow للعرض وحالة Workflow للطلب.
- أُنشئت 14 وحدة و6 قوالب رسائل.

هذا اختبار محلي، وليس بديلًا عن Backup PostgreSQL الحي.

## قاعدة مهمة جدًا

لا تبدل `ENCRYPTION_KEY` بعد إضافة أكواد أو حسابات أو كلمات مرور بريد. نسخة GitHub لا تحتوي هذه القيمة، وRailway هو المكان الصحيح لحفظها.
