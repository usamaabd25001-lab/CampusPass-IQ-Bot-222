# تشخيص الجذور — CampusPass IQ Emergency Stabilization

الإصدار المستهدف: `10.7.0-emergency-stabilization`

## منهج التشخيص

تم فك الحزمة الأصلية وتشغيل baseline قبل التعديل، ثم تتبع ترتيب الـrouters والـcallback filters واستدعاءات الخدمات والنماذج. لم يُستخدم Telebot ولم يُضف Monkey Patching. المشروع الفعلي هو Aiogram 3.30.0 مع SQLAlchemy Async.

## A. اختفاء Reply Keyboard وتضارب Inline/Reply

**الجذر الأصلي:**

- `app/bot/ui.py:194` في النسخة الأصلية كان `send_inline_menu` يعتمد على رسالة ناقلة تحمل `ReplyKeyboardRemove` ثم يحذفها أو يستبدلها. هذا السلوك غير حتمي على Telegram/iOS؛ حذف الرسالة الناقلة قد يحدث قبل أن يثبت العميل حالة الكيبورد.
- `app/bot/ui.py:238` كان `install_reply_keyboard_temporarily` يربط ReplyKeyboard برسالة مؤقتة لا بالرسالة النهائية المرئية.
- استدعاءات `start.py` و`menu.py` كانت موزعة بين إرسال وتعديل وحذف، لذلك الضغط السريع قد ينتج رسالتين أو يترك كيبورد شبحاً.

**الجذر بعد التتبع:** المشكلة ليست في Telegram API وحده، بل في كون الرسالة المالكة للكيبورد ليست الرسالة النهائية، مع عدم وجود قفل transition موحد.

## B. Back/Home وعبارة «استخدم /start»

- `app/bot/handlers/navigation.py:147` في الأصل كان Home/Back قريبين من مسار واحد، مع مسح حالة مبكر وحذف الشاشة قبل التأكد من نجاح الوجهة.
- بعض المسارات استعملت `message.from_user` من رسالة كتبها البوت؛ هذه الهوية هي هوية البوت وليست صاحب النقرة. الهوية الصحيحة هي `callback.from_user.id`.
- `provider:home` كان مملوكاً لأكثر من handler بحسب ترتيب routers، ولذلك كان handler سابق يمنع handler اللاحق من الوصول.
- حالات FSM لم تفرق بين Back، الذي يجب أن يحافظ على البيانات، وHome/Cancel، اللذين ينهيان العملية المقصودة.

## C. الصلاحيات واختفاء المنصات

- `app/services/platform_access.py:46-122` في الأصل اختزل الصلاحية إلى `set[str]` لمعرفات Telegram فقط. لم يحمل `provider_id` أو الدور أو حالة المنصة أو سبب الرفض.
- `app/bot/handlers/provider.py:133-240` و`app/services/menus.py:187` و`app/bot/permissions.py` و`app/services/authorization.py` كانت تستخدم بوابات مختلفة. النتيجة: قد يظهر زر المنصة وفق شرط، ثم يفشل أول زر وفق شرط آخر.
- OWNER كان يعتمد أحياناً على booleans تاريخية مثل `can_manage_offers=False`، ولذلك كان يُرفض رغم كونه المالك.
- `SystemSetting provider.active.<user_id>` كان يُستخدم كسياق وحيد في بعض المسارات؛ زر قديم قد يعمل على منصة خاطئة عند تعدد المنصات.
- الـcache السابق كان يتطلب refresh شامل بعد mutations، ولا يقدم سبباً دقيقاً مثل `staff_paused` أو `provider_paused` أو `stale_context`.

## D. تعقيد «متجري والعروض»

- `app/bot/handlers/provider_catalog.py:134` في الأصل جمع المخزون، الشعار، الأقسام، الخدمات، إضافة العرض، والحسابات في واجهة مزدحمة.
- زر إضافة عرض تكرر داخل تنظيم الأقسام والخدمات، ما جعل المستخدم يظن أن بناء الشجرة شرط قبل إنشاء أي عرض.
- نماذج `CatalogSection` و`CatalogServiceItem` و`OfferCatalogPlacement` سليمة؛ المشكلة في الوصول إليها لا في نموذج البيانات.

## E. شعار المنصة

- `app/services/branding.py:12` في الأصل كان مسار الحفظ المباشر لا يحقق دورة ذرية كاملة، والنسخ السابقة ربطته بخدمة خارجية/مفتاح Google Vision.
- غياب المفتاح أو فشل الشبكة كان قادراً على منع حفظ شعار صحيح.
- لم يكن الاستبدال دائماً: تحقق → معاينة → تأكيد/إلغاء → حفظ، مع إبقاء الشعار القديم حتى نجاح commit.

## F. رسالة `/start`

- النص الافتراضي كان ثابتاً في الإعدادات، وأي تعديل إداري كان سيحتاج مساراً موازياً أو query عند كل `/start`.
- يوجد بالفعل `MessageTemplate/SystemSetting` صالح لإعادة الاستخدام؛ الجذر كان غياب واجهة إدارة وcache/invalidation مخصصين.

## G. الاستقرار والأداء

- لا يوجد transition lock موحد لكل actor/chat، لذلك ضغطتان متزامنتان قد تبنيان fallback مرتين.
- بعض القوائم والتقارير احتوت N+1 أو استعلامات داخل loops.
- مسح FSM قبل render كان يحول فشل DB/Telegram مؤقت إلى فقدان جلسة.
- Healthcheck كان `/health/ready`؛ سجل Railway السابق أثبت أن انتظار DB/Telegram/runtime lease قد يجعل الخدمة تفشل healthcheck رغم أن HTTP process حي.

## خريطة callbacks المتأثرة

- Home aliases: `back_to_main`, `nav:home` → handler مركزي واحد في `navigation.py`.
- Provider aliases: `back_to_platform`, `provider:home` → handler مركزي واحد في `navigation.py`.
- Provider canonical dashboard: `provider:dashboard` في `provider.py`.
- Provider selection: `provider:choose`, `provider:select:<provider_id>` مع provider context صريح.
- Store: `provider:catalog`, `provider:offers`, `p:cs`, وlegacy callbacks الحالية محفوظة.
- Branding: `provider:branding` وadmin branding callbacks مع preview/confirm/cancel.

فحص AST النهائي وجد **333 callback routes فريدة** دون duplicate exact filters.
