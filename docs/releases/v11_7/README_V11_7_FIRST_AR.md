# ابدأ من هنا — CampusPass IQ V11.7 LTS Turbo

الإصدار: `11.7.0-lts-turbo-update-safe`

هذا الإصدار مبني مباشرة فوق V11.6 ويحافظ على جميع ميزات الطالب والمنصة والمالك والدفع والضمان والتقارير وRender Webhook.

## الهدف

- استجابة أسرع لتحديثات Telegram.
- عدم فقد التحديثات أثناء إعادة التشغيل أو النشر.
- قبول الإصدارات الجديدة وفق عقد توافق واضح.
- إبقاء الأزرار القديمة عاملة بواسطة Callback aliases وإصدار Schema ثابت.
- مزامنة القوائم والمزايا بين Web والـWorker من دون إعادة تشغيل.

## تشغيل Staging

1. ارفع محتويات ZIP الخاصة بـGitHub إلى مستودع جديد.
2. أنشئ PostgreSQL وRedis دائمين.
3. أنشئ Blueprint من `render.yaml`.
4. أدخل الأسرار المطلوبة ولا تضعها في المستودع.
5. راقب نجاح `python ops/render_predeploy.py`.
6. انتظر نجاح `/health/ready`.
7. شغّل `python ops/render_smoke.py` من بيئة تحمل `SMOKE_BASE_URL` و`API_ADMIN_TOKEN`.
8. اختبر زر الطالب، الوصل، مزوداً واحداً، OTP، ضماناً، وتقريراً قبل Production.

## Production

استخدم `render.production.yaml`. يحتوي على Web Service وBackground Worker منفصلين. لا تغيّر `UPDATE_MIN_COMPATIBLE_*` أو أرقام Callback/Event Schema إلا ضمن Migration وخطة Rollback موثقة.
