# تقرير فحص CampusPass IQ 4.1.0

تاريخ الفحص: 2026-07-19

## النتائج

- `pytest -q`: **31 passed**.
- `ruff check app tests scripts`: ناجح بدون أخطاء.
- `ruff format --check app tests scripts`: ناجح بعد تنسيق الملفات.
- `python -m compileall -q app tests scripts`: ناجح.
- `python scripts/verify_project.py`: ناجح.
- `python scripts/verify_runtime_files.py`: ناجح.
- `bandit -q -r app scripts -x tests`: ناجح بدون نتائج أمنية معروضة.

## حدود الفحص

- لم يتم الاتصال ببوابة Mastercard حقيقية؛ الـAdapter عام ويجب مطابقته مع وثائق البنك المتعاقد معه قبل التفعيل.
- لم يتم تشغيل PostgreSQL أو Redis حقيقيين داخل بيئة الفحص؛ تمت تغطية المسارات المنطقية والاختبارات باستخدام SQLite وFake Bot، مع اعتماد SQL خاص بـPostgreSQL فقط لقفل Scheduler.
- تعذر إكمال `pip-audit` لأن بيئة الفحص لم تستطع الوصول إلى قاعدة بيانات ثغرات PyPI/DNS. هذا لا يعني وجود ثغرة أو عدم وجودها؛ أعد تشغيله في CI متصل بالإنترنت.
- لم يتم تشغيل Bot Token حقيقي أو إرسال معاملات مالية فعلية.

## أمر الفحص المقترح في CI

```bash
pip install -r requirements.txt ruff bandit pip-audit
ruff format --check app tests scripts
ruff check app tests scripts
python -m compileall -q app tests scripts
python scripts/verify_project.py
python scripts/verify_runtime_files.py
pytest -q
bandit -q -r app scripts -x tests
pip-audit -r requirements.txt
```
