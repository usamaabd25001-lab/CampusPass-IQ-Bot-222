# CampusPass IQ V11.7 LTS Turbo

High-integrity Telegram student commerce platform built with Aiogram, FastAPI, PostgreSQL and Redis.

Current release: `11.7.1-all-features-ready`.

V11.7 inherits every feature through V11.6 and adds low-latency webhook wakeups, batched durable update claims, graceful deployment draining, callback compatibility, release/schema contracts, generation-based cross-process cache invalidation, and update-safe Render blueprints.

Start with:

- `docs/releases/v11_7/README_V11_7_FIRST_AR.md`
- `docs/releases/v11_7/UPDATE_AND_ROLLBACK_RUNBOOK_AR.md`
- `render.yaml` for staging
- `render.production.yaml` for split production

The repository is ready for GitHub and Render staging. It is not production-certified until tests run against real Telegram, PostgreSQL and Redis services.
