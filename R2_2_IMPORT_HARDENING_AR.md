# R2.2 — Import/API Hardening

- إصلاح تعارض `app.bot.ui` بعد تحويله من module إلى package.
- نقل واجهة UI القديمة إلى `app/bot/ui/runtime.py` مع Compatibility exports من `app/bot/ui/__init__.py`.
- إضافة Build Gate جديد `scripts/validate_ui_public_api.py` لمنع تكرار خطأ `edit_or_send` مستقبلًا.
- إصلاح تنظيف Docker ليبحث عن `__pycache__` بالاسم الصحيح.
- اجتياز compileall وفحص ثابت لجميع imports من `app.bot.ui` بدون أخطاء.
