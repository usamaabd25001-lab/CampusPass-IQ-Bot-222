# تقرير التحقق الفعلي — V10.7 Emergency Stabilization

تاريخ الفحص: 2026-07-31 — Asia/Baghdad

## Baseline قبل التعديل

نفذت الأوامر على النسخة الأصلية المفكوكة:

```bash
python -m compileall -q app alembic tests scripts
```

النتيجة: `exit 0`.

```bash
pytest -q \
  tests/test_v10_2_callback_ui_inventory.py \
  tests/test_v10_4_commerce_referral_payments.py \
  tests/test_v10_5_final_hardening.py \
  tests/test_v10_5_final_smart_emoji_fsm_offers.py \
  tests/test_v10_6_platform_access_referral.py \
  tests/test_v10_7_ui_authorization_blockers.py
```

النتيجة الأصلية: **49 passed**.

محاولة جمع المجموعة الكاملة قبل التعديل توقفت بسبب عدم وجود `aiogram` في بيئة الفحص المحلية. محاولة تثبيت متطلبات المشروع فشلت بسبب عدم توفر الشبكة/الحزمة في المستودع المحلي؛ لم يتم إنشاء stubs أو تزوير تشغيل الاختبارات.

## نتائج ما بعد التعديل

### Compile/import syntax

```bash
python -m compileall -q app alembic tests scripts
```

النتيجة: `exit 0`؛ لا SyntaxError أو IndentationError.

### اختبارات الإصدارات الحديثة + regression السلوكية

```bash
pytest -q \
  tests/test_v10_2_callback_ui_inventory.py \
  tests/test_v10_4_commerce_referral_payments.py \
  tests/test_v10_5_final_hardening.py \
  tests/test_v10_5_final_smart_emoji_fsm_offers.py \
  tests/test_v10_6_platform_access_referral.py \
  tests/test_v10_7_ui_authorization_blockers.py \
  tests/test_v10_7_emergency_stabilization_behavior.py
```

النتيجة: **60 passed**.

التغطية السلوكية الجديدة تشمل:

- OWNER بصلاحيات effective كاملة رغم booleans القديمة.
- STAFF بصلاحياته الممنوحة فقط.
- SUPER_ADMIN بلا ProviderStaff synthetic row.
- staff paused/provider paused/stale context بأسباب منفصلة.
- منصة واحدة/عدة منصات واختيار active provider.
- cache hit بلا إعادة resolver DB load وtargeted invalidation.
- query budget: استعلامان لمنصة واحدة وثلاثة عند الحاجة لقراءة active selection لتعدد المنصات؛ cache hit = صفر.
- HTML آمن ورسالة `/start` cached.
- تحقق صورة محلي ورفض ملف غير صورة.

### اختبارات Aiogram/PostgreSQL الاختيارية

```bash
pytest -q \
  tests/test_v10_7_navigation_ui_behavior.py \
  tests/test_v10_7_postgres_transaction.py
```

النتيجة المحلية: **2 skipped**، وخرج pytest بالرمز 5 لأن كل الاختبارات في الملفين تم تخطيها:

- `aiogram` غير مثبت في بيئة الفحص المحلية، بينما Docker يثبت `aiogram==3.30.0` من `requirements.txt`.
- `asyncpg` و`TEST_DATABASE_URL` غير متوفرين محلياً.

الاختبارات موجودة وتعمل في Docker/CI عند توفر المتطلبات.

### Validators

```text
V10.5 final hardening validation passed (329 callback handlers)
V10.6 platform access/referral validation passed (329 callback handlers, 281 literal payloads)
Final UI/authorization patch validation passed callbacks=329
V10.7 emergency stabilization validation passed callbacks=333 routes=333 literal_payloads=281
```

الـvalidator الجديد يفحص:

- كل callback يبدأ بـ`await callback.answer()` مرة واحدة.
- لا duplicate exact callback filters.
- Legacy aliases مملوكة لمسار مركزي واحد.
- الحمولات الحرفية ≤64 بايت.
- Migration upgrade لا يحتوي Drop/Truncate/Delete لجداول الإنتاج.
- لا Google Vision في مسار branding.
- Reply/Inline transition وقفل idempotency.

### Alembic

```bash
alembic heads
```

النتيجة:

```text
1070_emergency_stabilization (head)
```

### المجموعة التاريخية الكاملة

```bash
pytest -q --continue-on-collection-errors
```

النتيجة المحلية الفعلية:

```text
142 passed, 3 skipped, 6 failed, 15 errors
```

تفصيل ما لم يمر:

- 15 collection errors: غياب `aiogram` محلياً.
- اختباران: غياب `aiosqlite` محلياً.
- 3 اختبارات وثائق تاريخية تطلب ملفات Phase2/4/5 غير موجودة أصلاً في الحزمة الأصلية.
- اختبار privacy تاريخي يطلب إعادة router أزيل سابقاً بطلب صريح؛ لم يُعد لأن هذا الـpatch ممنوع أن يعكس قرار الميزة السابق.

لا يرتبط أي من هذه النتائج بفشل compile أو callback أو migration الجديدة.

### Railway verifier

`python scripts/verify_v10_railway_turbo.py` لم يمكن تشغيله محلياً لأنه يستورد Aiogram وAsyncPG. أُبقي داخل Docker بعد تثبيت `requirements.txt` وأُضيف بعده `validate_v10_7_emergency_stabilization.py`. لم يُدّع نجاحه محلياً.

## الأداء والاستعلامات

- baseline القديم: cache عالمي لمعرف المستخدم فقط، دون provider context؛ refresh شامل بعد mutations.
- patch: DB هو المصدر، cache actor قصير 8 ثوانٍ، invalidation محدد بـtelegram/provider بعد commit.
- resolver miss:
  - منصة واحدة: 2 queries (user + memberships eager-loaded).
  - منصات متعددة: 3 queries (إضافة active selection fallback).
  - cache hit: 0 queries.
- لا استعلام داخل loop في عرض provider catalog/dispute recipients؛ استبدلت باستعلامات aggregate/join محدودة.

## حدود التحقق الصريحة

لم تتوفر قاعدة PostgreSQL إنتاجية أو BOT_TOKEN صالح، لذلك لم تُرسل رسائل Telegram فعلية ولم يُشغل migration على بيانات المستخدمين. وُضعت smoke tests وتعليمات audit/nشر لتشغيلها في البيئة المتصلة دون كشف أسرار.
