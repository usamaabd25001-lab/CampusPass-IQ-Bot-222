# CampusPass New Bot V11.1 — ابدأ من هنا

هذه نسخة تطوير مستقلة مشتقة من CampusPass IQ V10.7. لا تستخدم قاعدة بيانات أو Bot Token أو Redis النسخة القديمة.

## ما تحتويه هذه المرحلة

### V11.0 Foundation

- تثبيت 85 مطلباً معتمداً داخل المشروع.
- إزالة Runtime الخاص بالنزاعات القديمة وطلبات الخصوصية المخفية.
- قاعدة المحفظة الجديدة.
- نواة نظام الحالة والمكافآت.
- نواة باقة أصدقائي فقط.
- حماية التكرار والعمليات الحساسة.

### V11.1 Student Commerce

- Web App عربية لإكمال وتعديل ملف الطالب.
- تحقق مشفّر من Telegram `initData` ومنع انتحال الهوية.
- بوابة تمنع دخول المتجر بملف ناقص.
- المنصات والأقسام والخدمات والعروض الديناميكية.
- المفضلة متعددة المستويات.
- Checkout Snapshot يحفظ تفاصيل الفاتورة كاملة.
- الخصم التلقائي الكامل لرسوم البوت من المحفظة فقط.
- بصمة لإثبات الدفع ومنع إعادة استعماله.
- فحص صلاحية صاحب المنصة قبل مراجعة الدفع.
- Migration `1110_student_commerce`.

## التحقق السريع

بعد تثبيت المتطلبات:

```bash
python scripts/validate_v11_foundation.py
python scripts/validate_v11_1_student_commerce.py
pytest -q
```

## التشغيل

استخدم Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.main
```

## متغيرات مستقلة إلزامية

- `BOT_TOKEN`
- `DATABASE_URL`
- `REDIS_URL`
- `PUBLIC_BASE_URL` لفتح Web App عبر HTTPS
- مفاتيح التشفير والأسرار الخاصة بالنسخة الجديدة

لا تنسخ أسرار البوت القديم.

## المرجع الملزم

- `MASTER_SPEC.md`
- `REQUIREMENTS_REGISTER.json`
- `DECISION_LOG.md`
- `TRACEABILITY_MATRIX.md`
- `IMPLEMENTATION_ROADMAP.md`
- `STUDENT_COMMERCE_VALIDATION_REPORT_AR.md`
