# رفع CampusPass IQ V11.7.1 إلى GitHub

1. فك ضغط `CampusPass-NewBot-V11.7.1-All-Features-GitHub-Web-Upload.zip`.
2. ارفع المحتويات إلى جذر Repository، ولا ترفع ZIP نفسه داخل GitHub.
3. لا ترفع `.env` أو أي Token أو مفاتيح S3/Google/بوابة الدفع.
4. اربط المستودع بـRender باستخدام `render.production.yaml`.
5. الأسرار الأساسية تكفي لإقلاع البوت؛ الميزات الخارجية المفعلة تبقى Pending حتى تضيف مفاتيحها.
6. راجع `docs/releases/v11_7_1/ALL_FEATURES_VARIABLES_AR.md`.
7. تأكد من نجاح Pre-deploy و`/health/ready`.

فك الضغط ضروري لأن Render يحتاج `Dockerfile` و`app/` كملفات فعلية في جذر المستودع.
