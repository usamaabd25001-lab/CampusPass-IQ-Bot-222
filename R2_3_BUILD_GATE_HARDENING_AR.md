# R2.3 - تحصين بوابة البناء على Render

تم إصلاح فشل البناء الذي ظهر عند تشغيل `scripts/validate_ui_public_api.py` مباشرة، حيث كان Python يضع مجلد `scripts` في مقدمة `sys.path` ولا يجد حزمة `app`.

## التغييرات

- جعل `scripts` حزمة Python صريحة بإضافة `scripts/__init__.py`.
- جعل `validate_ui_public_api.py` يضيف جذر المشروع إلى `sys.path` عند التشغيل المباشر.
- تشغيل جميع فحوصات Docker بصيغة modules عبر `python -m scripts...`.
- إضافة فحص مبكر داخل Docker يؤكد إمكانية `import app, scripts` من `/app`.
- تحديث `render_build_verify.py` لقبول صيغة module الجديدة والتحقق من وجود فحص UI.
- إبقاء تنظيف `__pycache__` بعد انتهاء بوابة البناء.

## التحقق المنفذ قبل التغليف

- `compileall` نجح.
- `render_build_verify --static-only` نجح بصيغة module وبصيغة script path.
- تم تحليل 272 ملف Python بدون أخطاء AST.
- تم فحص 773 مسار import محلي من `app` بدون وحدات مفقودة.
- تم فحص 581 مرجع FSM بدون حالات غير معرفة.

فحص imports الكامل الذي يعتمد على المكتبات الخارجية يبقى جزءًا من Docker build نفسه بعد تثبيت `requirements.txt`، وهو ما يفعله Render قبل تشغيل الخدمة.
