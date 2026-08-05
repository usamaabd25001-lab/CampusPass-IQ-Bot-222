# CampusPass V11 — Traceability Matrix

هذه المصفوفة تمنع ضياع المتطلبات. الحالة الحالية هي **Foundation Implemented** للنواة فقط؛ الميزات التجارية الكاملة تبقى موزعة على المراحل اللاحقة.

| المتطلبات | الوحدة الحالية | الاختبار/الحارس | الحالة |
|---|---|---|---|
| GOV-001..003 | ملفات الحوكمة في جذر المشروع | `validate_v11_foundation.py` | منفذ |
| NAV-001..004 | `app/domain/navigation.py` + Router القديم | `test_navigation_contract` | النواة منفذة |
| PAY-001..008 | `app/domain/money.py`, `WalletService`, `PaymentService` | اختبارات المحفظة + Spec Guard | أساس مالي منفذ |
| RWD-001..003 | `app/domain/status_rewards.py` | `test_status_rewards_are_configuration_driven` | محرك قواعد منفذ |
| PRV-004 | `PriceService.validate_offer_price` | فحص ثابت للحد `<250` | منفذ |
| FUL-003..005 | خدمات البريد الحالية | اختبارات التكامل في مرحلة التسليم | موروث ويعاد تطويره |
| FRD-001..005 | `app/domain/friend_packages.py` | اختبارات الرسوم والتقدم | النواة منفذة |
| WAR-001..006 | مخطط المتطلبات | اختبارات مرحلة الضمان | مخطط |
| SEC-001..004 | RateLimit V11 + DataProtection + Audit | Spec Guard واختبارات لاحقة | أساس منفذ |
| PERF-001..002 | Callback ACK/Redis/Activity Indicator | اختبارات ضغط لاحقة | أساس موروث ومحسن |
| DEL-001..003 | إزالة Runtime للخصوصية والنزاعات؛ السلة غير موجودة | Spec Guard | منفذ Runtime |

## قاعدة التتبع

كل Pull Request مستقبلي يجب أن يذكر Requirement IDs، الملفات المعدلة، Migration، الاختبارات، وطريقة Rollback.


## V11.1 Student Commerce

| المتطلبات | الوحدة الحالية | الاختبار/الحارس | الحالة |
|---|---|---|---|
| STU-003..004 | `WebAppProfileService`, `telegram_webapp.py`, `student_profile.html` | توقيع/انتهاء/حقول الملف | منفذ في V11.1 |
| MKT-001..004 | `StudentCommerceService`, `catalog.py`, `inline.py` | Validator + format/working-hours tests | أساس رحلة الطالب منفذ |
| PAY-001..002 | `calculate_invoice`, Checkout Snapshot, Wallet/Order services | اختبارات الكامل/غير الجزئي/الاسترداد | منفذ |
| PAY-003..007 | Order Coupon + Payment Proof + Amount Confirmation | Validator وحماية البصمة/المراجعة | أساس منفذ؛ رحلة Staging مطلوبة |
| RWD-001..003 | Reward status/event tables + foundation rules | Migration + Foundation tests | بنية البيانات منفذة |
| PRV-007..008 | Brand Profile + Working Hours | Migration + pure time test | بنية الطالب منفذة |
| ACL-002..003, SEC-001..004 | Telegram initData + provider review gate + receipt hash | Web App tamper tests + source guard | منفذ في المسارات الجديدة |
| NAV-003, PERF-001..002 | callback ACK/processing message/cache foundation | Source validator | منفذ كأساس |

### بوابة المرحلة

لا تنتقل V11.1 إلى Production قبل تشغيل المجموعة الكاملة داخل Docker/CI مع PostgreSQL وRedis وAiogram، وتطبيق Migration `1110_student_commerce` على Staging.


## V11.2 Provider Operations

| Requirement | Implementation | Verification |
|---|---|---|
| PRV-001 | provider terms acceptance + platform access gate | validator + model import |
| PRV-002/003/005/006 | provider catalog FSM + fulfillment profile + inventory | compile + regression tests |
| PRV-008 | provider working hours and public status | domain tests |
| PRV-009 | unified provider inbox and events | domain transitions + validator |
| PAY-005/006/008 | canonical payment configs, proof inbox and idempotency | validator + regression tests |
| FUL-001/002 | student activation email and code relay | static validation + encryption paths |
| FUL-003/004/005 | IMAP + 60-second OTP lease + 3 attempts | domain tests + compile |
| FUL-006/007 | temporary logout proof, provider confirmation, restriction | scheduler/domain tests |
| SEC-001/002/003/004 | rate limiting, evidence protection, audit/encryption | inherited + V11.2 middleware |

## V11.3 — Friends & Warranty

| Requirement | Implementation | Database | Acceptance |
|---|---|---|---|
| FRD-001..005 | `friend_packages.py`, `friends_warranty.py`, Delivery Outbox | `cp_friend_*` | `test_v11_3_friends_warranty.py` |
| WAR-001..006 | `warranties.py`, subscriptions/provider inbox handlers | `cp_warranty_*` | `test_v11_3_friends_warranty.py` |
| Reserve/24h refund | scheduler + wallet ledger + reservation lock | friend groups/members/escrow | expiry ordering test |
| Student-confirmed replacement | warranty service + fulfillment | warranty replacements/events | delayed binding test |


