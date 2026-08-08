## 11.8.2-provider-commerce-webapp-release-hygiene — 2026-08-08

- Fixed release metadata drift and decoupled code-only patch releases from database schema migrations.
- Added release-hygiene, imported-symbol, Render Free profile, and duplicate-env-key build gates.
- Corrected the Render Blueprint Frankfurt region identifier and unified conservative free-tier limits.
- Quarantined historical tests/validators from the runtime image while preserving them in the source archive.
- Added a deterministic deploy-bundle builder with SHA-256 manifest.


## 11.7.4-durable-ai-support — 2026-08-06

- Added a PostgreSQL-backed durable queue for Gemini support requests in Render Free combined mode.
- Added strict system instructions, minimum-context injection, explicit AI consent, and secret redaction.
- Added bounded concurrency, timeouts, retries, cache, circuit breaker, pending/daily limits, and retention cleanup.
- Added continuous Telegram typing feedback and automatic human-ticket escalation after final failure.
- Preserved the existing email/OTP, payment, provider, student, owner, warranty, reporting, and navigation flows.
- Added offline mocked Gemini validation and strengthened Render build verification.


## 11.7.1-all-features-ready

- Enabled Gemini, card payments, provider withdrawals, encrypted backups, image moderation and external evidence storage through safe readiness gates.
- Optional external credentials no longer block boot; operational routes remain closed until fully configured.
- Added Google Vision SafeSearch upgrade with local validation fallback.
- Added data migration 1171 and health visibility for requested vs configured state.
# 11.4.0-owner-commerce

- Added B2B platform billing, invoice proofs, automatic suspension and restoration.
- Added the central owner inbox and batched targeted advertising.
- Added owner/provider coupon campaigns with per-user assignments.
- Added hybrid bundles with child orders, balanced ledger allocation and pre-payment inventory holds.
- Added funded reward tasks with Telegram membership verification.
- Added V11.4 Render web/worker blueprint and cumulative validators.

## 11.3.0-friends-warranty — 2026-08-04
- Friends-only package feature gate with custom member count.
- Exclusive inventory reservation, per-member orders and full bot fee.
- Transactional escrow, 24-hour refund and synchronized delivery jobs.
- Warranty claims from subscriptions with screenshot classification.
- Provider actions for OTP, replacement account and text response.
- Student confirmation required before warranty closure and replacement binding.
- PostgreSQL constraints, active-claim unique guard, Redis 8.1 retry/backoff.


## 11.2.0-provider-operations — 2026-08-04
- Provider-specific onboarding terms and permissions.
- Unified provider inbox for payment, activation, OTP and logout evidence.
- Canonical Iraqi payment methods and receipt guide.
- Offer fulfillment profile, 60-second OTP lease and temporary-account enforcement.
- Render web/worker production blueprint.

## 11.1.0-student-commerce

- Add authenticated Telegram Student Profile Web App with RTL Arabic UI.
- Gate marketplace/account flows on complete profile data.
- Add provider cards, working hours, multi-level favorites and dynamic offer labels.
- Persist immutable checkout breakdowns and net wallet-fee deductions.
- Enforce the approved wallet policy: complete bot fee only, never partial service-price coverage.
- Add receipt SHA-256 duplicate protection and payment amount confirmations.
- Require provider payment-review permission before confirm/reject flows.
- Add Alembic migration `1110_student_commerce` and V11.1 validator/tests.
- Target Telegram Bot API 10.2 and aiogram 3.30.0.

## 10.7.0-emergency-stabilization

- Deterministic Reply/Inline navigation and transition locks.
- Typed Provider Access Resolver with OWNER/SUPER_ADMIN effective permissions.
- Multi-provider context, targeted cache invalidation, and precise failure reasons.
- Local atomic branding flow without Google Vision.
- Admin-editable cached `/start` template.
- Additive migration `1070_emergency_stabilization`.

# Changelog

## 10.6.0-platform-access-referral

- Remove privacy/delete-data buttons and public handlers while retaining database records.
- Add strict platform/admin menu permissions and a one-time platform TOS gate.
- Normalize Telegram IDs through the central `is_platform_authorized` query.
- Replace referral wallet cash with a targeted one-use fee-waiver coupon every three successful invites.
- Switch platform-logo persistence to direct Telegram `file_id` with no external image API.
- Harden Reply/Inline keyboard transitions and centralized FSM navigation cleanup.

## 10.2.0-callback-ui-inventory

