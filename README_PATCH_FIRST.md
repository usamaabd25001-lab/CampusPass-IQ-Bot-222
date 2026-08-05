# ابدأ من هنا — Patch V3.2.0 إلى V4.0.0

1. خذ Backup من PostgreSQL في Railway.
2. لا تغيّر `ENCRYPTION_KEY` ولا تحذف `DATABASE_URL`.
3. انسخ محتويات هذا المجلد إلى جذر مستودع GitHub الحالي.
4. وافق على استبدال الملفات.
5. أضف Variables الجديدة من `RAILWAY_VARIABLES.txt`.
6. اعمل Commit وانتظر نجاح `/health`.
7. اقرأ `V4_UPGRADE_GUIDE_AR.md` و`V4_TEST_REPORT_AR.md`.

هذا Patch يحتوي الملفات الجديدة والمعدلة فقط. لا يحتوي قاعدة بيانات أو أسرارًا.
