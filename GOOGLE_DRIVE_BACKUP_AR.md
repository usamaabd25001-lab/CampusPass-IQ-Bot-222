# Google Drive: نسخة احتياطية، وليس قاعدة بيانات

Google Drive يخزن ملفات ومجلدات. لا يوفر معاملات SQL، أقفال صفوف، فهارس PostgreSQL، أو تحديثاً متزامناً آمناً لطلبات ومحافظ متعددة؛ لذلك لا يُستعمل كقاعدة البوت الحية. هذه النسخة تستعمله فقط لحفظ dump يومي **مشفر AES-256 بواسطة GPG**.

## الربط مرة واحدة

1. أنشئ Google Cloud Project وفعّل Google Drive API.
2. أنشئ OAuth Client من نوع Desktop app ونزّل ملف JSON إلى جهازك.
3. محلياً ثبّت أداة الربط:

```bash
pip install -r requirements-backup.txt
python scripts/google_drive_oauth_setup.py /path/to/client_secret.json
```

4. سجّل الدخول بحساب Google الذي تريد حفظ النسخ فيه.
5. انسخ القيم الثلاث المطبوعة إلى GitHub Secrets:

```text
GOOGLE_DRIVE_CLIENT_ID
GOOGLE_DRIVE_CLIENT_SECRET
GOOGLE_DRIVE_REFRESH_TOKEN
```

الأداة تطلب نطاق `drive.file` فقط، ولذلك تصل إلى ملفات ومجلدات النسخ التي أنشأتها هي، لا إلى جميع ملفاتك.

## GitHub Secrets المطلوبة

```text
BACKUP_DATABASE_URL       رابط PostgreSQL الخارجي
BACKUP_ENCRYPTION_KEY     كلمة طويلة مستقلة لتشفير النسخ
GOOGLE_DRIVE_CLIENT_ID
GOOGLE_DRIVE_CLIENT_SECRET
GOOGLE_DRIVE_REFRESH_TOKEN
```

يوجد Workflow جاهز في:

```text
.github/workflows/external-db-backup.yml
```

يعمل يومياً الساعة 03:00 بتوقيت بغداد، ويمكن تشغيله يدوياً من Actions. ينشئ مجلداً باسم `CampusPass IQ Backups` تلقائياً إن لم تحدد `GOOGLE_DRIVE_FOLDER_ID`.

## اختبار الاستعادة بدون لمس أي قاعدة

```bash
export RESTORE_MODE=verify
export RESTORE_ASSET_NAME='اسم ملف .tar.gz.gpg'
python ops/google_drive_restore.py
```

## الاستعادة الفعلية

استعمل قاعدة PostgreSQL جديدة فارغة أولاً:

```bash
export RESTORE_MODE=restore
export RESTORE_DATABASE_URL='postgresql://...'
export RESTORE_CONFIRMATION='RESTORE_TO_EMPTY_DATABASE'
python ops/google_drive_restore.py
```

لا تختبر الاستعادة فوق قاعدة البوت العاملة.