- Acknowledge every Aiogram callback before any database, permission, or rendering work.
- Add a PostgreSQL-backed renewable singleton lease to prevent overlapping Telegram polling replicas.
- Serialize edits per Telegram message and update callback menus in place with one controlled fallback.
- Minify dynamic callback payloads to numeric IDs/tokens and retain legacy callback compatibility.
- Synchronize provider, offer, catalog, payment, plan, subscription, feature, and limit states immediately.
- Rebuild owner/provider dashboards as compact inline grids while preserving reply keyboards for navigation.
- Merge provider inventory into the store/offer tree with active, expired, renew, and stop actions.
- Require provider branding before offer creation; persist Telegram file_id and report-ready logo data.

## 6.9.0-operations-reliability-phase5

- Persistent deployment release registry and runtime component readiness.
- Split runtime modes for combined, bot-only, and worker-only operation.
- Database-backed scheduled-run leases and restart-safe daily tasks.
- Encrypted, verified PostgreSQL backups to S3-compatible storage.
- Safe external restore utility and optional pre-deploy backup gate.
- Runtime incident registry, metrics endpoint, and optional Sentry integration.
- Multi-key decryption and gradual encryption-key rotation.
- Staging bot-token isolation and Alembic V6.9 baseline.

## 6.8.0-user-experience-phase4

- Progressive onboarding and browse-before-registration.
- Explicit purchase confirmation before order/resource reservation.
- Separate delivery acknowledgement and activation success.
- Pagination and public-ID search for orders, subscriptions, tickets, messages, and disputes.
- Central Arabic status presentation and visible delivery estimates.

## 6.1.0-external-db

- فصل PostgreSQL عن Railway وإلزام المضيف الخارجي في الإنتاج.
- إضافة SSL/pooling/timeouts/retry startup للاتصال الخارجي.
- إضافة أدوات نقل وفحص واستعادة PostgreSQL.
- إضافة نسخ يومية مشفرة إلى Google Drive عبر GitHub Actions.
- إضافة ملف Variables شامل ودليل عربي للنقل الآمن.
- اجتاز المشروع 57 اختباراً محلياً.

# 5.0.0 - Radical owner and platform update

- Updated Telegram framework to aiogram 3.30.0.
- Added safe FSM navigation and persistent rescue keyboard.
- Added owner Super Admin mode across provider panels.
- Added full custom menu content and Reply/Inline/Both/Hidden surfaces.
- Added owner-controlled system, feature, report and plan pricing with IQD confirmation.
- Added provider-controlled offer prices with change logs.
- Added six activation modes and mandatory multimedia activation guides.
- Added Gmail/Outlook/Yahoo IMAP presets and connection tests.
- Added completed-order ratings and provider aggregate stars/count.
- Added timed pinned announcements and owner-only bot issue reports.
- Added seven independent A4 HTML report types with Standard, Plus and Pro tiers.
- Added safe catalog rename/hide/delete/archive operations.

# 4.3.0 - GitHub operations and resilience

- Added daily encrypted PostgreSQL backups executed by GitHub Actions.
- Added rolling encrypted backup storage in a private GitHub Release.
- Added manual backup verification and restore-to-staging workflow.
- Added destructive-safety guards for restore and stress-test databases.
- Added a PostgreSQL concurrency stress harness for simultaneous inventory reservations.
- Added GitHub Secrets and rotating-server deployment checklists.
- Extended CI checks to cover `ops/` and `loadtests/`.

# 4.2.0 - Branding, exports, and document polish

- Added CampusPass IQ branded export styling aligned to the approved logo colors.
- Embedded the official horizontal CampusPass IQ logo in exported report files by default.
- Added a reserved provider/platform logo slot in exported documents, with graceful placeholder handling.
- Added downloadable HTML and CSV report export endpoints and direct buttons inside the bot UI.
- Added packaged branding asset support through `EXPORT_LOGO_PATH` and color variables.
- Expanded test coverage to 33 passing tests.

# 4.1.0 - Production hardening

- Added idempotent payment webhook processing and checkout registration.
- Added strict amount, currency, order, reference, and signature verification.
- Added Redis FSM storage and distributed rate limiting with safe fallback.
- Added PostgreSQL scheduler advisory locking.
- Added protected health endpoints and revocable, limited report access.
- Added verified post-completion ratings and comments.
- Added production secret validation and deployment documentation.
- Expanded the test suite to 31 passing tests.

# 4.0.1 - Emergency repository repair

