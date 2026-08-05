# تقرير Backfill للصلاحيات

## ما ينفذه Migration 1070

- يضيف `ProviderStaff.role` بقيمة افتراضية `STAFF` عند غيابه.
- يضيف `can_manage_branding=False` عند غيابه.
- يحول فقط العناوين الصريحة التالية إلى OWNER:
  - `owner`, `platform_owner`, `provider_owner`, `مالك`.
- يحول العناوين الصريحة التالية إلى MANAGER:
  - `manager`, `admin`, `administrator`, `مدير`.
- يمنح OWNER صلاحية branding المخزنة، بينما جميع صلاحيات OWNER الفعلية تُحسب في resolver دون الحاجة لتغيير كل boolean.

## الحالات التي لا تُخمن

- أكثر من OWNER للمنصة نفسها.
- منصة بلا OWNER صريح.
- OWNER موقوف.
- صف موظف orphan.
- duplicate provider/user membership.
- `provider.active.*` مشوه.

يُخزن migration عدادات غير حساسة في:

```text
SystemSetting: provider_access.backfill_report
```

لم تتوفر في بيئة الفحص بيانات اعتماد قاعدة الإنتاج، لذلك لم تُقرأ بيانات المستخدمين ولم تُختلق أرقام فعلية. للحصول على التقرير الحقيقي بعد أخذ backup:

```bash
python scripts/provider_access_audit.py --json provider_access_audit.json
```

السكريبت read-only ولا يطبع Telegram IDs أو Tokens أو DATABASE_URL أو PII.
