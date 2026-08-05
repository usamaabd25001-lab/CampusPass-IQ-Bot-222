# خطة الـPatch الآمن

## مبادئ التنفيذ

- تغييرات مركزية محدودة، دون إعادة بناء المشروع.
- لا حذف لجداول أو بيانات أو callbacks قديمة.
- Legacy aliases محفوظة.
- DB مصدر الحقيقة؛ cache قصير ومحدد مع targeted invalidation.
- Back يحافظ على FSM data، بينما Home/Cancel يمسحان بعد نجاح render فقط.
- لا اتصال خارجي في رفع الشعار أو `/start` أو بوابات الصلاحية.

## الملفات والمحاور

1. **التنقل والواجهة**
   - `app/bot/ui.py`: transition locks، idempotency، render-before-delete، ReplyKeyboard على الرسالة النهائية.
   - `app/bot/handlers/navigation.py`: Navigation Coordinator، aliases، self-healing user، Back map.
   - `app/bot/handlers/start.py`, `menu.py`, admin handlers: استعمال المصيّرات المركزية.

2. **Provider Access Resolver**
   - `app/services/platform_access.py`: typed context واحد للأدوار والصلاحيات والحالة والأسباب.
   - `app/services/menus.py`, `authorization.py`, `payments.py`, `app/bot/permissions.py`, provider handlers: توجيه القرار إلى resolver نفسه.
   - targeted invalidation في middleware وبعد mutations.

3. **قاعدة البيانات**
   - `app/db/models.py`: `ProviderStaff.role` و`can_manage_branding`.
   - `alembic/versions/1070_emergency_stabilization.py`: migration additive/reversible.
   - `app/db/migrations.py`: migration داخلية مكافئة للبيئات التي تعتمد runner الداخلي.
   - `scripts/provider_access_audit.py`: تدقيق read-only بلا معرفات أو بيانات شخصية.

4. **المتجر والشعار**
   - `provider_catalog.py`: واجهة 3 مسارات، إنشاء قسم/خدمة داخل إضافة العرض، نقل الشعار للوحة المنصة.
   - `branding.py`: تحقق محلي محدود وatomic confirmation.
   - `image_moderation.py`, config وRailway vars: إزالة الاعتماد التشغيلي على Google Vision.

5. **رسالة `/start`**
   - `templates.py`: TTL cache + invalidation + Telegram HTML validation.
   - `admin/customization.py`, keyboards/states: عرض/تعديل/معاينة/تأكيد/إلغاء/استعادة الافتراضي.

6. **الاختبارات والبناء**
   - Regression tests سلوكية للصلاحيات والcache وHTML والصورة والتنقل.
   - validator جديد ضمن Docker.
   - تحديث الاختبارات القديمة التي كانت تفرض workarounds محذوفة عمداً.

## سبب الأمان

- لا يوجد `DROP/TRUNCATE` في `upgrade`.
- Backfill يغير فقط titles الصريحة `owner/manager`؛ الحالات الملتبسة تُعدّ وتُبلّغ ولا تُخمن.
- الـOWNER يحصل على الصلاحيات effective حسابياً، لذلك لا يلزم تغيير كل boolean تاريخي.
- cache لا يستبدل DB، ومدته 8 ثوانٍ مع invalidation فوري بعد commit.
- فشل render لا يحذف الشاشة الحالية ولا يمسح FSM.
