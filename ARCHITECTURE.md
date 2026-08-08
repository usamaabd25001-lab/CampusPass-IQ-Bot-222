# معمارية CampusPass IQ Enterprise V4

## المبدأ

PostgreSQL هو مصدر الحقيقة. Telegram واجهة فقط. لا يعتمد تنفيذ الطلب أو المال أو المخزون على نص زر أو رسالة عابرة.

## الطبقات

```text
app/bot              واجهة Telegram وFSM والكيبوردات
app/services         قواعد العمل والحجز والدفع والاشتراكات
app/db               النماذج، Seed، وسجل migrations
app/integrations     البريد، Gemini، وبوابات الدفع
app/tasks            Outbox، البريد، التنبيهات والتقارير
app/api              Health Check، التقارير، وWebhooks
app/plugins          إضافات منشورة من GitHub فقط
```

## محرك الكتالوج

```text
Provider
└── CatalogSection
    └── CatalogServiceItem
        └── OfferCatalogPlacement
            └── Offer
```

هوية العرض ثابتة حتى لو تغيّر الاسم أو ترتيب الأزرار. كل منصة ترى وتدير بياناتها فقط.

## محرك الصلاحية

`OfferValidityPolicy` يحدد:

- `days_from_activation`
- `months_from_activation`
- `fixed_offer_end`
- `inventory_end`
- `manual`

ويحدد وقت البداية:

- بعد قبول الدفع.
- عند التسليم.
- بعد تأكيد المستخدم نجاح التفعيل.

`StudentSubscription` يحتفظ بنسخة تاريخية من اسم المنصة والخدمة والعرض وتواريخ الطلب والدفع والتسليم والتفعيل والانتهاء. `ReceiptSnapshot` يمنع تغيّر الوصل القديم بعد تعديل العرض.

## الطلب والحجز

1. يتحقق `OrderService` من المنصة والعرض والحدود والمدة.
2. يحجز موردًا باستخدام `SELECT ... FOR UPDATE SKIP LOCKED` عند PostgreSQL.
3. ينشئ `PurchaseReservation` بمهلة زمنية.
4. إذا انتهت المهلة قبل الدفع، يُحرر المورد.
5. بعد قبول الدفع، يثبت الحجز.

## التسليم الآمن

`DeliveryJob` يمثل Outbox مستقلًا:

```text
pending → processing → sent
                    ↘ failed
```

`idempotency_key` فريد لكل طلب، لذلك الضغط المتكرر على قبول الدفع لا ينشئ مهمة ثانية ولا يختار حسابًا آخر. أسرار صندوق البريد وOAuth وIMAP لا تدخل نص التسليم للطالب.

## رموز البريد

المطابقة تعتمد على:

- الطلب والاشتراك المحجوز.
- وقت ضغط طلب الرمز.
- المرسل المتوقع.
- عنوان الرسالة أو الكلمات المطلوبة.
- Regex الرمز.
- Fingerprint للرسالة والرمز.
- حد المحاولات.

الرسالة أو الرمز المستخدم لا يُسلّم مرة ثانية.

## Workflow Engine

كل عرض لديه `OfferWorkflow` مرقم، وكل طلب لديه `OrderWorkflowState`. الانتقالات غير المسموحة تُرفض على مستوى الخدمة، وليس الواجهة فقط. تحديث تعريف Workflow يحدث بإصدار جديد دون حذف تاريخ الطلب.

## واجهة قابلة للإدارة

الأزرار محفوظة بمفتاح ثابت وعرض قابل للتعديل:

```text
key + action = الهوية والوظيفة الثابتة
text + style + surface + row + position = العرض القابل للتعديل
```

الأسماء القديمة تحفظ كـAliases حتى تعمل الكيبوردات القديمة.

## قوالب الرسائل والوحدات

- `MessageTemplate`: نصوص قابلة للتعديل مع متغيرات محددة.
- `ModuleRecord`: حالة كل وحدة وإصدارها وأهميتها.
- `HealthService`: قاعدة البيانات، مهام التسليم، الإيميلات، migrations والوحدات.

## التحديثات

`metadata.create_all` ينشئ الجداول الجديدة، ثم `run_migrations` ينفذ Backfill مسجلًا في `cp_schema_migrations`. تحديث V4 من V3.2 لا يغير أعمدة الجداول القديمة؛ يضيف جداول مستقلة ويربط البيانات القديمة بها.

التغييرات اليومية تتم من لوحة الإدارة. التغيير المنطقي الجديد يصل كـPatch يحتوي الملفات المعدلة وManifest وMigration إن لزم.


## طبقة الاعتمادية V4.1

- `cp_payment_webhook_events`: سجل أحداث الدفع ومفتاح منع التكرار.
- `cp_report_access`: بصمة رابط التقرير، الإلغاء، وعدد مرات الفتح.
- Redis: تخزين FSM وRate Limit فقط؛ PostgreSQL يبقى مصدر الحقيقة.
- PostgreSQL transaction advisory lock: يضمن أن دورة Scheduler تنفذها نسخة واحدة.
- Public health probes لا تكتب إلى قاعدة البيانات؛ الفحص التفصيلي محمي.
