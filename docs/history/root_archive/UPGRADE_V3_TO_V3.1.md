# التحديث من V3 إلى V3.1

1. خذ نسخة Backup من PostgreSQL في Railway.
2. ارفع ملفات V3.1 فوق ملفات المستودع الحالي.
3. أضف المتغيرات الجديدة من `RAILWAY_VARIABLES.txt`، ولا تغيّر BOT_TOKEN أو DATABASE_URL.
4. نفذ Redeploy.
5. راقب Deploy Logs حتى يظهر `CampusPass IQ Bot started in polling mode`.
6. افتح لوحة الإدارة ثم باقات المنصات. ستنشأ الباقات الافتراضية تلقائيًا.
7. المنصات القديمة تحصل على الباقة المجانية تلقائيًا عند أول طلب أو عند فتح صفحة اشتراكها.

لا تحذف خدمة Postgres، ولا ترفع ملف قاعدة بيانات SQLite إلى GitHub.
