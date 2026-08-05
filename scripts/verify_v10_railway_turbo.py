from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.pool import NullPool

from app import __version__
from app.bot.handlers import build_router
from app.core.config import Settings
from app.core.release import require_release_at_least
from app.core.database import Database

BASELINE_VERSION = "10.7.0-emergency-stabilization"


def require_text(path: str, *needles: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"{path} is missing Railway Turbo marker: {needle}")


def settings_for(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyzABCDE12345",
        "ADMIN_IDS": "1",
        "REQUIRE_EXTERNAL_DATABASE": False,
        "ENCRYPTION_KEY": "railway-turbo-verification-key",
    }
    values.update(overrides)
    return Settings(**values)


async def verify_databases() -> None:
    internal = settings_for(
        DATABASE_URL=(
            "postgresql://postgres:password@postgres.railway.internal:5432/railway"
        ),
        DB_SSL_MODE="verify-full",
    )
    internal_database = Database(internal)
    assert internal_database.is_railway_internal
    assert not internal_database.is_transaction_pooler
    await internal_database.close()

    supabase = settings_for(
        DATABASE_URL=(
            "postgresql://postgres.project:password@"
            "aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
        ),
        DB_SSL_MODE="require",
    )
    supabase_database = Database(supabase)
    assert supabase_database.is_supabase
    assert supabase_database.is_transaction_pooler
    assert isinstance(supabase_database.engine.pool, NullPool)
    await supabase_database.close()


def main() -> None:
    require_release_at_least(
        __version__, BASELINE_VERSION, context="V10 Railway Turbo verification"
    )
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == __version__

    railway = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
    deploy = railway["deploy"]
    assert deploy["healthcheckPath"] == "/health/live"
    assert deploy["restartPolicyType"] == "ALWAYS"
    assert deploy["overlapSeconds"] == 0
    assert deploy["drainingSeconds"] >= 20

    require_text("app/api/server.py", '@app.get("/ping")', '@app.get("/health/ready")')
    require_text(
        "app/main.py",
        "tasks_concurrency_limit=settings.bot_update_concurrency",
        "AiohttpSession(",
        "events_isolation=event_isolation",
        "RuntimeLeaseGuard(",
        "await polling_lease.acquire",
        "⚠️ Bot is shutting down/restarting.",
        "dp.include_router(callback_fallback_router)",
        "FSMInputValidationMiddleware()",
    )
    require_text(
        "app/bot/ui.py",
        "_RENDER_LOCKS",
        "message.edit_text",
        "message.edit_reply_markup",
        "with_navigation",
        "validate_callback_markup",
    )
    require_text(
        "app/services/branding.py",
        "Local, deterministic provider branding pipeline",
        "provider.logo_file_id = candidate.file_id",
        "BrandingCandidate",
        "روابط الصور غير مقبولة",
    )
    require_text(
        "app/services/image_moderation.py",
        "validate_image",
        "_google_safe_search",
        "ensure_safe",
    )
    require_text(
        "app/services/order_coupons.py",
        "OrderCouponType.FEE_WAIVER.value",
        "OrderCouponType.FREE_REPORT.value",
        "coupon.target_user_id",
    )
    require_text(
        "app/services/finance.py",
        "referral:success:",
        "completed_count == 1",
        "referral_reward_points",
        "no automatic fee-waiver coupon is created",
    )
    require_text(
        "app/bot/handlers/payments.py",
        "payment_proof_max_bytes",
        "payment_review_keyboard(order.id)",
    )
    require_text(
        "app/bot/handlers/menu.py",
        "referral_link",
        "missing:reply:",
        "MSR-",
    )
    require_text(
        "app/services/platform_access.py",
        "def normalize_telegram_user_id",
        "async def is_platform_authorized",
        ".join(ProviderStaff",
        ".join(Provider",
    )
    require_text(
        "app/bot/handlers/provider.py",
        'F.data == "provider:terms:accept"',
        'F.data == "provider:terms:reject"',
        "user.has_platform_access = True",
        "resolve_provider_access",
    )
    require_text(
        "app/bot/ui.py",
        "send_inline_menu",
        "send_reply_menu",
        "ReplyKeyboardRemove()",
        "transition_lock",
    )
    require_text(
        "app/services/offer_lifecycle.py",
        "async def run_cycle",
        "queue_launch_announcement",
        "OfferStatus.OUT_OF_STOCK.value",
        "update(InventoryItem)",
        "InventoryItem.offer_id.in_",
    )
    require_text(
        "app/tasks/scheduler.py",
        '"offer_lifecycle"',
        "offer_lifecycle_interval_seconds",
    )
    require_text(
        "app/bot/middleware.py",
        "class RateLimitMiddleware",
        "class ActivityIndicatorMiddleware",
        "class CallbackNavigationStateMiddleware",
        '"ai": asyncio.Semaphore',
        "class FSMInputValidationMiddleware",
    )
    require_text("app/services/email_codes.py", "_recover_failure", "fetch_candidates(")
    require_text(
        "app/core/emoji.py",
        "def smart_emoji",
        'default: str = "✨"',
        '"netflix"',
        '"طبية"',
    )
    require_text(
        "app/services/catalog.py",
        "_backfilled_until",
        "_sellable_stock_condition",
        "async def promotion_providers",
        "async def promotion_offers",
    )
    require_text(
        "app/bot/handlers/catalog.py",
        'F.data == "promo:root"',
        'F.data.startswith("promo:provider:")',
        'F.data.startswith("buy:")',
    )
    require_text(
        "app/bot/handlers/provider_catalog.py",
        "smart_emoji(value)",
        "Ignored stale provider wizard callback",
    )
    require_text("app/services/reviews.py", "provider_summaries")
    require_text(
        "app/services/direct_support.py",
        "without the legacy dispute workflow",
        "async def open",
    )
    require_text("ops/google_drive_backup.py", "Google Drive token alert")

    settings = settings_for()
    assert settings.rate_limit_interval_ms == 350
    assert settings.bot_update_concurrency == 96
    assert settings.telegram_http_connection_limit == 120
    assert settings.ai_concurrency_limit == 5
    assert settings.imap_concurrency_limit == 8
    assert settings.report_concurrency_limit == 4
    assert settings.db_prepared_statement_cache_size == 100
    assert settings.offer_lifecycle_interval_seconds == 60
    assert settings.image_moderation_enabled is True
    assert settings.image_moderation_fail_closed is False
    assert settings.image_moderation_provider == "auto"
    assert settings.referral_reward_points == 10
    assert settings.referral_wallet_reward_iqd == 0
    assert settings.payment_proof_max_bytes == 15_000_000

    asyncio.run(verify_databases())

    # Import all handlers through the root router to catch circular imports and
    # missing optional symbols before Railway accepts the deployment.
    build_router()

    env = Environment(loader=FileSystemLoader(str(ROOT / "app/reports/templates")))
    env.get_template("provider_daily.html")
    env.get_template("provider_v5.html")
    print("CampusPass IQ V10.7 emergency stabilization verification passed")


if __name__ == "__main__":
    main()