## V11.4 — Owner Commerce

| Requirement | Implementation | Database | Acceptance |
|---|---|---|---|
| OWN-001 | `owner_commerce.py` B2B billing + provider suspension | billing policy/proofs | V11.4 tests + validator |
| OWN-002/003 | campaign engine + segmented recipients + scheduler batches | ad campaigns/recipients | scheduler and target-rule tests |
| PAY-004 | owner/provider coupon campaigns + assignments | coupon campaign/assignment | redemption guard tests |
| OWN-007 | central owner inbox materialization | owner inbox items | unique source guard |
| OWN-008 | hybrid bundles, child orders, inventory holds, balanced allocation | hybrid bundle/purchase/hold/allocation | exact-balance and hold tests |
| OWN-009 | funded reward tasks + Telegram membership verification | reward campaigns/completions | getChatMember + wallet idempotency |
| SEC-001..004 | tenant recheck, immutable financial ledgers, receipt fingerprints | all V11.4 tables | source validator + domain tests |
| PERF-001/002 | batched campaign dispatch and background scheduler | campaign recipient queue | scheduler wiring test |


# مصفوفة تتبع V11.5

| المطلب | التنفيذ | قاعدة البيانات | الاختبار |
|---|---|---|---|
| RPT-001 Free | `ReportService.free_message` + Scheduler | `cp_daily_provider_metrics` | `test_v11_5_reports_branding_health.py` |
| RPT-002 Plus HTML | `render_artifact(format=html)` | `cp_report_artifacts` | HTML artifact test |
| RPT-003 Pro PDF/Web | API dashboard/PDF + WeasyPrint | `cp_report_artifacts` | PDF signature + rendered sample |
| RPT-004 Branding all tiers | `BrandingService`, `branding_palette.py` | `cp_provider_brand_profiles` | palette/contrast test |
| RPT-005 Official A4 | `provider_v5.html` | report reference/access | visual two-page sample |
| RPT-006 Background metrics | Scheduler + daily materialization | `cp_daily_provider_metrics` | validator |
| OWN-004 UI Builder | snapshot/list/restore | `cp_menu_revisions` | compile + validator |
| OWN-010 Health | `HealthService`, `system_metrics.py` | `cp_system_health_snapshots` | runtime metrics test |

# مصفوفة تتبع V11.6

| المطلب | التنفيذ | قاعدة البيانات | التحقق |
|---|---|---|---|
| OPS-001 Webhook موثّق | `app/api/server.py`, `app/main.py` | `cp_telegram_update_inbox` | رفض Secret مزور + Validator |
| OPS-002 Durable Inbox | `app/services/telegram_updates.py`, `app/domain/telegram_delivery.py` | `cp_telegram_update_inbox` | Digest/Retry/Lease tests |
| OPS-003 Pre-deploy Gate | `ops/render_predeploy.py`, `app/services/deployment_gates.py` | `cp_deployment_gate_runs` | V11.6 Validator |
| OPS-004 Post-deploy Smoke | `ops/render_smoke.py` | — | forged webhook + health source tests |
| OPS-005 Worker readiness | `app/api/server.py`, `app/main.py`, WorkerHeartbeat | `cp_worker_heartbeats`, `cp_deployment_gate_runs` | readiness wiring test |
| OPS-006 Render Blueprints | `render.yaml`, `render.production.yaml` | — | YAML parse + checksPass/preDeploy assertions |

## بوابة قبول V11.6

لا يُعلن Production إلا بعد نجاح Staging على Telegram وPostgreSQL وRedis حقيقيين، وتشغيل Smoke Test، واختبار إعادة التشغيل، ومنع التكرار، وفشل الـWorker، واستعادة قاعدة البيانات.

# مصفوفة تتبع V11.7

| المطلب | التنفيذ | قاعدة البيانات | التحقق |
|---|---|---|---|
| OPS-007 | Release/schema compatibility contract | `cp_release_compatibility` | V11.7 validator |
| OPS-008 | Graceful deployment drain | durable update inbox | compile/source guard |
| PERF-003 | Batch claim + immediate wakeup | Telegram update inbox | validator/domain checks |
| PERF-004 | orjson/uvloop/httptools | — | dependency guard |
| CFG-001 | Cross-process cache generations | `cp_runtime_config_generations` | schema/validator |
| CBK-001 | Versioned callback compatibility | compatibility contract | callback domain checks |

## V11.7.1 Optional Integrations

| Requirement | Implementation | Validation |
|---|---|---|
| OPT-001 Gemini readiness | `app/core/config.py`, `app/bot/handlers/support.py` | `test_v11_7_1_all_features_ready.py` |
| OPT-002 Mastercard readiness | `app/integrations/payments/mastercard.py`, `app/api/server.py` | readiness tests |
| OPT-003 Provider withdrawals | `app/services/finance.py`, `app/services/authorization.py` | readiness tests |
| OPT-004 Encrypted backup | `app/services/backups.py`, scheduler, predeploy | readiness tests |
| OPT-005 Image moderation | `app/services/image_moderation.py`, `app/services/branding.py` | local readiness test |
| OPT-006 Evidence S3 | `app/services/evidence.py` | readiness tests |
