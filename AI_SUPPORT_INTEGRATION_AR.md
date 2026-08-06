# CampusPass IQ V11.7.4 — تكامل Gemini الآمن والدائم

## ما تم تطبيقه فعلياً

- لا ينتظر Handler تيليجرام رد Gemini؛ يحفظ السؤال ويرد فوراً ثم يحرر حالة الـFSM.
- يُحفظ كل طلب في جدول `cp_distributed_jobs` داخل PostgreSQL قبل التنفيذ.
- عامل داخلي يعمل في `RUNTIME_MODE=combined`، لذلك لا يحتاج Background Worker منفصلاً في Render Free.
- الوظائف المعلقة تُستعاد بعد إعادة تشغيل الخدمة، والـlease المنتهي يسمح بإكمال المهمة بأمان.
- يظهر للمستخدم إشعار فوري ثم حالة «يكتب…» طوال معالجة Gemini.
- السياق المرسل محدود ومملوك للمستخدم: الاسم الأول، آخر الطلبات، الاشتراكات النشطة، الطلب المحدد، الضمان، FAQ، والعروض المطابقة.
- لا تُرسل كلمات المرور أو OTP أو مفاتيح API أو بيانات البطاقة أو وصل الدفع أو بيانات مستخدم آخر.
- توجد موافقة خصوصية قبل إرسال السياق إلى Gemini.
- توجد حدود للطول، وعدد يومي، وعدد وظائف معلقة، وتزامن محدود.
- توجد مهلة، إعادة محاولات بتأخير تدريجي، Cache محدود، وCircuit Breaker عند تعطل الخدمة الخارجية.
- عند الفشل النهائي يظهر زر لإنشاء تذكرة بشرية من السؤال المحفوظ بدون إعادة كتابته.
- إجابة Gemini لا تنفذ إلغاءً أو استرجاعاً أو تعديلاً مالياً؛ الإجراءات الحساسة تبقى داخل أزرار البوت وصلاحياته.
- نظام البريد وOTP الحالي لم يُحذف أو يُستبدل، وبقي مستقلاً عن Gemini.

## متغيرات Render المطلوبة

```env
FEATURE_GEMINI=true
GEMINI_API_KEY=ضع_مفتاح_Google_AI_Studio
GEMINI_MODEL=gemini-3.6-flash
GEMINI_TIMEOUT_SECONDS=45
GEMINI_RETRY_ATTEMPTS=3
GEMINI_MAX_OUTPUT_TOKENS=700
GEMINI_MAX_QUESTION_CHARS=2000
GEMINI_MAX_CONTEXT_CHARS=6000
GEMINI_MAX_ANSWER_CHARS=3500
GEMINI_DAILY_USER_LIMIT=20
GEMINI_MAX_PENDING_PER_USER=2
GEMINI_JOB_MAX_ATTEMPTS=3
GEMINI_JOB_RETENTION_DAYS=14
GEMINI_WORKER_POLL_SECONDS=1
GEMINI_CIRCUIT_FAILURE_THRESHOLD=5
GEMINI_CIRCUIT_RESET_SECONDS=60
GEMINI_CACHE_TTL_SECONDS=300
GEMINI_CACHE_MAX_ENTRIES=200
AI_CONCURRENCY_LIMIT=3
```

ضع `GEMINI_API_KEY` في Render Environment فقط، ولا تضعه داخل GitHub.

## Render Free

استخدم `render.yaml` الموجود في جذر المشروع. يجب أن ينشئ مورداً واحداً فقط:

```text
campuspass-iq-free
RUNTIME_MODE=combined
```

لا يحتاج `REDIS_URL` ولا Worker منفصلاً. PostgreSQL/Supabase يبقى التخزين الدائم للوظائف.
