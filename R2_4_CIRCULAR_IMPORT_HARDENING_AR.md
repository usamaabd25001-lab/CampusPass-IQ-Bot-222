# R2.4 — Circular Import Hardening

## المشكلة
إعادة هيكلة `app.bot.ui` إلى package أدخلت اعتمادًا دائريًا فعليًا:

`app.bot.keyboards.inline -> app.bot.ui.button_styles -> app.bot.ui.__init__ -> app.bot.ui.runtime -> app.bot.keyboards.inline`

هذا النوع لا يكتشفه `compileall` لأنه خطأ في ترتيب الاستيراد وقت التشغيل، لا خطأ Syntax.

## الحل المعماري
- إرجاع `app.bot.ui` إلى module واحد مستقر (`app/bot/ui.py`) للحفاظ على API التاريخية.
- نقل سياسة ألوان الأزرار إلى `app/bot/button_styles.py` لأنها طبقة مستقلة ولا تعتمد على UI runtime.
- جعل `inline.py` يعتمد على `button_styles.py` فقط.
- إزالة package المتعارض `app/bot/ui/` نهائيًا.
- إبقاء دوال سياسة الألوان متاحة من `app.bot.ui` كتوافق خلفي.

## بوابة منع التكرار
أضيف `scripts/validate_import_architecture.py` إلى Docker Build Gate. يفشل البناء عند:
- وجود module وpackage بالاسم نفسه؛
- استيراد `app.bot.ui` أو handlers من طبقة keyboards؛
- اعتماد سياسة الألوان على UI أو inline؛
- تغير الشكل المعماري المتوقع.

## ملاحظة
نقل import داخل function قد يخفي بعض circular imports مؤقتًا، لكنه ليس الحل المعتمد هنا لأن الاعتماد المعماري الخاطئ يبقى قائمًا وقد يظهر في مسار تشغيل مختلف.