- Added build-time verification for missing local Python modules.
- Included all V4 runtime files needed to repair a partial GitHub upload.
- Build now stops before deployment when the repository file set is incomplete.

# سجل الإصدارات

## 4.0.0 — إعادة بناء منصة المتجر والاشتراكات

### الكتالوج والمنصات

- إضافة بنية منصة ← قسم ← خدمة ← عرض.
- إضافة إدارة الأقسام والخدمات والعروض من لوحة المنصة.
- إضافة إدارة المخزون وطرق الدفع وتذاكر الدعم للمنصة.
- فصل هوية الكتالوج عن أسماء الأزرار والنصوص.

### اشتراكات الطلاب

- إضافة صلاحية بالأيام والأشهر والتاريخ الثابت وتاريخ المورد والتاريخ اليدوي.
- إضافة لحظة بداية قابلة للاختيار.
- إضافة `اشتراكاتي` والوصل التاريخي والتجديد والتنبيهات.
- إضافة ضمان التفعيل ومهلة الاعتراض.

### الطلب والدفع والتسليم

- إضافة حجز مؤقت للمخزون قبل الدفع.
- إضافة بصمة تمنع تكرار الحساب أو الكود.
- إضافة Delivery Outbox ومفتاح Idempotency وإعادة المحاولة.
- حماية وسيلة الدفع ومرجع العملية.
- إضافة مطابقة آمنة لرموز البريد ومنع إعادة الاستخدام.

### النظام

- إضافة Workflow Engine لكل عرض وطلب.
- إضافة Message Templates وModule Registry وHealth Service.
- إضافة رسالة معالجة تلقائية ورقم متابعة للأخطاء.
- إصلاح النقر السريع حتى لا يبقى Spinner Telegram عالقًا.
- إصلاح حفظ Seed وMigrations عند بدء التشغيل بإضافة Commit صريح.
- إصلاح فروقات الوقت بين SQLite وPostgreSQL واعتماد UTC داخليًا وAsia/Baghdad للعرض.
- إضافة ترقية غير مدمرة من V3.2 واختبارات رحلة شراء كاملة.

## 3.2.0 — مدير واجهة الأزرار والتحديثات الجزئية

- إدارة اسم ولون ومكان وترتيب وتفعيل الأزرار.
- Aliases للأسماء القديمة.
- سجل Migrations وإصدار التطبيق.

## 3.1.1

- إصلاح رفض أسماء صحيحة مثل «اسامة» و«أسماء».

## 5.0.1 — Railway healthcheck and domainless reports hotfix

- Start the FastAPI liveness server before database migrations, Redis, and Telegram API calls.
- Railway now checks `/health/live` with a 300-second deployment window.
- `PUBLIC_BASE_URL` is no longer required for HTML/CSV reports.
- Reports are delivered directly inside Telegram when no public domain exists.
- Auto-detect `RAILWAY_PUBLIC_DOMAIN` when Railway provides one.
- Keep `PUBLIC_BASE_URL` mandatory only for external card-payment callbacks.
- Prevent configuration validation traces from printing secret input values.
- Make `REPORT_SECRET_KEY` and `API_ADMIN_TOKEN` optional with secure fallback/locked endpoints.

## 5.0.2
- إضافة إدارة عملية للإعلانات المثبتة من لوحة المالك.
- إضافة مدد سريعة وإيقاف يدوي وفك تثبيت تلقائي.
- إضافة إحصاءات نجاح الإرسال والتثبيت.
- تحسين إظهار فشل التثبيت بدل إخفائه بصمت.

## 6.0.0-foundation
- Added atomic student/provider wallets and overpayment carry-forward.
- Added provider commission settlements with 24-hour due workflow and proof review states.
- Added capacity-aware resource pools and seat reservations.
- Added temporary access sessions with deletion acknowledgement.
- Added scoped feature overrides and unified offer search.
- Added Arabic IQD amount rendering.


# سجل تغييرات V11.5 — Reports, Branding & Health

## الأساس
- بُني الإصدار فوق V11.4 Owner Commerce من دون حذف ميزات الطالب أو المنصة أو الأصدقاء أو الضمان أو التجارة الإدارية.
- الإصدار: `11.5.0-reports-branding-health`.

## هوية CampusPass IQ
- اعتماد الشعار الأفقي كترويسة رسمية.
- اعتماد الشعار المربع كأيقونة وعلامة مائية بنسبة 10%.
- الألوان الأساسية: `#003279` و`#14A5A2` واللون الداكن `#082F63`.
- استخراج ألوان شعار المنصة بواسطة Pillow مع فحص التباين، من دون ColorThief قديم.

