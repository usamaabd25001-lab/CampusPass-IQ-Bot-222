# CampusPass IQ — GitHub Operations Pack

هذه الحزمة مخصّصة لثلاث مهام فقط:

1. نسخة PostgreSQL احتياطية مشفّرة تعمل من GitHub Actions، ولا تعتمد على قرص السيرفر المؤقت.
2. فحص النسخة الاحتياطية أو استعادتها إلى قاعدة اختبار منفصلة.
3. اختبار ضغط وتزامن لطلبات المخزون، بما في ذلك محاولة مئات المستخدمين حجز العنصر نفسه باللحظة نفسها.

> صُممت الحزمة لتوضع في **جذر مستودع البوت نفسه**؛ لأن اختبار التزامن يستورد كود `app/` وخدمات CampusPass الحالية.

## لماذا تناسب السيرفر الذي يتبدل كل 30 يومًا؟

- الـWorkflow يعمل على GitHub Actions وليس داخل السيرفر.
- النسخ المشفرة تُرفع إلى Release ثابت اسمه `database-backups` داخل GitHub.
- لا توجد ملفات مهمة محفوظة على القرص المحلي للسيرفر.
- عند تبديل السيرفر، يكفي أن ينشر المستودع نفسه وأن تُعاد متغيرات تشغيل البوت على منصة الاستضافة.

## الملفات التي ستظهر بعد دمج الحزمة

```text
.github/workflows/database-backup.yml
.github/workflows/database-restore.yml
.github/workflows/concurrency-stress.yml
ops/common.py
ops/github_backup.py
ops/github_restore.py
loadtests/concurrent_orders.py
```

## إعداد GitHub Secrets

من المستودع افتح:

```text
Settings → Secrets and variables → Actions → New repository secret
```

أضف القيم التالية:

### مطلوب للنسخ الاحتياطي

```text
BACKUP_DATABASE_URL
BACKUP_ENCRYPTION_KEY
```

- `BACKUP_DATABASE_URL`: رابط PostgreSQL الحقيقي. يقبل أيضًا صيغة `postgresql+asyncpg://`.
- `BACKUP_ENCRYPTION_KEY`: مفتاح مختلف عن مفاتيح البوت، بطول 32 حرفًا على الأقل. احتفظ بنسخة خارج GitHub أيضًا، لأن فقدانه يجعل ملفات النسخ غير قابلة للفك.

### مطلوب لاختبار الضغط

```text
LOAD_TEST_DATABASE_URL
```

يجب أن يكون لقاعدة PostgreSQL **منفصلة وقابلة للحذف بالكامل**. اسم قاعدة البيانات يجب أن يحتوي إحدى الكلمات:

```text
load / stress / staging / stage / test / qa
```

الاختبار يقوم بإسقاط جداول قاعدة الاختبار وإعادة إنشائها، لذلك يمنع تشغيله على قاعدة الإنتاج عمدًا.

### اختياري لاختبار الاستعادة

```text
RESTORE_DATABASE_URL
```

يجب أن يشير إلى قاعدة استعادة/اختبار منفصلة، وليس إلى الإنتاج.

## إعداد Repository Variable اختياري

يمكن إضافة:

```text
BACKUP_RETENTION_DAYS=14
```

المدى المقبول داخل السكربت من 3 إلى 365 يومًا. تبقى أحدث ثلاث نسخ على الأقل حتى عند تنظيف الملفات القديمة.

## تشغيل النسخة الاحتياطية

تعمل يوميًا الساعة 00:15 UTC، أي 03:15 بتوقيت بغداد. ويمكن تشغيلها يدويًا:

```text
Actions → CampusPass Database Backup → Run workflow
```

الناتج داخل GitHub:

```text
Releases → CampusPass Encrypted Database Backups
```

كل نسخة تحتوي:

- PostgreSQL custom dump.
- Manifest يتضمن وقت الإنشاء وبصمة ملف الـdump.
- تشفير GPG AES-256.
- ملف SHA-256 منفصل.

