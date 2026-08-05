from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Annotated, Any
from urllib.parse import urlparse

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.db_url import database_hostname, normalize_async_database_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    admin_ids: Annotated[frozenset[int], NoDecode] = Field(alias="ADMIN_IDS")
    database_url: str = Field(default="sqlite+aiosqlite:///./campuspass.db", alias="DATABASE_URL")
    redis_url: str = Field(default="", alias="REDIS_URL")
    require_external_database: bool = Field(default=True, alias="REQUIRE_EXTERNAL_DATABASE")
    db_ssl_mode: str = Field(default="verify-full", alias="DB_SSL_MODE")
    db_ca_cert_b64: str = Field(default="", alias="DB_CA_CERT_B64")
    db_pool_size: int = Field(default=10, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_pool_pre_ping: bool = Field(default=False, alias="DB_POOL_PRE_PING")
    db_pool_timeout_seconds: int = Field(default=15, alias="DB_POOL_TIMEOUT_SECONDS")
    db_pool_recycle_seconds: int = Field(default=900, alias="DB_POOL_RECYCLE_SECONDS")
    db_connect_timeout_seconds: int = Field(default=15, alias="DB_CONNECT_TIMEOUT_SECONDS")
    db_statement_timeout_ms: int = Field(default=30000, alias="DB_STATEMENT_TIMEOUT_MS")
    db_startup_retries: int = Field(default=8, alias="DB_STARTUP_RETRIES")
    db_startup_retry_seconds: float = Field(default=5.0, alias="DB_STARTUP_RETRY_SECONDS")
    db_application_name: str = Field(default="campuspass-iq", alias="DB_APPLICATION_NAME")
    db_prepared_statement_cache_size: int = Field(
        default=100, alias="DB_PREPARED_STATEMENT_CACHE_SIZE"
    )

    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    timezone: str = Field(default="Asia/Baghdad", alias="TIMEZONE")
    port: int = Field(default=8080, alias="PORT")
    public_base_url: str = Field(default="", alias="PUBLIC_BASE_URL")
    railway_public_domain: str = Field(default="", alias="RAILWAY_PUBLIC_DOMAIN", exclude=True)
    render_external_url: str = Field(default="", alias="RENDER_EXTERNAL_URL", exclude=True)
    render_external_hostname: str = Field(
        default="", alias="RENDER_EXTERNAL_HOSTNAME", exclude=True
    )
    render_service_id: str = Field(default="", alias="RENDER_SERVICE_ID", exclude=True)
    render_instance_id: str = Field(default="", alias="RENDER_INSTANCE_ID", exclude=True)
    render_git_commit: str = Field(default="", alias="RENDER_GIT_COMMIT", exclude=True)
    api_admin_token: str = Field(default="", alias="API_ADMIN_TOKEN")
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")
    sentry_traces_sample_rate: float = Field(default=0.0, alias="SENTRY_TRACES_SAMPLE_RATE")
    metrics_enabled: bool = Field(default=True, alias="METRICS_ENABLED")
    metrics_token: str = Field(default="", alias="METRICS_TOKEN")

    bot_name: str = Field(default="CampusPass IQ Bot", alias="BOT_NAME")
    bot_name_en: str = Field(default="CampusPass IQ Bot", alias="BOT_NAME_EN")
    bot_short_description: str = Field(
        default="Student subscriptions and digital services", alias="BOT_SHORT_DESCRIPTION"
    )
    bot_description: str = Field(
        default="منصة اشتراكات وخدمات طلابية متعددة المزودين.", alias="BOT_DESCRIPTION"
    )
    welcome_text: str = Field(
        default="أهلًا بك في CampusPass IQ Bot 👋\\nمنصة الاشتراكات والخدمات الطلابية.",
        alias="WELCOME_TEXT",
    )
    help_text: str = Field(default="اختر القسم المطلوب من القائمة.", alias="HELP_TEXT")
    support_text: str = Field(
        default="اختر المشكلة المقترحة أو اكتب سؤالك بالتفصيل.", alias="SUPPORT_TEXT"
    )
    terms_text: str = Field(
        default=(
            "يُعد تقديم بياناتك الأكاديمية والشخصية الصحيحة (كالاسم الثلاثي والجامعة) "
            "شرطاً أساسياً لضمان حقوقك والاستفادة من العروض والخدمات المقدمة في المنصة."
        ),
        alias="TERMS_TEXT",
    )
    provider_terms_version: str = Field(
        default="provider-v11.2", alias="PROVIDER_TERMS_VERSION"
    )
    provider_terms_text: str = Field(
        default=(
            "🛡 مرحباً بك في لوحة الإدارة الخاصة بمنصتك على CampusPass IQ\n\n"
            "1️⃣ آلية الرسوم: لا يستقطع البوت من سعر خدمتك الأصلي، بل يضيف رسوم خدمة "
            "رمزية يدفعها الطالب لتغطية التشغيل.\n\n"
            "2️⃣ الولاء والخصومات: تستطيع إطلاق أكواد وحملات لطلابك، وتُفتح الميزات "
            "حسب خطة منصتك.\n\n"
            "3️⃣ الشفافية والأمان: تعرض اللوحة الحركات المالية والتشغيلية الخاصة بمنصتك "
            "فقط، وتبقى بيانات المنصات معزولة.\n\n"
            "بالضغط على «أوافق وأبدأ العمل» تقر بقراءة سياسة العمل."
        ),
        alias="PROVIDER_TERMS_TEXT",
    )
    privacy_text: str = Field(
        default=(
            "نلتزم التزاماً كاملاً بحماية خصوصيتك. تُجمع بياناتك الأساسية وتُعالج   "
            "وحصراً لغرض إدارة اشتراكاتك وتقديم الدعم الفني لك. جميع معلوماتك محفوظة "
            "في بيئة آمنة، ولا يتم مشاركتها مع أي جهات خارجية أو استخدامها لأغراض تجارية "
            "دون موافقتك الصريحة."
        ),
        alias="PRIVACY_TEXT",
    )
        ),
        alias="PRIVACY_TEXT",
    )
    welcome_photo: str = Field(default="", alias="WELCOME_PHOTO")
    bot_logo_url: str = Field(default="", alias="BOT_LOGO_URL")
    export_logo_path: str = Field(
        default="app/reports/assets/campuspass-iq-horizontal.png", alias="EXPORT_LOGO_PATH"
    )
    brand_primary_color: str = Field(default="#003279", alias="BRAND_PRIMARY_COLOR")
    brand_secondary_color: str = Field(default="#14A5A2", alias="BRAND_SECONDARY_COLOR")
    brand_dark_color: str = Field(default="#082F63", alias="BRAND_DARK_COLOR")
    support_username: str = Field(default="", alias="SUPPORT_USERNAME")

    default_service_fee_iqd: int = Field(default=500, alias="DEFAULT_SERVICE_FEE_IQD")
    default_management_percent: int = Field(default=5, alias="DEFAULT_MANAGEMENT_PERCENT")
    default_provider_plan: str = Field(default="free", alias="DEFAULT_PROVIDER_PLAN")
    default_subscription_grace_days: int = Field(default=3, alias="DEFAULT_SUBSCRIPTION_GRACE_DAYS")
    default_trial_days: int = Field(default=7, alias="DEFAULT_TRIAL_DAYS")
    default_trial_plan: str = Field(default="pro", alias="DEFAULT_TRIAL_PLAN")
    subscription_reminder_days: Annotated[tuple[int, ...], NoDecode] = Field(
        default=(3, 1), alias="SUBSCRIPTION_REMINDER_DAYS"
    )
    default_payment_instructions: str = Field(
        default="سيعرض لك البوت معلومات التحويل الخاصة بالمنصة.",
        alias="DEFAULT_PAYMENT_INSTRUCTIONS",
    )
    purchase_reservation_minutes: int = Field(default=15, alias="PURCHASE_RESERVATION_MINUTES")
    payment_review_reservation_hours: int = Field(
        default=2, alias="PAYMENT_REVIEW_RESERVATION_HOURS"
    )
    max_open_payment_reviews_per_user: int = Field(
        default=3, alias="MAX_OPEN_PAYMENT_REVIEWS_PER_USER"
    )
    delivery_retry_seconds: int = Field(default=30, alias="DELIVERY_RETRY_SECONDS")
    delivery_max_attempts: int = Field(default=3, alias="DELIVERY_MAX_ATTEMPTS")
    delivery_lease_seconds: int = Field(default=180, alias="DELIVERY_LEASE_SECONDS")
    processing_indicator_delay_ms: int = Field(default=50, alias="PROCESSING_INDICATOR_DELAY_MS")
    processing_message_text: str = Field(
        default="جاري المعالجة، يرجى الانتظار...", alias="PROCESSING_MESSAGE_TEXT"
    )
    # Railway turbo profile: keep accidental double-click protection without
    # imposing the old two-second pause on normal navigation.
    rate_limit_interval_ms: int = Field(default=350, alias="RATE_LIMIT_INTERVAL_MS")
    duplicate_action_window_ms: int = Field(
        default=2_000, alias="DUPLICATE_ACTION_WINDOW_MS"
    )
    sensitive_action_cooldown_ms: int = Field(
        default=1_250, alias="SENSITIVE_ACTION_COOLDOWN_MS"
    )
    bot_update_concurrency: int = Field(default=96, alias="BOT_UPDATE_CONCURRENCY")
    telegram_http_connection_limit: int = Field(
        default=120, alias="TELEGRAM_HTTP_CONNECTION_LIMIT"
    )
    telegram_request_timeout_seconds: float = Field(
        default=30.0, alias="TELEGRAM_REQUEST_TIMEOUT_SECONDS"
    )
    telegram_delivery_mode: str = Field(default="polling", alias="TELEGRAM_DELIVERY_MODE")
    telegram_webhook_path: str = Field(default="/telegram/webhook", alias="TELEGRAM_WEBHOOK_PATH")
    telegram_webhook_secret: str = Field(default="", alias="TELEGRAM_WEBHOOK_SECRET")
    telegram_webhook_max_connections: int = Field(default=40, alias="TELEGRAM_WEBHOOK_MAX_CONNECTIONS")
    telegram_webhook_drop_pending_updates: bool = Field(
        default=False, alias="TELEGRAM_WEBHOOK_DROP_PENDING_UPDATES"
    )
    telegram_webhook_body_limit_bytes: int = Field(
        default=1_048_576, alias="TELEGRAM_WEBHOOK_BODY_LIMIT_BYTES"
    )
    telegram_update_consumers: int = Field(default=8, alias="TELEGRAM_UPDATE_CONSUMERS")
    telegram_update_claim_batch_size: int = Field(
        default=4, alias="TELEGRAM_UPDATE_CLAIM_BATCH_SIZE"
    )
    telegram_update_idle_wait_ms: int = Field(
        default=100, alias="TELEGRAM_UPDATE_IDLE_WAIT_MS"
    )
    telegram_update_graceful_shutdown_seconds: float = Field(
        default=25.0, alias="TELEGRAM_UPDATE_GRACEFUL_SHUTDOWN_SECONDS"
    )
    telegram_update_lease_seconds: int = Field(default=90, alias="TELEGRAM_UPDATE_LEASE_SECONDS")
    telegram_update_max_attempts: int = Field(default=8, alias="TELEGRAM_UPDATE_MAX_ATTEMPTS")
    telegram_update_retention_days: int = Field(default=14, alias="TELEGRAM_UPDATE_RETENTION_DAYS")
    cache_generation_poll_seconds: float = Field(
        default=2.0, alias="CACHE_GENERATION_POLL_SECONDS"
    )
    update_min_compatible_version: str = Field(
        default="11.6.0-render-e2e-hardening", alias="UPDATE_MIN_COMPATIBLE_VERSION"
    )
    update_min_compatible_schema: str = Field(
        default="11.6.0-render-e2e-hardening", alias="UPDATE_MIN_COMPATIBLE_SCHEMA"
    )
    update_callback_schema_version: int = Field(
        default=1, alias="UPDATE_CALLBACK_SCHEMA_VERSION"
    )
    update_event_schema_version: int = Field(
        default=1, alias="UPDATE_EVENT_SCHEMA_VERSION"
    )
    update_rollout_percent: float = Field(default=100.0, alias="UPDATE_ROLLOUT_PERCENT")
    update_require_expand_contract: bool = Field(
        default=True, alias="UPDATE_REQUIRE_EXPAND_CONTRACT"
    )
    uvicorn_limit_concurrency: int = Field(
        default=1000, alias="UVICORN_LIMIT_CONCURRENCY"
    )
    uvicorn_backlog: int = Field(default=2048, alias="UVICORN_BACKLOG")
    uvicorn_timeout_keep_alive: int = Field(
        default=10, alias="UVICORN_TIMEOUT_KEEP_ALIVE"
    )
    require_fresh_worker_heartbeat: bool = Field(
        default=False, alias="REQUIRE_FRESH_WORKER_HEARTBEAT"
    )
    deployment_gate_strict: bool = Field(default=False, alias="DEPLOYMENT_GATE_STRICT")
    deployment_gate_wait_seconds: int = Field(default=90, alias="DEPLOYMENT_GATE_WAIT_SECONDS")
    ai_concurrency_limit: int = Field(default=5, alias="AI_CONCURRENCY_LIMIT")
    imap_concurrency_limit: int = Field(default=8, alias="IMAP_CONCURRENCY_LIMIT")
    report_concurrency_limit: int = Field(default=4, alias="REPORT_CONCURRENCY_LIMIT")
    long_operation_concurrency_limit: int = Field(
        default=12, alias="LONG_OPERATION_CONCURRENCY_LIMIT"
    )
    slow_update_warning_ms: int = Field(default=750, alias="SLOW_UPDATE_WARNING_MS")
    banned_user_cache_ttl_seconds: float = Field(
        default=30.0, alias="BANNED_USER_CACHE_TTL_SECONDS"
    )
    redis_fsm_ttl_seconds: int = Field(default=86400, alias="REDIS_FSM_TTL_SECONDS")
    require_redis_in_production: bool = Field(default=False, alias="REQUIRE_REDIS_IN_PRODUCTION")
    scheduler_lock_id: int = Field(default=410001, alias="SCHEDULER_LOCK_ID")
    offer_lifecycle_interval_seconds: int = Field(default=60, alias="OFFER_LIFECYCLE_INTERVAL_SECONDS")

    image_moderation_enabled: bool = Field(default=True, alias="IMAGE_MODERATION_ENABLED")
    image_moderation_provider: str = Field(default="auto", alias="IMAGE_MODERATION_PROVIDER")
    google_vision_api_key: str = Field(default="", alias="GOOGLE_VISION_API_KEY")
    image_moderation_fail_closed: bool = Field(default=False, alias="IMAGE_MODERATION_FAIL_CLOSED")
    image_moderation_timeout_seconds: float = Field(default=15.0, alias="IMAGE_MODERATION_TIMEOUT_SECONDS")
    image_moderation_block_likelihood: str = Field(default="LIKELY", alias="IMAGE_MODERATION_BLOCK_LIKELIHOOD")

    runtime_mode: str = Field(default="combined", alias="RUNTIME_MODE")
    release_id: str = Field(default="manual-release", alias="RELEASE_ID")
    railway_deployment_id: str = Field(default="", alias="RAILWAY_DEPLOYMENT_ID", exclude=True)
    git_sha: str = Field(default="", alias="GIT_SHA")
    railway_git_commit_sha: str = Field(
        default="", alias="RAILWAY_GIT_COMMIT_SHA", exclude=True
    )
    previous_release_id: str = Field(default="", alias="PREVIOUS_RELEASE_ID")
    staging_guard_enabled: bool = Field(default=True, alias="STAGING_GUARD_ENABLED")
    staging_bot_token_fingerprint: str = Field(default="", alias="STAGING_BOT_TOKEN_FINGERPRINT")
    scheduler_lease_seconds: int = Field(default=300, alias="SCHEDULER_LEASE_SECONDS")
    scheduled_run_retention_days: int = Field(default=90, alias="SCHEDULED_RUN_RETENTION_DAYS")
    incident_retention_days: int = Field(default=180, alias="INCIDENT_RETENTION_DAYS")

    pilot_mode: bool = Field(default=False, alias="PILOT_MODE")
    pilot_strict_startup: bool = Field(default=False, alias="PILOT_STRICT_STARTUP")
    pilot_require_redis: bool = Field(default=True, alias="PILOT_REQUIRE_REDIS")
    pilot_require_storage: bool = Field(default=True, alias="PILOT_REQUIRE_STORAGE")
    pilot_require_verified_backup: bool = Field(default=True, alias="PILOT_REQUIRE_VERIFIED_BACKUP")
    pilot_backup_max_age_hours: int = Field(default=30, alias="PILOT_BACKUP_MAX_AGE_HOURS")
    pilot_validation_timeout_seconds: int = Field(default=10, alias="PILOT_VALIDATION_TIMEOUT_SECONDS")
    pilot_min_free_inventory: int = Field(default=1, alias="PILOT_MIN_FREE_INVENTORY")
    chaos_testing_enabled: bool = Field(default=False, alias="CHAOS_TESTING_ENABLED")
    chaos_testing_token: str = Field(default="", alias="CHAOS_TESTING_TOKEN")
    enterprise_job_lease_seconds: int = Field(default=180, alias="ENTERPRISE_JOB_LEASE_SECONDS")
    enterprise_job_base_backoff_seconds: int = Field(default=15, alias="ENTERPRISE_JOB_BASE_BACKOFF_SECONDS")
    enterprise_job_max_backoff_seconds: int = Field(default=3600, alias="ENTERPRISE_JOB_MAX_BACKOFF_SECONDS")
    enterprise_worker_stale_seconds: int = Field(default=120, alias="ENTERPRISE_WORKER_STALE_SECONDS")
    enterprise_webhook_timeout_seconds: int = Field(default=10, alias="ENTERPRISE_WEBHOOK_TIMEOUT_SECONDS")
    enterprise_webhook_max_attempts: int = Field(default=8, alias="ENTERPRISE_WEBHOOK_MAX_ATTEMPTS")
    enterprise_webhook_base_backoff_seconds: int = Field(default=30, alias="ENTERPRISE_WEBHOOK_BASE_BACKOFF_SECONDS")
    enterprise_webhook_max_backoff_seconds: int = Field(default=21600, alias="ENTERPRISE_WEBHOOK_MAX_BACKOFF_SECONDS")
    enterprise_grace_days: int = Field(default=7, alias="ENTERPRISE_GRACE_DAYS")

    backup_enabled: bool = Field(default=True, alias="BACKUP_ENABLED")
    auto_pre_deploy_backup: bool = Field(default=True, alias="AUTO_PRE_DEPLOY_BACKUP")
    require_pre_deploy_backup: bool = Field(default=False, alias="REQUIRE_PRE_DEPLOY_BACKUP")
    backup_hour: int = Field(default=3, alias="BACKUP_HOUR")
    backup_minute: int = Field(default=30, alias="BACKUP_MINUTE")
    backup_retention_days: int = Field(default=14, alias="BACKUP_RETENTION_DAYS")
    backup_max_bytes: int = Field(default=268435456, alias="BACKUP_MAX_BYTES")
    backup_pg_dump_path: str = Field(default="pg_dump", alias="BACKUP_PG_DUMP_PATH")
    backup_storage_backend: str = Field(default="s3", alias="BACKUP_STORAGE_BACKEND")
    backup_s3_endpoint: str = Field(default="", alias="BACKUP_S3_ENDPOINT")
    backup_s3_bucket: str = Field(default="", alias="BACKUP_S3_BUCKET")
    backup_s3_region: str = Field(default="auto", alias="BACKUP_S3_REGION")
    backup_s3_access_key: str = Field(default="", alias="BACKUP_S3_ACCESS_KEY")
    backup_s3_secret_key: str = Field(default="", alias="BACKUP_S3_SECRET_KEY")
    backup_s3_prefix: str = Field(default="campuspass/backups", alias="BACKUP_S3_PREFIX")
    backup_alert_after_hours: int = Field(default=30, alias="BACKUP_ALERT_AFTER_HOURS")

    encryption_key_version: int = Field(default=1, alias="ENCRYPTION_KEY_VERSION")
    encryption_keyring: Annotated[tuple[str, ...], NoDecode] = Field(default=(), alias="ENCRYPTION_KEYRING")
    key_rotation_batch_size: int = Field(default=100, alias="KEY_ROTATION_BATCH_SIZE")

    encryption_key: str = Field(default="", alias="ENCRYPTION_KEY")
    report_secret_key: str = Field(default="", alias="REPORT_SECRET_KEY")
    report_token_days: int = Field(default=2, alias="REPORT_TOKEN_DAYS")
    report_max_accesses: int = Field(default=20, alias="REPORT_MAX_ACCESSES")
    report_snapshot_retention_days: int = Field(default=30, alias="REPORT_SNAPSHOT_RETENTION_DAYS")
    daily_report_hour: int = Field(default=23, alias="DAILY_REPORT_HOUR")
    daily_report_minute: int = Field(default=55, alias="DAILY_REPORT_MINUTE")

    privacy_policy_version: str = Field(default="1.0", alias="PRIVACY_POLICY_VERSION")
    evidence_retention_days: int = Field(default=180, alias="EVIDENCE_RETENTION_DAYS")
    evidence_external_storage_enabled: bool = Field(default=True, alias="EVIDENCE_EXTERNAL_STORAGE_ENABLED")
    evidence_s3_endpoint: str = Field(default="", alias="EVIDENCE_S3_ENDPOINT")
    evidence_s3_bucket: str = Field(default="", alias="EVIDENCE_S3_BUCKET")
    evidence_s3_region: str = Field(default="auto", alias="EVIDENCE_S3_REGION")
    evidence_s3_access_key: str = Field(default="", alias="EVIDENCE_S3_ACCESS_KEY")
    evidence_s3_secret_key: str = Field(default="", alias="EVIDENCE_S3_SECRET_KEY")
    require_external_evidence_storage_in_production: bool = Field(
        default=False, alias="REQUIRE_EXTERNAL_EVIDENCE_STORAGE_IN_PRODUCTION"
    )

    feature_gemini: bool = Field(default=True, alias="FEATURE_GEMINI")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.6-flash", alias="GEMINI_MODEL")
    gemini_system_prompt: str = Field(
        default=(
            "أنت مساعد دعم لمنصة اشتراكات طلابية. أجب باختصار ولا تطلب كلمات مرور "
            "أو رموز تحقق أو بيانات بطاقة، ولا تؤكد دفعًا أو استرجاعًا."
        ),
        alias="GEMINI_SYSTEM_PROMPT",
    )

    feature_email_codes: bool = Field(default=False, alias="FEATURE_EMAIL_CODES")
    email_poll_seconds: int = Field(default=20, alias="EMAIL_POLL_SECONDS")
    email_reservation_minutes: int = Field(default=10, alias="EMAIL_RESERVATION_MINUTES")
    email_ambiguity_policy: str = Field(default="review", alias="EMAIL_AMBIGUITY_POLICY")
    email_imap_timeout_seconds: int = Field(default=20, alias="EMAIL_IMAP_TIMEOUT_SECONDS")
    email_imap_overall_timeout_seconds: int = Field(
        default=30, alias="EMAIL_IMAP_OVERALL_TIMEOUT_SECONDS"
    )
    max_code_attempts: int = Field(default=3, alias="MAX_CODE_ATTEMPTS")
    otp_account_lease_seconds: int = Field(default=60, alias="OTP_ACCOUNT_LEASE_SECONDS")
    temporary_logout_grace_minutes: int = Field(
        default=30, alias="TEMPORARY_LOGOUT_GRACE_MINUTES"
    )

    feature_mastercard: bool = Field(default=True, alias="FEATURE_MASTERCARD")
    payment_gateway_create_url: str = Field(default="", alias="PAYMENT_GATEWAY_CREATE_URL")
    payment_gateway_status_url: str = Field(default="", alias="PAYMENT_GATEWAY_STATUS_URL")
    payment_gateway_api_key: str = Field(default="", alias="PAYMENT_GATEWAY_API_KEY")
    payment_gateway_merchant_id: str = Field(default="", alias="PAYMENT_GATEWAY_MERCHANT_ID")
    payment_webhook_secret: str = Field(default="", alias="PAYMENT_WEBHOOK_SECRET")
    payment_success_statuses: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("paid", "success", "successful", "approved", "captured", "completed"),
        alias="PAYMENT_SUCCESS_STATUSES",
    )
    payment_failure_statuses: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("failed", "declined", "cancelled", "canceled", "expired", "voided"),
        alias="PAYMENT_FAILURE_STATUSES",
    )
    payment_webhook_max_body_bytes: int = Field(
        default=262144, alias="PAYMENT_WEBHOOK_MAX_BODY_BYTES"
    )

    feature_reports: bool = Field(default=True, alias="FEATURE_REPORTS")
    feature_referrals: bool = Field(default=True, alias="FEATURE_REFERRALS")
    referral_reward_points: int = Field(default=10, alias="REFERRAL_REWARD_POINTS")
    referral_wallet_reward_iqd: int = Field(default=0, alias="REFERRAL_WALLET_REWARD_IQD")
    payment_proof_max_bytes: int = Field(default=15_000_000, alias="PAYMENT_PROOF_MAX_BYTES")
    feature_provider_withdrawals: bool = Field(default=True, alias="FEATURE_PROVIDER_WITHDRAWALS")
    money_flow_model: str = Field(
        default="provider_direct_prepaid_commission", alias="MONEY_FLOW_MODEL"
    )
    feature_colored_buttons: bool = Field(default=True, alias="FEATURE_COLORED_BUTTONS")
    maintenance_mode: bool = Field(default=False, alias="MAINTENANCE_MODE")

    plugin_modules: Annotated[tuple[str, ...], NoDecode] = Field(default=(), alias="PLUGIN_MODULES")

    @field_validator("money_flow_model", mode="before")
    @classmethod
    def normalize_money_flow_model(cls, value: Any) -> str:
        normalized = str(value or "provider_direct_prepaid_commission").strip().lower()
        allowed = {
            "provider_direct_prepaid_commission",
            "gateway_marketplace",
        }
        if normalized not in allowed:
            raise ValueError(
                "MONEY_FLOW_MODEL must be provider_direct_prepaid_commission or gateway_marketplace"
            )
        return normalized

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, value: Any) -> str:
        normalized = str(value or "development").strip().lower()
        aliases = {"prod": "production", "dev": "development", "local": "development"}
        normalized = aliases.get(normalized, normalized)
        if normalized not in {"development", "test", "staging", "production"}:
            raise ValueError(
                "ENVIRONMENT must be development, test, staging, or production"
            )
        return normalized

    @field_validator(
        "bot_token",
        "encryption_key",
        "report_secret_key",
        "api_admin_token",
        "sentry_dsn",
        "metrics_token",
        "gemini_api_key",
        "google_vision_api_key",
        "redis_url",
        "evidence_s3_access_key",
        "evidence_s3_secret_key",
        "backup_s3_access_key",
        "backup_s3_secret_key",
        mode="before",
    )
    @classmethod
    def strip_secret_values(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: Any) -> frozenset[int]:
        if isinstance(value, set | frozenset | list | tuple):
            return frozenset(int(item) for item in value)
        if isinstance(value, int):
            return frozenset({value})
        if not isinstance(value, str) or not value.strip():
            raise ValueError("ADMIN_IDS is required")
        normalized = value.strip()
        if normalized.startswith("[") and normalized.endswith("]"):
            normalized = normalized[1:-1]
        normalized = normalized.replace(";", ",").replace(" ", ",")
        result = {
            int(item.strip().strip("\"'"))
            for item in normalized.split(",")
            if item.strip().strip("\"'")
        }
        if not result:
            raise ValueError("ADMIN_IDS must contain at least one Telegram ID")
        return frozenset(result)

    @field_validator("subscription_reminder_days", mode="before")
    @classmethod
    def parse_reminder_days(cls, value: Any) -> tuple[int, ...]:
        if not value:
            return (3, 1)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized.startswith("[") and normalized.endswith("]"):
                normalized = normalized[1:-1]
            values = [
                int(item.strip().strip("\"'"))
                for item in normalized.replace(";", ",").split(",")
                if item.strip()
            ]
        else:
            values = [int(item) for item in value]
        return tuple(sorted({item for item in values if 0 <= item <= 30}, reverse=True))

    @field_validator("payment_success_statuses", "payment_failure_statuses", mode="before")
    @classmethod
    def parse_statuses(cls, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized.startswith("[") and normalized.endswith("]"):
                normalized = normalized[1:-1]
            values = normalized.replace(";", ",").split(",")
        else:
            values = value or ()
        return tuple(
            dict.fromkeys(
                str(item).strip().strip("\"'").lower()
                for item in values
                if str(item).strip().strip("\"'")
            )
        )

    @field_validator("plugin_modules", mode="before")
    @classmethod
    def parse_plugins(cls, value: Any) -> tuple[str, ...]:
        if not value:
            return ()
        if isinstance(value, str):
            normalized = value.strip()
            if normalized.startswith("[") and normalized.endswith("]"):
                normalized = normalized[1:-1]
            return tuple(
                x.strip().strip("\"'")
                for x in normalized.replace(";", ",").split(",")
                if x.strip().strip("\"'")
            )
        return tuple(str(x).strip() for x in value if str(x).strip())

    @field_validator("image_moderation_provider")
    @classmethod
    def validate_image_moderation_provider(cls, value: str) -> str:
        normalized = (value or "auto").strip().lower().replace("-", "_")
        if normalized not in {"disabled", "local", "google_vision", "auto"}:
            raise ValueError(
                "IMAGE_MODERATION_PROVIDER must be disabled, local, google_vision, or auto"
            )
        return normalized

    @field_validator("image_moderation_block_likelihood")
    @classmethod
    def validate_image_moderation_likelihood(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"POSSIBLE", "LIKELY", "VERY_LIKELY"}:
            raise ValueError("IMAGE_MODERATION_BLOCK_LIKELIHOOD must be POSSIBLE, LIKELY, or VERY_LIKELY")
        return normalized

    @field_validator("runtime_mode")
    @classmethod
    def validate_runtime_mode(cls, value: str) -> str:
        normalized = value.strip().lower().replace("_", "-")
        if normalized not in {"combined", "bot", "worker"}:
            raise ValueError("RUNTIME_MODE must be combined, bot, or worker")
        return normalized

    @field_validator("telegram_delivery_mode")
    @classmethod
    def validate_telegram_delivery_mode(cls, value: str) -> str:
        normalized = value.strip().lower().replace("_", "-")
        if normalized not in {"polling", "webhook"}:
            raise ValueError("TELEGRAM_DELIVERY_MODE must be polling or webhook")
        return normalized

    @field_validator("telegram_webhook_path")
    @classmethod
    def validate_telegram_webhook_path(cls, value: str) -> str:
        normalized = "/" + value.strip().strip("/")
        if normalized == "/":
            raise ValueError("TELEGRAM_WEBHOOK_PATH cannot be root")
        if any(part in {".", ".."} for part in normalized.split("/")):
            raise ValueError("TELEGRAM_WEBHOOK_PATH contains an unsafe segment")
        return normalized

    @field_validator("backup_storage_backend")
    @classmethod
    def validate_backup_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"s3", "disabled"}:
            raise ValueError("BACKUP_STORAGE_BACKEND must be s3 or disabled")
        return normalized

    @field_validator("encryption_keyring", mode="before")
    @classmethod
    def parse_encryption_keyring(cls, value: Any) -> tuple[str, ...]:
        if not value:
            return ()
        if isinstance(value, str):
            normalized = value.strip()
            if normalized.startswith("[") and normalized.endswith("]"):
                normalized = normalized[1:-1]
            values = normalized.replace(";", ",").split(",")
        else:
            values = value
        return tuple(
            dict.fromkeys(
                str(item).strip().strip("\"'")
                for item in values
                if str(item).strip().strip("\"'")
            )
        )

    @field_validator("release_id", "git_sha", "previous_release_id")
    @classmethod
    def clean_release_metadata(cls, value: str) -> str:
        return "".join(ch for ch in value.strip() if ch.isalnum() or ch in "-_.")[:120]

    @field_validator("backup_s3_prefix")
    @classmethod
    def clean_backup_prefix(cls, value: str) -> str:
        return value.strip().strip("/") or "campuspass/backups"

    @field_validator("support_username")
    @classmethod
    def clean_username(cls, value: str) -> str:
        return value.strip().lstrip("@")

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        return normalize_async_database_url(value)

    @field_validator("db_ssl_mode")
    @classmethod
    def validate_db_ssl_mode(cls, value: str) -> str:
        normalized = value.strip().lower().replace("_", "-")
        if normalized not in {"disable", "prefer", "require", "verify-full"}:
            raise ValueError("DB_SSL_MODE must be disable, prefer, require, or verify-full")
        return normalized

    @field_validator("db_application_name")
    @classmethod
    def validate_db_application_name(cls, value: str) -> str:
        cleaned = "".join(ch for ch in value.strip() if ch.isalnum() or ch in "-_.")
        if not cleaned:
            raise ValueError("DB_APPLICATION_NAME cannot be empty")
        return cleaned[:63]

    @field_validator("public_base_url")
    @classmethod
    def normalize_public_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("railway_public_domain")
    @classmethod
    def normalize_railway_domain(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator(
        "welcome_text",
        "help_text",
        "support_text",
        "terms_text",
        "privacy_text",
        "default_payment_instructions",
        "gemini_system_prompt",
    )
    @classmethod
    def expand_newlines(cls, value: str) -> str:
        return value.replace("\\n", "\n").strip()

    @field_validator("email_ambiguity_policy")
    @classmethod
    def valid_email_policy(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"review", "latest"}:
            raise ValueError("EMAIL_AMBIGUITY_POLICY must be review or latest")
        return value

    @field_validator(
        "brand_primary_color",
        "brand_secondary_color",
        "brand_dark_color",
        mode="before",
    )
    @classmethod
    def validate_hex_color(cls, value: object, info: ValidationInfo) -> str:
        # Railway bulk/raw imports may strip a leading '#', and may preserve
        # accidental surrounding quotes. Normalize those safe forms only.
        defaults = {
            "brand_primary_color": "#003279",
            "brand_secondary_color": "#14A5A2",
            "brand_dark_color": "#082F63",
        }

        color = "" if value is None else str(value).strip()

        if len(color) >= 2 and color[0] == color[-1] and color[0] in {'"', "'"}:
            color = color[1:-1].strip()

        # An explicitly empty Railway value behaves like an omitted optional
        # branding override and falls back to the existing official default.
        if not color:
            return defaults[info.field_name]

        hex_value = color[1:] if color.startswith("#") else color
        if len(hex_value) != 6:
            raise ValueError("Brand colors must be 6-digit hex values like #0B4AA9")

        try:
            int(hex_value, 16)
        except ValueError as exc:
            raise ValueError("Brand colors must contain only hexadecimal characters") from exc

        return f"#{hex_value.upper()}"

    @field_validator("export_logo_path")
    @classmethod
    def normalize_export_logo_path(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_runtime(self) -> Settings:
        environment = self.environment.lower().strip()
        is_production = environment == "production"
        if ":" not in self.bot_token or len(self.bot_token) < 20:
            raise ValueError("BOT_TOKEN appears invalid")
        if not (1 <= self.port <= 65535):
            raise ValueError("PORT must be between 1 and 65535")
        if not (0 <= self.daily_report_hour <= 23 and 0 <= self.daily_report_minute <= 59):
            raise ValueError("Daily report time is invalid")
        if self.report_token_days < 1 or self.report_token_days > 30:
            raise ValueError("REPORT_TOKEN_DAYS must be between 1 and 30")
        if self.report_max_accesses < 1 or self.report_max_accesses > 1000:
            raise ValueError("REPORT_MAX_ACCESSES must be between 1 and 1000")
        if self.report_snapshot_retention_days < 7 or self.report_snapshot_retention_days > 3650:
            raise ValueError("REPORT_SNAPSHOT_RETENTION_DAYS must be between 7 and 3650")
        if self.payment_webhook_max_body_bytes < 1024:
            raise ValueError("PAYMENT_WEBHOOK_MAX_BODY_BYTES is too small")
        if not (0.0 <= self.sentry_traces_sample_rate <= 1.0):
            raise ValueError("SENTRY_TRACES_SAMPLE_RATE must be between 0 and 1")
        if not (250 <= self.rate_limit_interval_ms <= 60_000):
            raise ValueError("RATE_LIMIT_INTERVAL_MS must be between 250 and 60000")
        if not (500 <= self.duplicate_action_window_ms <= 60_000):
            raise ValueError("DUPLICATE_ACTION_WINDOW_MS must be between 500 and 60000")
        if not (500 <= self.sensitive_action_cooldown_ms <= 60_000):
            raise ValueError("SENSITIVE_ACTION_COOLDOWN_MS must be between 500 and 60000")
        if not (1 <= self.bot_update_concurrency <= 500):
            raise ValueError("BOT_UPDATE_CONCURRENCY must be between 1 and 500")
        if not (10 <= self.telegram_http_connection_limit <= 500):
            raise ValueError("TELEGRAM_HTTP_CONNECTION_LIMIT must be between 10 and 500")
        if not (5.0 <= self.telegram_request_timeout_seconds <= 180.0):
            raise ValueError("TELEGRAM_REQUEST_TIMEOUT_SECONDS must be between 5 and 180")
        if not (1 <= self.telegram_webhook_max_connections <= 100):
            raise ValueError("TELEGRAM_WEBHOOK_MAX_CONNECTIONS must be between 1 and 100")
        if not (4096 <= self.telegram_webhook_body_limit_bytes <= 10_485_760):
            raise ValueError("TELEGRAM_WEBHOOK_BODY_LIMIT_BYTES must be between 4 KiB and 10 MiB")
        if not (1 <= self.telegram_update_consumers <= 64):
            raise ValueError("TELEGRAM_UPDATE_CONSUMERS must be between 1 and 64")
        if not (1 <= self.telegram_update_claim_batch_size <= 64):
            raise ValueError("TELEGRAM_UPDATE_CLAIM_BATCH_SIZE must be between 1 and 64")
        if not (10 <= self.telegram_update_idle_wait_ms <= 5_000):
            raise ValueError("TELEGRAM_UPDATE_IDLE_WAIT_MS must be between 10 and 5000")
        if not (1.0 <= self.telegram_update_graceful_shutdown_seconds <= 120.0):
            raise ValueError(
                "TELEGRAM_UPDATE_GRACEFUL_SHUTDOWN_SECONDS must be between 1 and 120"
            )
        if not (0.25 <= self.cache_generation_poll_seconds <= 300.0):
            raise ValueError("CACHE_GENERATION_POLL_SECONDS must be between 0.25 and 300")
        if not (1 <= self.update_callback_schema_version <= 1000):
            raise ValueError("UPDATE_CALLBACK_SCHEMA_VERSION must be between 1 and 1000")
        if not (1 <= self.update_event_schema_version <= 1000):
            raise ValueError("UPDATE_EVENT_SCHEMA_VERSION must be between 1 and 1000")
        if not (0.0 <= self.update_rollout_percent <= 100.0):
            raise ValueError("UPDATE_ROLLOUT_PERCENT must be between 0 and 100")
        if not (100 <= self.uvicorn_limit_concurrency <= 100_000):
            raise ValueError("UVICORN_LIMIT_CONCURRENCY must be between 100 and 100000")
        if not (128 <= self.uvicorn_backlog <= 65_535):
            raise ValueError("UVICORN_BACKLOG must be between 128 and 65535")
        if not (1 <= self.uvicorn_timeout_keep_alive <= 120):
            raise ValueError("UVICORN_TIMEOUT_KEEP_ALIVE must be between 1 and 120")
        if not (30 <= self.telegram_update_lease_seconds <= 900):
            raise ValueError("TELEGRAM_UPDATE_LEASE_SECONDS must be between 30 and 900")
        if not (1 <= self.telegram_update_max_attempts <= 20):
            raise ValueError("TELEGRAM_UPDATE_MAX_ATTEMPTS must be between 1 and 20")
        if not (1 <= self.telegram_update_retention_days <= 365):
            raise ValueError("TELEGRAM_UPDATE_RETENTION_DAYS must be between 1 and 365")
        if not (0 <= self.deployment_gate_wait_seconds <= 600):
            raise ValueError("DEPLOYMENT_GATE_WAIT_SECONDS must be between 0 and 600")
        for name, value, maximum in (
            ("AI_CONCURRENCY_LIMIT", self.ai_concurrency_limit, 50),
            ("IMAP_CONCURRENCY_LIMIT", self.imap_concurrency_limit, 100),
            ("REPORT_CONCURRENCY_LIMIT", self.report_concurrency_limit, 50),
            ("LONG_OPERATION_CONCURRENCY_LIMIT", self.long_operation_concurrency_limit, 100),
        ):
            if not (1 <= value <= maximum):
                raise ValueError(f"{name} must be between 1 and {maximum}")
        if not (100 <= self.slow_update_warning_ms <= 60_000):
            raise ValueError("SLOW_UPDATE_WARNING_MS must be between 100 and 60000")
        if not (1.0 <= self.banned_user_cache_ttl_seconds <= 3600.0):
            raise ValueError("BANNED_USER_CACHE_TTL_SECONDS must be between 1 and 3600")
        if not (30 <= self.delivery_lease_seconds <= 3600):
            raise ValueError("DELIVERY_LEASE_SECONDS must be between 30 and 3600")
        if not (1 <= self.payment_review_reservation_hours <= 24):
            raise ValueError("PAYMENT_REVIEW_RESERVATION_HOURS must be between 1 and 24")
        if not (1 <= self.max_open_payment_reviews_per_user <= 20):
            raise ValueError("MAX_OPEN_PAYMENT_REVIEWS_PER_USER must be between 1 and 20")
        if not (30 <= self.evidence_retention_days <= 3650):
            raise ValueError("EVIDENCE_RETENTION_DAYS must be between 30 and 3650")
        if not (0 <= self.backup_hour <= 23 and 0 <= self.backup_minute <= 59):
            raise ValueError("Backup time is invalid")
        if not (1 <= self.backup_retention_days <= 365):
            raise ValueError("BACKUP_RETENTION_DAYS must be between 1 and 365")
        if not (1048576 <= self.backup_max_bytes <= 5368709120):
            raise ValueError("BACKUP_MAX_BYTES must be between 1 MiB and 5 GiB")
        if not (60 <= self.scheduler_lease_seconds <= 3600):
            raise ValueError("SCHEDULER_LEASE_SECONDS must be between 60 and 3600")
        if not (7 <= self.scheduled_run_retention_days <= 3650):
            raise ValueError("SCHEDULED_RUN_RETENTION_DAYS must be between 7 and 3650")
        if not (7 <= self.incident_retention_days <= 3650):
            raise ValueError("INCIDENT_RETENTION_DAYS must be between 7 and 3650")
        if not (1 <= self.encryption_key_version <= 1000000):
            raise ValueError("ENCRYPTION_KEY_VERSION must be positive")
        if not (1 <= self.key_rotation_batch_size <= 5000):
            raise ValueError("KEY_ROTATION_BATCH_SIZE must be between 1 and 5000")
        if set(self.payment_success_statuses) & set(self.payment_failure_statuses):
            raise ValueError("Payment success and failure statuses must not overlap")

        if is_production and self.database_url.startswith("sqlite"):
            raise ValueError("Production requires PostgreSQL DATABASE_URL")
        if is_production and self.require_external_database:
            host = database_hostname(self.database_url)
            if not host:
                raise ValueError("DATABASE_URL must include an external PostgreSQL host")
            if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".railway.internal"):
                raise ValueError(
                    "REQUIRE_EXTERNAL_DATABASE=true rejects local/Railway-internal PostgreSQL"
                )
            placeholder_hosts = {"host", "external_host", "example.com", "your-host"}
            lowered_url = self.database_url.lower()
            if host in placeholder_hosts or any(
                marker in lowered_url
                for marker in (
                    "user:password@",
                    "your_user",
                    "your_password",
                    "put_database",
                    "ضع_رابط",
                )
            ):
                raise ValueError("DATABASE_URL still contains an example/placeholder value")
            if "${{" in self.database_url or "}}" in self.database_url:
                raise ValueError("DATABASE_URL still contains a Railway reference placeholder")
        if is_production and self.db_ssl_mode == "disable":
            raise ValueError("Production external PostgreSQL must use SSL")
        if not (1 <= self.db_pool_size <= 50):
            raise ValueError("DB_POOL_SIZE must be between 1 and 50")
        if not (0 <= self.db_max_overflow <= 100):
            raise ValueError("DB_MAX_OVERFLOW must be between 0 and 100")
        if not (1 <= self.db_pool_timeout_seconds <= 300):
            raise ValueError("DB_POOL_TIMEOUT_SECONDS must be between 1 and 300")
        if not (30 <= self.db_pool_recycle_seconds <= 86400):
            raise ValueError("DB_POOL_RECYCLE_SECONDS must be between 30 and 86400")
        if not (1 <= self.db_connect_timeout_seconds <= 120):
            raise ValueError("DB_CONNECT_TIMEOUT_SECONDS must be between 1 and 120")
        if not (1000 <= self.db_statement_timeout_ms <= 600000):
            raise ValueError("DB_STATEMENT_TIMEOUT_MS must be between 1000 and 600000")
        if not (1 <= self.db_startup_retries <= 60):
            raise ValueError("DB_STARTUP_RETRIES must be between 1 and 60")
        if not (0.5 <= self.db_startup_retry_seconds <= 120):
            raise ValueError("DB_STARTUP_RETRY_SECONDS must be between 0.5 and 120")
        if not (0 <= self.db_prepared_statement_cache_size <= 10000):
            raise ValueError("DB_PREPARED_STATEMENT_CACHE_SIZE must be between 0 and 10000")
        if not (5 <= self.email_imap_timeout_seconds <= 120):
            raise ValueError("EMAIL_IMAP_TIMEOUT_SECONDS must be between 5 and 120")
        if not (self.email_imap_timeout_seconds <= self.email_imap_overall_timeout_seconds <= 180):
            raise ValueError(
                "EMAIL_IMAP_OVERALL_TIMEOUT_SECONDS must be >= EMAIL_IMAP_TIMEOUT_SECONDS and <= 180"
            )
        # Render exposes the service URL automatically. Reports still work as
        # Telegram attachments when no public URL is configured.
        if not self.public_base_url and self.render_external_url:
            object.__setattr__(
                self, "public_base_url", self.render_external_url.rstrip("/")
            )
        elif not self.public_base_url and self.render_external_hostname:
            object.__setattr__(
                self,
                "public_base_url",
                f"https://{self.render_external_hostname.strip().strip('/')}"
            )

        # Railway compatibility is retained for existing installations.
        if not self.public_base_url and self.railway_public_domain:
            domain = self.railway_public_domain
            if not domain.startswith(("http://", "https://")):
                domain = f"https://{domain}"
            object.__setattr__(self, "public_base_url", domain.rstrip("/"))

        if is_production:
            encryption_key = self.encryption_key.strip()
            if len(encryption_key) < 32:
                raise ValueError("Production requires ENCRYPTION_KEY of at least 32 chars")
            normalized = encryption_key.lower()
            if any(
                marker in normalized
                for marker in (
                    "change_this",
                    "put_",
                    "replace_",
                    "example",
                    "ضع_",
                    "اكتب_",
                    "هنا",
                )
            ):
                raise ValueError("ENCRYPTION_KEY still contains an example/placeholder value")

            # REPORT_SECRET_KEY is optional: SecretBox derives a stable signing key
            # from ENCRYPTION_KEY when it is absent. API_ADMIN_TOKEN is also
            # optional; web admin endpoints remain locked (401) until it is set.
            for name, value in {
                "REPORT_SECRET_KEY": self.report_secret_key.strip(),
                "API_ADMIN_TOKEN": self.api_admin_token.strip(),
            }.items():
                if not value:
                    continue
                if len(value) < 32:
                    raise ValueError(f"{name} must be at least 32 chars when provided")
                lowered = value.lower()
                if any(
                    marker in lowered
                    for marker in (
                        "change_this",
                        "put_",
                        "replace_",
                        "example",
                        "ضع_",
                        "اكتب_",
                        "هنا",
                    )
                ):
                    raise ValueError(f"{name} still contains an example/placeholder value")

            # A public URL is mandatory only for external card-payment callbacks.
            # Standard/Plus/Pro reports work without a domain and are sent as files.
            if any((
                self.payment_gateway_create_url,
                self.payment_gateway_api_key,
                self.payment_gateway_merchant_id,
                self.payment_webhook_secret,
            )) and not self.public_base_url:
                raise ValueError("PUBLIC_BASE_URL is required when card gateway credentials are configured")
            if self.public_base_url:
                parsed = urlparse(self.public_base_url)
                if parsed.scheme != "https" or not parsed.netloc:
                    raise ValueError("Production PUBLIC_BASE_URL must be an absolute HTTPS URL")
                hostname = (parsed.hostname or "").lower()
                if hostname.endswith(".invalid") or any(
                    marker in hostname for marker in ("replace-me", "your-service")
                ):
                    raise ValueError("PUBLIC_BASE_URL still contains a placeholder hostname")

            if self.runtime_mode in {"combined", "bot"} and self.telegram_delivery_mode == "webhook":
                if not self.public_base_url:
                    raise ValueError("Webhook delivery requires PUBLIC_BASE_URL")
                secret = self.telegram_webhook_secret.strip()
                if not (32 <= len(secret) <= 256):
                    raise ValueError("TELEGRAM_WEBHOOK_SECRET must contain 32-256 characters")
                if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for ch in secret):
                    raise ValueError("TELEGRAM_WEBHOOK_SECRET may contain only A-Z, a-z, 0-9, _ and -")
            if self.runtime_mode in {"combined", "bot"} and self.telegram_delivery_mode == "polling" and self.render_service_id:
                if self.deployment_gate_strict:
                    raise ValueError("Strict Render production requires TELEGRAM_DELIVERY_MODE=webhook")

        # Optional integrations may be enabled before external credentials are
        # provisioned. Operational routes remain closed until readiness is true.
        if is_production and self.require_redis_in_production and not self.redis_url:
            raise ValueError("REQUIRE_REDIS_IN_PRODUCTION=true requires REDIS_URL")
        evidence_values = (
            self.evidence_s3_bucket,
            self.evidence_s3_access_key,
            self.evidence_s3_secret_key,
        )
        if any(evidence_values) and not all(evidence_values):
            raise ValueError("External evidence storage variables are incomplete")
        if self.evidence_s3_endpoint and is_production:
            parsed_evidence = urlparse(self.evidence_s3_endpoint)
            if parsed_evidence.scheme != "https" or not parsed_evidence.netloc:
                raise ValueError("Production EVIDENCE_S3_ENDPOINT must use HTTPS")
        if (
            is_production
            and self.require_external_evidence_storage_in_production
            and not self.evidence_external_storage_ready
        ):
            raise ValueError(
                "REQUIRE_EXTERNAL_EVIDENCE_STORAGE_IN_PRODUCTION=true requires external evidence storage"
            )

        payment_values = [
            self.payment_gateway_create_url,
            self.payment_gateway_api_key,
            self.payment_gateway_merchant_id,
            self.payment_webhook_secret,
        ]
        if any(payment_values) and not all(payment_values):
            raise ValueError("Mastercard gateway variables are incomplete")
        if self.payment_webhook_secret and len(self.payment_webhook_secret) < 32:
            raise ValueError("PAYMENT_WEBHOOK_SECRET must be at least 32 chars")
        if (
            self.payment_gateway_create_url
            and is_production
            and urlparse(self.payment_gateway_create_url).scheme != "https"
        ):
            raise ValueError("Production payment gateway URL must use HTTPS")
        if self.release_id in {"", "manual-release"}:
            if self.render_service_id and self.render_git_commit:
                self.release_id = f"{self.render_service_id}-{self.render_git_commit[:16]}"[:120]
            else:
                render_release = self.render_service_id or self.render_instance_id
                if render_release:
                    self.release_id = render_release[:120]
                elif self.railway_deployment_id:
                    self.release_id = self.railway_deployment_id[:120]
        if not self.git_sha:
            if self.render_git_commit:
                self.git_sha = self.render_git_commit[:120]
            elif self.railway_git_commit_sha:
                self.git_sha = self.railway_git_commit_sha[:120]
        if self.require_pre_deploy_backup and not self.backup_ready:
            raise ValueError(
                "REQUIRE_PRE_DEPLOY_BACKUP requires a fully configured S3 backup connector"
            )
        backup_values = (
            self.backup_s3_bucket,
            self.backup_s3_access_key,
            self.backup_s3_secret_key,
        )
        if any(backup_values) and not all(backup_values):
            raise ValueError("Backup S3 variables are incomplete")
        if self.backup_enabled and self.backup_storage_backend != "s3":
            raise ValueError("BACKUP_ENABLED currently supports BACKUP_STORAGE_BACKEND=s3 only")
        if is_production and self.environment == "production":
            unsafe_release_ids = {
                "",
                "local",
                "manual-release",
                "put_unique_release_id_here",
            }
            if self.release_id.lower() in unsafe_release_ids:
                raise ValueError(
                    "Production requires a stable RELEASE_ID or an automatic Render/Railway release identifier"
                )
        if self.environment == "staging" and self.staging_guard_enabled:
            fingerprint = self.staging_bot_token_fingerprint.strip().lower()
            if not fingerprint or fingerprint == hashlib.sha256(self.bot_token.encode()).hexdigest():
                raise ValueError(
                    "Staging must declare the production bot token fingerprint and use a different BOT_TOKEN"
                )
        return self

    @property
    def gemini_ready(self) -> bool:
        return bool(self.feature_gemini and self.gemini_api_key.strip())

    @property
    def mastercard_ready(self) -> bool:
        return bool(
            self.feature_mastercard
            and self.public_base_url.strip()
            and self.payment_gateway_create_url.strip()
            and self.payment_gateway_api_key.strip()
            and self.payment_gateway_merchant_id.strip()
            and len(self.payment_webhook_secret.strip()) >= 32
        )

    @property
    def provider_withdrawals_ready(self) -> bool:
        return bool(
            self.feature_provider_withdrawals
            and self.money_flow_model == "gateway_marketplace"
            and self.mastercard_ready
        )

    @property
    def backup_ready(self) -> bool:
        return bool(
            self.backup_enabled
            and self.backup_storage_backend == "s3"
            and self.backup_s3_bucket.strip()
            and self.backup_s3_access_key.strip()
            and self.backup_s3_secret_key.strip()
        )

    @property
    def evidence_external_storage_ready(self) -> bool:
        return bool(
            self.evidence_external_storage_enabled
            and self.evidence_s3_bucket.strip()
            and self.evidence_s3_access_key.strip()
            and self.evidence_s3_secret_key.strip()
        )

    @property
    def image_moderation_ready(self) -> bool:
        if not self.image_moderation_enabled:
            return False
        if self.image_moderation_provider in {"local", "auto"}:
            return True
        return bool(
            self.image_moderation_provider == "google_vision"
            and self.google_vision_api_key.strip()
        )

    @property
    def image_moderation_external_ready(self) -> bool:
        return bool(
            self.image_moderation_enabled
            and self.image_moderation_provider in {"google_vision", "auto"}
            and self.google_vision_api_key.strip()
        )

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.admin_ids


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
