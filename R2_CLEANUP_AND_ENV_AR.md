# R2 — تنظيف آمن ومتغيرات البيئة

## ما حُذف
- `.pytest_cache` و`__pycache__` وملفات `*.pyc/*.pyo`.
- ملفات Patch القديمة: `PATCH.diff`, `PATCH_FILE_LIST.txt`, `PATCH_MANIFEST*.json`, `PATCH_SHA256SUMS.txt`.

هذه الملفات لا تدخل في تشغيل البوت ولا قاعدة البيانات.

## ما لم يُحذف بعد
- مسارات التقارير والعروض وFSM القديمة؛ لأنها ما زالت البديل التشغيلي إلى أن تكتمل Web Apps وتنجح اختبارات الترحيل.
- اختبارات legacy والوثائق القديمة؛ تحتاج مراجعة اعتماد قبل حذفها لأنها قد تُستخدم للتحقق أو الرجوع.

## ملفات البيئة الجديدة
- `RENDER_FREE_REQUIRED_VARIABLES.example`: المتغيرات الأساسية والموصى بها لـRender Free.
- `ENV_ALL_VARIABLES.example`: سجل كامل لكل متغيرات `app/core/config.py` وعددها 231.

لا تضع أسرارك الحقيقية داخل الملفات أو GitHub؛ أدخلها مباشرة في Render Environment.
