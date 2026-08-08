CampusPass IQ — Render Free First
=================================

هذه الحزمة مخصصة للخطة المجانية في Render.

المهم:
1) احذف الـBlueprint القديم الفاشل الذي أنشأ Web + Worker، أو اتركه متوقفاً.
2) ارفع محتويات هذه الحزمة إلى جذر GitHub.
3) Render > New > Blueprint > اختر المستودع.
4) لا تكتب Blueprint Path؛ سيقرأ Render الملف render.yaml تلقائياً.
5) سيظهر مورد واحد فقط: campuspass-iq-free (Web / Free).
6) أدخل الأسرار السبعة المطلوبة عند الإنشاء.
7) لا تنشئ Worker، ولا تضف REDIS_URL في أول تشغيل.

الأسرار المطلوبة:
- BOT_TOKEN
- ADMIN_IDS
- DATABASE_URL
- ENCRYPTION_KEY
- TELEGRAM_WEBHOOK_SECRET
- API_ADMIN_TOKEN
- METRICS_TOKEN

التغييرات عن النسخة المدفوعة:
- RUNTIME_MODE=combined
- Web واحدة تشغّل البوت والمهام الدورية
- لا Background Worker
- لا preDeployCommand
- Redis اختياري
- migrations تعمل عند بدء التطبيق
- health check هو /health/live

لم تُحذف أي Handler أو Service أو Model أو Migration أو ميزة تجارية.
