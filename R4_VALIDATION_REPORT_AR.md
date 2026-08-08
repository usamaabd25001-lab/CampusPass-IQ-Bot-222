# CampusPass IQ — تقرير فحص R4

الإصدار: `11.8.0-provider-commerce-webapp`

## نطاق المرحلة

هذه المرحلة تركز على إدارة المنصة والعروض فقط. لم تتم إعادة تصميم رحلة الطالب في هذه الحزمة.

- إضافة منصة عبر Telegram Web App متسلسل وآمن.
- إضافة عرض عبر Telegram Web App متسلسل ومتفرع.
- حفظ Draft والرجوع خطوة حقيقية للخلف داخل Web Apps.
- تقوية عقد أزرار الرجوع في واجهات البوت الحرفية.
- إضافة عمولة خدمة افتراضية للمنصة تُنسخ Snapshot إلى العرض الجديد.
- جعل شعار المنصة اختياريًا مع معاينة واعتماد وتغيير لاحق.
- دعم الحساب الخاص/المشترك، المخزون، OTP، التفعيل على بريد الطالب، الاستخدام المؤقت، الضمان، والتعليمات عبر خدمات المشروع القائمة.
- Gemini ككاتب وصف فقط، وليس كمدقق لبيانات الأعمال.

## نتائج الفحص قبل التغليف

تم تشغيل الفحوصات التالية بنجاح داخل بيئة العمل:

- `python -m compileall -q app scripts ops alembic`
- `python -m scripts.validate_ai_support_integration`
- `python -m scripts.validate_import_architecture`
- `python -m scripts.validate_webapp_contract`
- `python -m scripts.validate_navigation_contract`
- `python -m scripts.render_build_verify --static-only`
- `pytest -q tests/test_webapp_validation.py`
- فحص JavaScript بالقالبين الجديدين بواسطة `node --check`.

نتيجة Render Static Verify وقت الإصدار:

- Python files: 278
- FSM state groups: 82
- FSM state references: 580
- Local app imports checked: 806
- Web App validation tests: 21 passed
- Literal inline buttons checked by navigation contract: 691

## حدود الفحص المحلي

`validate_ui_public_api` وRender runtime import verification لم يتمكنا من العمل في بيئة التجهيز المحلية لأن حزمة `aiogram` غير مثبتة في هذه البيئة. هذا ليس تجاوزًا للبوابة: Dockerfile يشغلهما داخل صورة Render **بعد تثبيت requirements**، ولذلك سيظل النشر يفشل تلقائيًا إذا ظهر ImportError فعلي في بيئة الإنتاج.

رسالة `Gemini circuit opened after 1 consecutive temporary failures` التي تظهر أثناء اختبار دمج الذكاء هي جزء من اختبار الـCircuit Breaker، وقد أكمل Validator بعدها بنجاح.

## قاعدة الأمان

لا تعتمد الواجهات على `Telegram.WebApp.sendData()`. جميع عمليات الحفظ تستخدم `fetch()` مع `X-Telegram-Init-Data`، ثم يعاد التحقق من توقيع Telegram ومن صلاحية المستخدم على السيرفر، ثم Pydantic + Service validation قبل الكتابة في PostgreSQL.
