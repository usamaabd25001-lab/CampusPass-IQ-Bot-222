# Traceability — V11.6

| ID | Code | Data | Acceptance |
|---|---|---|---|
| OPS-001 | `app/api/server.py`, `app/main.py` | `cp_telegram_update_inbox` | Authenticated webhook source test |
| OPS-002 | `app/services/telegram_updates.py` | Update inbox state/lease/digest | Canonical digest and retry test |
| OPS-003 | `ops/render_predeploy.py`, `deployment_gates.py` | `cp_deployment_gate_runs` | Static validator + migration check |
| OPS-004 | `ops/render_smoke.py` | — | Forged webhook rejection test |
| OPS-005 | `/health/ready`, heartbeats | Worker heartbeat/gate runs | Render readiness test |
| OPS-006 | Render blueprints | — | YAML/checksPass/preDeploy test |
