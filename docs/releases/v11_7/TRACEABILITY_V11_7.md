# مصفوفة تتبع V11.7

| المطلب | التنفيذ | قاعدة البيانات | التحقق |
|---|---|---|---|
| OPS-007 عقد التوافق | `app/services/update_safety.py`, `ops/render_predeploy.py` | `cp_release_compatibility` | V11.7 Validator |
| OPS-008 Graceful drain | `app/main.py`, `app/api/server.py`, `app/services/telegram_updates.py` | Durable inbox | Source/compile checks |
| PERF-003 Batch + wakeup | `TelegramUpdateRuntime`, `RuntimeContext.update_wakeup` | `cp_telegram_update_inbox` | V11.7 tests/validator |
| PERF-004 Turbo JSON/server | `orjson`, `uvloop`, `httptools`, Uvicorn limits | — | dependency/source guard |
| CFG-001 Cache generations | `CacheCoherenceService`, Menu/Feature services | `cp_runtime_config_generations` | schema + validator |
| CBK-001 Callback compatibility | `callback_compat.py`, middleware | release contract schema | pure-domain assertions |

## بوابة القبول
لا يُعلن Production Certified إلا بعد نجاح Staging على Telegram وPostgreSQL وRedis الحقيقيين، وفحص restart/drain، والضغط المتزامن، والدفع والضمان والتقارير.
