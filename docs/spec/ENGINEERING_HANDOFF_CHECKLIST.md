# Engineering Handoff Checklist

## كل Pull Request يجب أن يحتوي
- Requirement IDs.
- الملفات المعدلة.
- Database migrations.
- Tests.
- Security impact.
- Performance impact.
- Rollback steps.

## كل ميزة يجب أن تربط بـ
- Handler.
- Service.
- Model/Table.
- Permissions.
- FSM.
- Background jobs.
- Audit events.
- Acceptance tests.

## لا تعتبر الميزة مكتملة قبل
- نجاح الاختبارات.
- تحديث Requirements Register.
- تحديث Decision Log.
- تحديث Changelog.
- مراجعة الصلاحيات والتكرار المالي.
