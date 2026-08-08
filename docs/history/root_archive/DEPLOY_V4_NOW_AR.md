# رفع V4.1 إلى GitHub وRailway

سبب عدم ظهور الإضافات: النشر الجديد في Railway فشل، ولذلك بقي البوت يعمل على آخر إصدار ناجح قديم.

## طريقة الرفع الصحيحة

1. خذ نسخة احتياطية من PostgreSQL في Railway.
2. لا تحذف خدمة PostgreSQL، ولا تغيّر DATABASE_URL أو ENCRYPTION_KEY.
3. فك ملف `campuspass-v4.1.0-production-ready.zip`.
4. ارفع **كل الملفات التي ظهرت بعد فك الضغط مباشرة** إلى جذر مستودع GitHub الحالي، مع استبدال الملفات القديمة.
5. يجب أن ترى في الصفحة الرئيسية للمستودع مباشرة:
   - `Dockerfile`
   - `Procfile`
   - `VERSION.txt`
   - `app/`
   - `requirements.txt`
6. لا تضع الملفات داخل مجلد إضافي باسم الملف أو باسم V4.
7. اعمل Commit وانتظر Railway.
8. يجب أن تتحول حالة Deployment إلى `SUCCESS` أو `ACTIVE`، وليس `FAILED`.
9. إذا فشل، افتح `View logs` وأرسل أول سطر أحمر كامل وآخر 30 سطرًا من Build Logs.
10. بعد نجاح النشر، أرسل `/start` للبوت. يجب أن يظهر زر `📅 اشتراكاتي`.

## تحقق سريع

محتوى `VERSION.txt` يجب أن يكون:

```text
4.1.0
```

والمسار الصحيح هو:

```text
app/bot/handlers/subscriptions.py
```

وليس داخل مجلد فرعي مثل:

```text
campuspass-v4/app/bot/handlers/subscriptions.py
```


لإعداد الأسرار والدفع وRedis راجع `DEPLOY_V4_1_AR.md`.
