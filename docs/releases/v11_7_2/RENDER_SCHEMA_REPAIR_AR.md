# CampusPass IQ V11.7.2 — Render Schema Repair

هذا إصلاح إضافي وآمن لقواعد البيانات القديمة التي لا تحتوي العمود:

`cp_payment_proofs.file_fingerprint`

الإصلاح:
- لا يحذف أي جدول أو سجل.
- لا يغيّر الطلبات أو وصولات الدفع القديمة.
- يضيف العمود والفهرس فقط عند غيابهما.
- يمكن تشغيله أكثر من مرة بأمان.

ويبقى REDIS_URL إعداداً خارجياً: يجب أن تكون خدمة Render Key Value في نفس Region للخدمتين Web وWorker، وأن تُستخدم Internal Redis URL كاملة.
