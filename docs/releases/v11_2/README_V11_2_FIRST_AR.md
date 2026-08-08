# ابدأ من هنا — V11.2

1. ارفع محتويات نسخة GitHub إلى Repository جديد أو فرع V11.
2. استخدم `render.production.yaml` للإنتاج المدفوع: Web + Worker.
3. ضع القيم نفسها لـ `BOT_TOKEN`, `DATABASE_URL`, `REDIS_URL`, `ENCRYPTION_KEY` في الخدمتين؛ لا تولد مفتاح تشفير مختلفاً للـWorker.
4. شغّل قاعدة Staging مستقلة أولاً.
5. راقب `/ping`, `/health`, Logs، وحالة migrations.
6. اختبر: قبول شروط المنصة، إضافة طريقة دفع، ساعات العمل، إنشاء عرض، رفع وصل، بريد المنصة، تفعيل إيميل الطالب، OTP، وانتهاء حساب مؤقت.
7. لا تنشر للطلاب قبل نجاح اختبار Staging الكامل.

## أوامر الفحص
```bash
python scripts/validate_v11_1_student_commerce.py
python scripts/validate_v11_2_provider_operations.py
pytest -q tests/test_v11_foundation_domain.py tests/test_v11_1_student_commerce.py tests/test_v11_2_provider_operations.py
```
