# سجل تغييرات V6.7 — Privacy & Evidence

## Added
- PrivacyService وEvidenceService.
- تشفير حقلي للاسم والهاتف وبيانات التفعيل.
- EvidenceAsset وEvidenceAccessLog وSecretAccessLog وPrivacyRequest.
- `/privacy`, `/my_data`, `/process_privacy`.
- زر `🔐 خصوصيتي` في القائمة.
- موافقة AI وتنظيف PII قبل الإرسال.
- S3/R2/MinIO encrypted evidence adapter.
- تشخيص الأدلة وطلبات الحذف.
- ترحيل تدريجي للمرفقات القديمة.

## Changed
- إثبات الدفع يرسل للمراجع عبر EvidenceService.
- شاشة الطلب الإدارية تعرض بيانات التفعيل مخفية أولاً.
- ملفات تصدير المستخدم تخفي كلمات المرور والرموز.
- سياسة الخصوصية الافتراضية أصبحت أوضح.
- Scheduler يدير الأرشفة والحذف والطلبات المستحقة.

## Security
- منع حفظ Telegram file IDs الجديدة في حقول الأعمال النصية.
- تسجيل فتح الأدلة والأسرار.
- حذف المرفقات بعد انتهاء مدة الاحتفاظ.
- منع AI من العمل دون موافقة المستخدم.
