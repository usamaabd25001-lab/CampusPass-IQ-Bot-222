# R4.1 - إصلاح عقد Build الخاص بإنشاء العروض

## السبب
كان نموذج `OfferCreateRequest` قد تطور في R4 ليطلب حقولًا جديدة مثل:
- `fulfillment_kind`
- `guide_text`
- اختيار صريح لقيمة `warranty_enabled`

لكن عينة التحقق داخل `scripts/render_build_verify.py` بقيت تستخدم العقد القديم، ومنها
`delivery_type` و`activation_mode`. لذلك نجحت فحوصات المعمارية والاستيراد ثم فشل Build عند
إنشاء نموذج Pydantic التجريبي.

## الإصلاح
- تحديث عينة `OfferCreateRequest` لتطابق العقد الحالي بالكامل.
- إزالة الحقول القديمة من عينة التحقق.
- إضافة فحص AST داخل `validate_webapp_contract.py` يقارن حقول نموذج Pydantic مع عينة
  `render_build_verify.py` ويمنع وجود حقول مطلوبة مفقودة أو حقول قديمة غير معروفة.
- اعتبار `warranty_enabled` مطلوبًا دلاليًا في فحص العقد لأنه مطلوب عبر `model_validator`.

## التحقق
- `pytest -q tests/test_webapp_validation.py` => 21 passed.
- `python -m scripts.render_build_verify --static-only` => passed.
- `python -m scripts.validate_webapp_contract` => passed.
- `python -m scripts.validate_import_architecture` => passed.
- `python -m scripts.validate_navigation_contract` => passed.
- عينة `OfferCreateRequest` الجديدة تم تشغيلها منفردة على Pydantic 2.13.4 ونجحت.

ملاحظة: Runtime import الكامل الذي يحتاج aiogram يبقى ضمن Docker Build على Render بعد تثبيت
المتطلبات، كما في R4.
