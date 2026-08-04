# رفع CampusPass IQ V11.7 إلى GitHub

1. فك ضغط `CampusPass-NewBot-V11.7-LTS-Turbo-GitHub-Web-Upload.zip`.
2. ارفع المحتويات إلى جذر Repository جديد، لا ترفع مجلد التغليف الخارجي.
3. لا ترفع `.env` ولا أي Token.
4. اربط المستودع بـRender باستخدام `render.yaml` للـStaging أولاً.
5. أدخل الأسرار من Render Dashboard.
6. تأكد من نجاح Pre-deploy وHealth Ready.
7. نفذ `ops/render_smoke.py` ثم Runbook V11.7.

نسخة Production تستخدم `render.production.yaml` بعد نجاح Staging فقط.
