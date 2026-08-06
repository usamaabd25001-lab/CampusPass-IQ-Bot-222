from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

try:  # uvicorn[standard] installs uvloop on Railway/Linux; safe fallback elsewhere.
    import uvloop
except ImportError:  # pragma: no cover - platform/development fallback
    uvloop = None

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError
from redis.retry import Retry
from sqlalchemy import select

from app.api.server import build_api
from app.bot.handlers import build_router
from app.bot.handlers.fallback import router as callback_fallback_router
from app.bot.middleware import (
    ActivityIndicatorMiddleware,
    BannedUserMiddleware,
    CallbackCompatibilityOuterMiddleware,
    CallbackNavigationStateMiddleware,
    FSMInputValidationMiddleware,
    OperationalRestrictionMiddleware,
    RateLimitMiddleware,
    SessionMiddleware,
)
from app.core.config import get_settings
from app.core.context import AppContext
from app.core.database import Database
from app.core.logging import configure_logging
from app.core.runtime_lock import RuntimeLeaseGuard
from app.core.observability import configure_observability
from app.core.security import SecretBox
from app.db.migrations import MIGRATIONS, run_migrations
from app.db.models import BackupRunStatus, SchemaMigration
from app.db.seed import seed_defaults
from app.plugins.loader import load_plugins
from app.services.container import Services
from app.services.telegram_updates import TelegramUpdateRuntime
from app.services.platform_access import refresh_authorized_platforms
from app.tasks.ai_support_worker import AISupportWorker
from app.tasks.scheduler import Scheduler

logger = logging.getLogger(__name__)


async def notify_admins_safely(bot: Bot, admin_ids: frozenset[int], text: str) -> None:
    """Best-effort Telegram alert that never blocks shutdown for long."""
    if not admin_ids:
        return

    async def send_one(chat_id: int) -> None:
        try:
            async with asyncio.timeout(4):
                await bot.send_message(chat_id, text)
        except Exception as exc:
            logger.warning("Could not send lifecycle alert to admin %s: %s", chat_id, type(exc).__name__)

    await asyncio.gather(*(send_one(chat_id) for chat_id in admin_ids), return_exceptions=True)


async def configure_bot(bot: Bot) -> None:
    settings = get_settings()
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="تشغيل البوت"),
                BotCommand(command="menu", description="إظهار القائمة الرئيسية"),
                BotCommand(command="cancel", description="إلغاء العملية الحالية"),
                BotCommand(command="help", description="المساعدة"),
                BotCommand(command="support", description="التواصل مع الدعم"),
                BotCommand(command="admin", description="لوحة مالك البوت"),
                BotCommand(command="diagnostics", description="تشخيص النظام للمالك"),
                BotCommand(command="recent_errors", description="آخر الأعطال للمالك"),
                BotCommand(command="version", description="إصدار البوت"),
                BotCommand(command="deployment_status", description="حالة النشر للمالك"),
                BotCommand(command="backup_status", description="حالة النسخ الاحتياطي للمالك"),
                BotCommand(command="run_backup", description="تشغيل نسخة احتياطية للمالك"),
            ]
        )
    except Exception as exc:
        logger.warning("Telegram command setup deferred: %s", type(exc).__name__)

    # Bot API supports localized names/descriptions. Failures are non-fatal because
    # Telegram can be briefly unavailable during a zero-downtime Render deploy.
    operations = (
        (bot.set_my_name, {"name": settings.bot_name}),
        (bot.set_my_name, {"name": settings.bot_name_en, "language_code": "en"}),
        (bot.set_my_short_description, {"short_description": settings.bot_short_description[:120]}),
        (bot.set_my_short_description, {"short_description": settings.bot_short_description[:120], "language_code": "en"}),
        (bot.set_my_description, {"description": settings.bot_description[:512]}),
        (bot.set_my_description, {"description": settings.bot_description[:512], "language_code": "ar"}),
    )
    for method, kwargs in operations:
        try:
            await method(**kwargs)
        except Exception as exc:
            logger.warning("Telegram profile setup deferred: %s", type(exc).__name__)


