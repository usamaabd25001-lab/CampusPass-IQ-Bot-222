CampusPass IQ V11.7.2 Render Hotfix

المشكلة:
ProviderPaymentMethodStates.proof_guide كان مستخدماً في provider_catalog.py وmiddleware.py، لكنه غير معرّف داخل app/bot/states.py.

الإصلاح:
إضافة السطر التالي إلى ProviderPaymentMethodStates:
    proof_guide = State()

طريقة التطبيق:
انسخ مجلد app من هذه الحزمة فوق مجلد app داخل مستودع GitHub، ثم Commit وPush.
لا يحذف أو يغير أي ميزة أخرى.
