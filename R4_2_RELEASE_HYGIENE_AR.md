# CampusPass IQ — R4.2 Release Hygiene & Build Hardening

الإصدار: `11.8.2-provider-commerce-webapp-release-hygiene`

## لماذا هذا الإصدار؟

R4.1 كشف أن مستودعًا طويل العمر يمكن أن يحتوي أكثر من تمثيل لنفس الحقيقة: إصدار التطبيق، إصدار قاعدة البيانات، ملفات Render، Validators تاريخية، واختبارات قديمة. هذه العناصر مفيدة للأرشفة، لكنها لا يجب أن تتحكم بصورة الإنتاج الحالية.

## الإصلاحات

- مزامنة `VERSION.txt` مع `app.__version__` وإضافة Release Hygiene Gate مبكر قبل `compileall`.
- فصل **إصدار التطبيق** عن **Schema Head**: تحديث برمجي Patch لا يحتاج Migration وهمية. البناء يمنع فقط أن تكون Migration أحدث من التطبيق.
- فحص ترتيب وعدم تكرار Custom Migrations.
- توسيع Import Architecture Gate ليتحقق من الرموز المستوردة داخليًا (`from app.x import Y`) بالـAST، وليس مسار الملف فقط.
- تصحيح Render Free region إلى `frankfurt` وتوحيد حدود Free Tier المحافظة.
- تحويل `RENDER_VARIABLES.txt` إلى الملف اليدوي الرسمي للـFree profile، وأرشفة ملف Paid/Split التاريخي داخل `docs/history`.
- عزل اختبارات V10 التاريخية في `tests_legacy/v10` لكي لا تفرض عقودًا تجارية ملغاة على Current Test Suite.
- توسيع `.dockerignore` لعزل docs/examples/tests/legacy validators/caches عن صورة Render مع بقائها في المصدر الكامل.
- إضافة `scripts/build_deploy_bundle.py` لبناء ZIP نشر deterministic مع SHA-256 manifest.

## حدود Render Free المعتمدة في ملفات النشر

- DB pool: 3 + overflow 2
- Telegram update consumers: 2
- Bot update concurrency: 8
- HTTP connection limit: 16
- Uvicorn concurrency: 50
- AI concurrency: 1
- Report concurrency: 1
- Long-operation concurrency: 2

هذه الحدود ليست جزءًا من Business Logic، ويمكن ضبطها لاحقًا بعد قياس حقيقي، لكنها تمنع ملفات Turbo/paid التاريخية من فرض قيم عدوانية على Free Tier.

## Build Contract

تسلسل Docker يبدأ الآن بـ Release Hygiene قبل إنشاء `__pycache__`، ثم compile/import/WebApp/navigation/UI/runtime gates، وفي النهاية ينظف cache artifacts.