async def serve_api(context: AppContext) -> None:
    app = build_api(context)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",  # nosec B104 - Railway requires binding on all interfaces
            port=context.settings.port,
            log_level=context.settings.log_level.lower(),
            access_log=False,
            server_header=False,
            timeout_keep_alive=context.settings.uvicorn_timeout_keep_alive,
            http="httptools",
            loop="uvloop" if uvloop is not None else "asyncio",
            limit_concurrency=context.settings.uvicorn_limit_concurrency,
            backlog=context.settings.uvicorn_backlog,
        )
    )
    await server.serve()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_observability(settings)

    database = Database(settings)
    secrets = SecretBox(settings)
    telegram_session = AiohttpSession(
        limit=settings.telegram_http_connection_limit,
        timeout=settings.telegram_request_timeout_seconds,
    )
    bot = Bot(
        settings.bot_token,
        session=telegram_session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    services = Services(bot, settings, secrets)
    context = AppContext(
        settings=settings,
        database=database,
        secrets=secrets,
        services=services,
        bot=bot,
    )

    # Start the lightweight HTTP server before migrations, Redis and Telegram API calls.
    # Railway health checks can reach /ping even while external services are warming up.
    api_task = asyncio.create_task(serve_api(context), name="campuspass-api")
    await asyncio.sleep(0)

    redis_client: Redis | None = None
    storage = MemoryStorage()
    event_isolation = SimpleEventIsolation()
    dp: Dispatcher | None = None
    scheduler: Scheduler | None = None
    ai_support_worker: AISupportWorker | None = None
    polling_lease: RuntimeLeaseGuard | None = None
    update_runtime: TelegramUpdateRuntime | None = None
    update_compatibility_checks: dict | None = None

    try:
        await database.wait_until_ready()
        await database.create_tables()

        async with database.session_factory() as predeploy_session:
            existing_versions = set(
                (await predeploy_session.scalars(select(SchemaMigration.version))).all()
            )
            pending_migrations = [
                migration.version for migration in MIGRATIONS if migration.version not in existing_versions
            ]
            if (
                pending_migrations
                and settings.backup_ready
                and settings.auto_pre_deploy_backup
            ):
                logger.info(
                    "Creating verified pre-deploy backup before migrations: %s",
                    pending_migrations,
                )
                predeploy_backup = await services.backups.create(predeploy_session)
                if predeploy_backup.status != BackupRunStatus.VERIFIED.value:
                    if settings.require_pre_deploy_backup:
                        raise RuntimeError(
                            "Pre-deploy backup failed; migrations were not started: "
                            f"{predeploy_backup.last_error or 'unknown error'}"
                        )
                    logger.warning(
                        "Pre-deploy backup failed but deployment is allowed: %s",
                        predeploy_backup.last_error,
                    )
                await predeploy_session.commit()
            elif pending_migrations and settings.require_pre_deploy_backup:
                raise RuntimeError(
                    "Pending migrations require a verified backup, but automatic backup is unavailable"
                )

        async with database.session_factory() as session:
            await run_migrations(session)
            await seed_defaults(session)
            await services.cache_coherence.ensure_defaults(session)
            current_schema_head = MIGRATIONS[-1].version
            await services.update_safety.register(
                session,
                schema_head=current_schema_head,
                metadata={
                    "runtime_mode": settings.runtime_mode,
                    "git_sha": settings.git_sha,
                },
            )
            update_compatibility_checks = await services.update_safety.assert_compatible(
                session,
                schema_order=tuple(migration.version for migration in MIGRATIONS),
                current_schema_head=current_schema_head,
            )
            await services.data_protection.protect_legacy_rows(session, batch_size=500)
            await services.evidence.migrate_legacy_references(session, limit=500)
            await services.operations.register_release(session)
            # Warm authorization and menu metadata while the startup session is
            # already open. Platform-dashboard checks are O(1) after this point.
            await refresh_authorized_platforms(session)
            await services.menus.list_buttons(session)
            await services.features.enabled(session, "colored_buttons", True)
            await services.templates.seed(session)
            await services.templates.welcome_text(session, settings.welcome_text)
            await session.commit()
            context.database_ready = True
            context.release_registered = True

        bot_mode = settings.runtime_mode in {"combined", "bot"}
        worker_mode = settings.runtime_mode in {"combined", "worker"}

        if settings.redis_url:
            try:
                redis_client = Redis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    protocol=2,
                    socket_connect_timeout=2.0,
                    socket_timeout=1.0,
                    health_check_interval=30,
                    retry=Retry(ExponentialBackoff(cap=1.0, base=0.05), retries=3),
                    retry_on_error=(RedisConnectionError, RedisTimeoutError),
                )
                await redis_client.ping()
                context.redis_client = redis_client
                context.redis_ready = True
                if bot_mode:
                    storage = RedisStorage(
                        redis_client,
                        state_ttl=settings.redis_fsm_ttl_seconds,
                        data_ttl=settings.redis_fsm_ttl_seconds,
                    )
                    event_isolation = storage.create_isolation()
                    logger.info("Redis FSM storage and distributed rate limiting enabled")
                else:
                    logger.info("Redis dependency check passed for worker runtime")
            except Exception:
                logger.exception("Redis unavailable")
                if redis_client is not None:
                    await redis_client.aclose()
                redis_client = None
                context.redis_client = None
                context.redis_ready = False
                if settings.environment == "production" and settings.require_redis_in_production:
                    raise RuntimeError("Redis is required in production but is unavailable")
                if bot_mode:
                    logger.warning("Falling back to in-memory FSM storage")
                    storage = MemoryStorage()
                    event_isolation = SimpleEventIsolation()
        elif settings.environment == "production" and settings.require_redis_in_production:
            raise RuntimeError("Redis is required in production but REDIS_URL is empty")

        if bot_mode:
            # Different students stay fully concurrent, while two updates from
            # the same user/chat are serialized to protect FSM and purchase state.
            dp = Dispatcher(storage=storage, events_isolation=event_isolation)
            # Reject duplicate/spam updates before opening a PostgreSQL session.
            # This is important during a 100-200 click burst on a shared Railway CPU.
            rate_limiter = RateLimitMiddleware(
                max(0.25, settings.rate_limit_interval_ms / 1000),
                redis_client,
                duplicate_window=settings.duplicate_action_window_ms / 1000,
                sensitive_interval=settings.sensitive_action_cooldown_ms / 1000,
            )
            dp.update.outer_middleware(CallbackCompatibilityOuterMiddleware())
            dp.update.outer_middleware(rate_limiter)
            dp.update.outer_middleware(
                SessionMiddleware(
                    database,
                    settings,
                    services,
                    slow_warning_ms=settings.slow_update_warning_ms,
                )
            )
            processing = ActivityIndicatorMiddleware(
                settings.processing_indicator_delay_ms,
                settings.processing_message_text,
                ai_limit=settings.ai_concurrency_limit,
                imap_limit=settings.imap_concurrency_limit,
                report_limit=settings.report_concurrency_limit,
                long_operation_limit=settings.long_operation_concurrency_limit,
            )
            dp.callback_query.middleware(CallbackNavigationStateMiddleware())
            dp.message.middleware(FSMInputValidationMiddleware())
            for observer in (dp.message, dp.callback_query):
                observer.middleware(
                    BannedUserMiddleware(settings.banned_user_cache_ttl_seconds)
                )
                observer.middleware(OperationalRestrictionMiddleware())
                observer.middleware(processing)
            dp.include_router(build_router())
            await load_plugins(dp, context)
            # Must be last: known core/plugin callbacks always win.
            dp.include_router(callback_fallback_router)
            context.dispatcher = dp
            await configure_bot(bot)
            allowed_updates = dp.resolve_used_update_types()
            if settings.telegram_delivery_mode == "webhook":
                update_runtime = TelegramUpdateRuntime(context, dp)
                await update_runtime.start()
                webhook_url = f"{settings.public_base_url}{settings.telegram_webhook_path}"
                await bot.set_webhook(
                    url=webhook_url,
                    secret_token=settings.telegram_webhook_secret,
                    max_connections=settings.telegram_webhook_max_connections,
                    allowed_updates=allowed_updates,
                    drop_pending_updates=settings.telegram_webhook_drop_pending_updates,
                )
                info = await bot.get_webhook_info()
                if info.url != webhook_url:
                    raise RuntimeError("Telegram webhook URL verification failed")
                context.webhook_ready = True
                logger.info("Durable Telegram webhook enabled url=%s", webhook_url)
            else:
                await bot.delete_webhook(drop_pending_updates=False)
                polling_lease = RuntimeLeaseGuard(
                    database,
                    bot_token=settings.bot_token,
                    release_id=settings.release_id,
                    ttl_seconds=45,
                )
                await polling_lease.acquire(wait_seconds=90)
                logger.info("Telegram long polling enabled")
            context.bot_ready = True

        if worker_mode:
            scheduler = Scheduler(context)
            ai_support_worker = AISupportWorker(context)
            await scheduler.start()
            await ai_support_worker.start()
            context.worker_ready = True

        async with database.session_factory() as session:
            await services.operations.mark_release_ready(session)
            await services.update_safety.mark_ready(
                session, checks=update_compatibility_checks or {}
            )
            await session.commit()
        gate_deadline = asyncio.get_running_loop().time() + settings.deployment_gate_wait_seconds
        while True:
            async with database.session_factory() as gate_session:
                gate = await services.deployment_gates.run(
                    gate_session,
                    redis_client=redis_client,
                    include_telegram=bot_mode,
                    include_webhook=bot_mode,
                    include_worker=True,
                    persist=True,
                )
                await gate_session.commit()
            context.last_gate_checks = gate
            context.deployment_gate_ready = bool(gate.get("ok"))
            if context.deployment_gate_ready or not settings.deployment_gate_strict:
                break
            if asyncio.get_running_loop().time() >= gate_deadline:
                raise RuntimeError("Strict deployment gate failed")
            logger.warning("Deployment gate not ready; retrying in 3 seconds")
            await asyncio.sleep(3)
        context.ready = True
        context.startup_error = ""
        logger.info(
            "CampusPass IQ started runtime_mode=%s release_id=%s",
            settings.runtime_mode,
            settings.release_id,
        )
        if bot_mode and dp is not None and settings.telegram_delivery_mode == "polling":
            logger.info(
                "Polling profile enabled update_concurrency=%s telegram_http_limit=%s",
                settings.bot_update_concurrency,
                settings.telegram_http_connection_limit,
            )
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
                polling_timeout=30,
                handle_as_tasks=True,
                tasks_concurrency_limit=settings.bot_update_concurrency,
                close_bot_session=False,
            )
        elif bot_mode and settings.telegram_delivery_mode == "webhook":
            await api_task
        elif scheduler is not None and scheduler.task is not None:
            await scheduler.task
        else:
            raise RuntimeError("RUNTIME_MODE did not start bot or worker")
    except Exception as exc:
        context.ready = False
        context.startup_error = type(exc).__name__
        logger.exception("CampusPass startup failed")
        if context.database_ready and context.release_registered:
            with contextlib.suppress(Exception):
                async with database.session_factory() as session:
                    error_text = f"{type(exc).__name__}: {str(exc)[:800]}"
                    await services.operations.mark_release_failed(session, error_text)
                    await services.update_safety.mark_failed(session, error_text)
                    await session.commit()
        raise
    finally:
        context.draining = True
        context.ready = False
        context.bot_ready = False
        context.worker_ready = False
        context.webhook_ready = False
        context.deployment_gate_ready = False
        if update_runtime is not None:
            await update_runtime.stop()
        if ai_support_worker is not None:
            await ai_support_worker.stop()
        if scheduler is not None:
            await scheduler.stop()
        if polling_lease is not None:
            await polling_lease.release()
        if dp is not None:
            await dp.storage.close()
        else:
            await storage.close()
        if redis_client is not None:
            with contextlib.suppress(Exception):
                await redis_client.aclose()
        context.redis_client = None
        context.redis_ready = False
        if context.database_ready and context.release_registered:
            with contextlib.suppress(Exception):
                async with database.session_factory() as session:
                    await services.operations.mark_release_stopped(session)
                    await session.commit()
        # Send before closing the aiohttp session used internally by aiogram.
        if settings.runtime_mode in {"combined", "bot"}:
            await notify_admins_safely(
                bot,
                settings.admin_ids,
                "⚠️ Bot is shutting down/restarting.",
            )
        await services.gemini.close()
        await bot.session.close()
        await database.close()
        api_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await api_task


def _safe_configuration_error(exc: ValidationError) -> str:
    """Render configuration errors without echoing secret input values."""
    messages: list[str] = []
    for item in exc.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item.get("loc", ())) or "settings"
        message = str(item.get("msg", "invalid value"))
        messages.append(f"{location}: {message}")
    return "; ".join(messages) or "invalid deployment variables"


if __name__ == "__main__":
    try:
        if uvloop is not None:
            uvloop.run(main())
        else:
            asyncio.run(main())
    except ValidationError as exc:
        # Never print Pydantic's default exception, because it can include values
        # such as BOT_TOKEN. Only field names and safe validation messages appear.
        print(f"CampusPass configuration error: {_safe_configuration_error(exc)}", file=sys.stderr)
        raise SystemExit(2) from None