## التقارير
- Free: رسالة Telegram يومية أو أسبوعية بالمؤشرات التشغيلية فقط.
- Plus: ملف HTML منسق بهوية CampusPass IQ والمنصة، من دون CSV أو Excel.
- Pro: PDF رسمي A4/PDF-A مع QR ورقم مرجعي وWeb Dashboard آمن.
- أفضل ثلاثة عروض، متوسط تأكيد الدفع، نمو الطلاب، التحليل الأكاديمي والجغرافي.
- حفظ Metadata وبصمة SHA-256 لكل Artifact مولد.
- تجميع مؤشرات يومية مستقلة عن مستوى التقرير لضمان دقة Plus وPro.

## UI Builder
- حفظ نسخة كاملة من ترتيب وأسماء وألوان وحالة الأزرار والمحتوى والإعدادات.
- سجل نسخ مرقم مع SHA-256.
- استعادة نسخة سابقة مع إنشاء نسخة أمان تلقائية قبل الاستعادة.

## صحة النظام
- CPU وRAM والقرص والـThreads والـOpen Files وUptime.
- Ping حقيقي لـRedis وTelegram API بمهلة قصيرة.
- حفظ تاريخ Health Snapshots في PostgreSQL.
- عرض المؤشرات الجديدة داخل لوحة المالك.

## Render
- Web Service وBackground Worker بأسماء V11.5.
- إضافة مكتبات Pango/Harfbuzz/Noto المطلوبة لإنشاء PDF عربي.
- تثبيت `weasyprint==69.0` و`psutil==7.2.2`.

# سجل تغييرات V11.6 — Render, E2E & Production Hardening

## Webhook آمن ودائم
- الانتقال إلى وضع Webhook في Render مع دعم Polling كمسار تطوير اختياري فقط.
- التحقق الثابت زمنياً من `X-Telegram-Bot-Api-Secret-Token`.
- حد أعلى لحجم جسم Webhook والتحقق من JSON و`update_id`.
- حفظ التحديث في PostgreSQL قبل إرجاع HTTP 200.
- منع تكرار التحديثات بواسطة `update_id` وبصمة SHA-256.
- إعادة معالجة آمنة بمهلة Lease ومحاولات محدودة وBackoff وحالة Dead Letter.

## بوابة النشر والجاهزية
- إضافة `DeploymentGateService` لفحص PostgreSQL وRedis وTelegram والمخطط والإصدار والـWorker والـWebhook.
- إضافة `cp_deployment_gate_runs` لسجل نتائج البوابات.
- منع إعلان `/health/ready` إذا كان أحد المكونات الحرجة غير جاهز.
- إضافة `/health/deep` محمي وواجهة قراءة آخر بوابة نشر.

## Render
- إضافة `preDeployCommand` للمهاجرات والفحص قبل التشغيل.
- استخدام `/health/ready` بدلاً من فحص حياة سطحي فقط.
- تفعيل النشر بعد نجاح Checks.
- Blueprint Staging بخدمة Combined وBlueprint Production بخدمتي Web وWorker.

## الاختبارات والتشغيل
- إضافة `ops/render_predeploy.py`.
- إضافة `ops/render_smoke.py` لفحص Ping وLive وReady وDeep ورفض Webhook مزور.
- إضافة Migration `1160_render_e2e_hardening`.
- توسيع سجل المتطلبات إلى 91 مطلباً بإضافة OPS-001..OPS-006.
- تحديث Validators السابقة لتعمل كحراس توافق تراكمي بدلاً من رفض الإصدارات الأحدث.

# سجل تغييرات V11.7 — LTS Turbo & Update Safety

- حفظ جميع ميزات V11.6 وما قبلها.
- Wakeup فوري لمعالج تحديثات Telegram بعد حفظ Webhook.
- Claim بدُفعات مع `SKIP LOCKED` وتقليل رحلات قاعدة البيانات.
- Graceful drain وإعادة تسليم Telegram أثناء النشر.
- `orjson`, `uvloop`, `httptools` وخيارات Uvicorn محسنة.
- عقد توافق إصدار/مخطط وCallback/Event schema.
- Callback aliases للواجهات القديمة.
- Cache generations مشتركة للقوائم والمزايا والقوالب والهوية.
- Migration `1170_lts_turbo_update_safe`.