## فحص النسخة دون استعادتها

```text
Actions → CampusPass Backup Verify or Restore → Run workflow
```

اختر:

```text
mode = verify
asset_name = الاسم الكامل للملف المنتهي بـ .tar.gz.gpg
```

سيتم فك الملف مؤقتًا، فحص البصمة، وتشغيل `pg_restore --list` للتأكد من أن النسخة قابلة للقراءة.

## استعادة نسخة إلى قاعدة اختبار

اختر:

```text
mode = restore
confirmation = RESTORE_TO_DEDICATED_DATABASE
```

يستخدم الـWorkflow قيمة `RESTORE_DATABASE_URL`، وينظف قاعدة الاستعادة ثم يعيد البيانات إليها.

## اختبار الطلبات المتزامنة

افتح:

```text
Actions → CampusPass Concurrent Orders Stress Test → Run workflow
```

القيم المقترحة لأول فحص:

```text
attempts = 500
inventory = 1
workers = 100
confirmation = RESET_DEDICATED_LOAD_TEST_DATABASE
```

هذا يعني: 500 محاولة شراء متزامنة لعرض يحتوي عنصر مخزون واحد فقط.

النجاح المتوقع:

- طلب واحد ناجح فقط.
- حجز واحد فقط.
- العنصر نفسه لا يرتبط بأكثر من Reservation.
- بقية المحاولات تُرفض برسالة نفاد المخزون.
- لا توجد أخطاء غير متوقعة.

بعدها جرّب تدريجيًا:

```text
1000 محاولة / 200 عامل
3000 محاولة / 300 عامل
5000 محاولة / 500 عامل
```

ارفع الأرقام تدريجيًا حسب حد اتصالات قاعدة الاختبار وإمكاناتها. النتيجة تُرفع كملف `load-test-result.json` ضمن Artifacts لكل تشغيل.

## متغيرات السيرفر عند تغييره

رفع هذه الحزمة إلى GitHub يجعل **الكود** يظهر في السيرفر عند النشر التلقائي، لكن الأسرار لا تُخزن داخل المستودع. عند إنشاء سيرفر جديد، يجب أن تبقى متغيرات تشغيل البوت في لوحة الاستضافة أو تُنسخ إليها:

```text
BOT_TOKEN
ADMIN_IDS
DATABASE_URL
REDIS_URL
ENCRYPTION_KEY
REPORT_SECRET_KEY
API_ADMIN_TOKEN
PUBLIC_BASE_URL
```

أما أسرار الـWorkflows (`BACKUP_DATABASE_URL` وما شابه) فتبقى داخل GitHub ولا تتأثر بتبديل السيرفر.

## Hotmail

هذه الحزمة لا تغيّر تكامل Hotmail ولا تحتاج وضع حسابات البريد في GitHub Secrets. حسابات Hotmail تبقى داخل قاعدة البيانات ومشفرة بواسطة `ENCRYPTION_KEY`. لذلك النسخة الاحتياطية مع الاحتفاظ بنفس `ENCRYPTION_KEY` تحفظ إعدادات البريد أيضًا.

## قواعد أمان مهمة

- استخدم مستودع GitHub خاصًا Private؛ النسخ مشفرة، لكن لا تجعل المستودع عامًا بلا حاجة.
- لا تضع روابط قواعد البيانات أو المفاتيح داخل أي ملف committed.
- لا تستخدم قاعدة الإنتاج في `LOAD_TEST_DATABASE_URL` أو `RESTORE_DATABASE_URL`.
- احتفظ بـ`BACKUP_ENCRYPTION_KEY` و`ENCRYPTION_KEY` في Password Manager خارج GitHub أيضًا.
- نفّذ Workflow التحقق من النسخة دوريًا؛ وجود ملف Backup وحده لا يضمن أنه قابل للاستعادة.
