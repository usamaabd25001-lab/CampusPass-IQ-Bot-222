# CampusPass IQ – Implementation Roadmap

## Phase 0 — Freeze
- تثبيت Master Spec وسجل المتطلبات.
- فتح Repository جديد وفرع main محمي.
- منع أي كود بلا Requirement ID.

## Phase 1 — Isolation
- نسخ المشروع القديم.
- Token وPostgreSQL وRedis وObject Storage مستقل.
- حذف Privacy Requests وLegacy Disputes وAbandoned Cart.
- CI واختبارات الأساس.

## Phase 2 — Core
- Roles وProvider Isolation.
- Global Back/Home.
- Redis FSM.
- Start Message Editor.
- Anti-Spam الأساسي.

## Phase 3 — Student
- Onboarding وWeb App.
- القوائم والحساب.
- المتجر والمفضلة والدعم.

## Phase 4 — Money
- Pricing/Coupons.
- خصم المحفظة التلقائي 500 د.ع.
- Payment Methods وProof Review.
- Wallet Ledger وIdempotency.

## Phase 5 — Provider
- Onboarding.
- Store FSM.
- Inventory.
- Working Hours.
- Provider Inbox.
- Branding.

## Phase 6 — Fulfillment
- Student Email Activation.
- Student OTP Relay.
- IMAP OTP.
- Temporary Accounts.
- Logout Confirmation.

## Phase 7 — Friends & Warranty
- باقة أصدقائي فقط.
- Reserve/Escrow/24h.
- Full fee per member.
- Warranty from Subscriptions.
- OTP continuation.

## Phase 8 — Owner
- B2B Billing.
- Central Inbox.
- Ads & Targeting.
- Coupons.
- UI Builder.
- Users/Assistants.
- Hybrid Bundles.
- Reward Tasks.

## Phase 9 — Reports
- Free branded text.
- Plus branded HTML.
- Pro Web App + A4 PDF.
- Celery/Beat/Materialized Views.

## Phase 10 — Validation
- Unit/Integration/Permission/Concurrency/Load/Security tests.
- Staging.
- Production.
- Rollback drill.
