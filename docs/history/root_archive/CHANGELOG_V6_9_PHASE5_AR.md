# سجل تغييرات V6.9 Phase 5

- إضافة سجل الإصدارات والنشر.
- إضافة Runtime modes: combined/bot/worker.
- Readiness حسب المكونات.
- Scheduled runs دائمة مع leases.
- إصلاح ضياع التقرير عند فوات الدقيقة أو Restart.
- نسخ PostgreSQL مشفر إلى S3-compatible storage.
- تحقق SHA-256 بعد الرفع.
- Backup اختياري قبل Migration.
- أداة Restore خارجية بتأكيد صريح.
- سجل أعطال مركزي.
- Multi-key decryption وتدوير تدريجي.
- Staging token isolation.
- أوامر تشغيل عربية للمالك.
- أدوات Preflight وBackup وRestore.

- فصل هوية سجل النشر حسب runtime component.
- التقاط RAILWAY_DEPLOYMENT_ID وRAILWAY_GIT_COMMIT_SHA تلقائياً.
- معالجة سباق إنشاء ScheduledRun وDeploymentRelease بمعاملة فرعية وقيد فريد.
- إضافة RuntimeIncident إلى `/recent_errors`.
- تثبيت PostgreSQL client داخل صورة التشغيل.
