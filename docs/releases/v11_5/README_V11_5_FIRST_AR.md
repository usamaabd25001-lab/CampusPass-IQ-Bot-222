# ابدأ من هنا — CampusPass IQ V11.5

## الرفع إلى GitHub
1. فك ملف `CampusPass-NewBot-V11.5-Reports-Branding-Health-GitHub-Web-Upload.zip`.
2. ارفع محتوياته إلى Repository جديد أو إلى فرع V11.5.
3. لا ترفع `.env`.
4. اربط المستودع بـRender باستخدام `render.production.yaml`.

## خدمات Render
- `campuspass-v11-5-web`: البوت وFastAPI وWeb Apps والتقارير الآمنة.
- `campuspass-v11-5-worker`: المهام الخلفية، التقارير، OTP، SLA، والإشعارات.

## Variables الأساسية
`BOT_TOKEN`, `ADMIN_IDS`, `DATABASE_URL`, `REDIS_URL`, `ENCRYPTION_KEY`, `PUBLIC_BASE_URL`, `REPORT_SECRET_KEY`.

## قبل Production
- نفذ Alembic حتى `1150_reports_branding_health`.
- اختبر تقرير Free وPlus وPro.
- اختبر استعادة نسخة UI Builder.
- افحص Redis وTelegram latency من لوحة صحة النظام.
- لا تطلق البوت تجارياً قبل نجاح Staging.
