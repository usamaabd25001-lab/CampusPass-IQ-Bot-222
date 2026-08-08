# CampusPass IQ V10.7 — Emergency Stabilization

- تثبيت Reply Keyboard على رسالة الرئيسية النهائية وإزالة deleted-carrier workaround.
- Navigation Coordinator يفصل Back عن Home ويحافظ على FSM data عند الرجوع.
- Provider Access Resolver typed موحد لـSUPER_ADMIN/OWNER/MANAGER/STAFF.
- صلاحيات OWNER وSUPER_ADMIN effective بالكامل دون الاعتماد على booleans تاريخية.
- دعم تعدد المنصات وlegacy callbacks مع provider context صريح وأسباب رفض دقيقة.
- cache قصير مع targeted invalidation بعد commit.
- تبسيط «متجري والعروض» إلى: إضافة عرض، عروضي، تنظيم المتجر.
- رفع شعار محلي ذري: تحقق MIME/صيغة/حجم/أبعاد → معاينة → تأكيد/إلغاء.
- إزالة الاعتماد التشغيلي على Google Vision.
- محرر إداري لرسالة `/start` مع cache وHTML validation واستعادة الافتراضي.
- Migration 1070 additive/reversible وaudit غير حساس لصفوف الصلاحيات.
- Healthcheck Railway أصبح `/health/live` مع إبقاء `/health/ready` للتشخيص.
