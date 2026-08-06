from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    CatalogSection,
    CatalogServiceItem,
    Category,
    FeatureBillingMode,
    FeatureFlag,
    Favorite,
    FavoriteTargetType,
    StudentFavorite,
    FeaturePrice,
    MessageTemplate,
    MenuButtonConfig,
    ModuleRecord,
    Offer,
    OfferCatalogPlacement,
    OfferValidityPolicy,
    OfferWorkflow,
    Order,
    OrderWorkflowState,
    Provider,
    ProviderWorkingHour,
    RuntimeConfigGeneration,
    SchemaMigration,
    SystemSetting,
    ValidityType,
)
from app.services.modules import BUILTIN_MODULES
from app.services.templates import DEFAULT_TEMPLATES
from app.services.workflows import WORKFLOW_VERSION, workflow_for_delivery

MigrationCallable = Callable[[AsyncSession], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    description: str
    apply: MigrationCallable

    @property
    def checksum(self) -> str:
        raw = f"{self.version}:{self.description}".encode()
        return hashlib.sha256(raw).hexdigest()


async def _register_ui_manager(_session: AsyncSession) -> None:
    """V3.2 stores UI surfaces in cp_system_settings, so no ALTER is required."""


async def _backfill_catalog_and_validity(session: AsyncSession) -> None:
    """Create provider-specific browsing hierarchy without changing old rows.

    New tables are created by metadata.create_all before this runner executes.
    Existing offers are linked into provider sections and services so no old
    offer or order needs to be rewritten.
    """
    categories = list(
        (
            await session.scalars(
                select(Category).where(Category.is_active.is_(True)).order_by(Category.sort_order)
            )
        ).all()
    )
    providers = list((await session.scalars(select(Provider))).all())
    for provider in providers:
        sections = list(
            (
                await session.scalars(
                    select(CatalogSection).where(CatalogSection.provider_id == provider.id)
                )
            ).all()
        )
        if not sections:
            for index, category in enumerate(categories):
                session.add(
                    CatalogSection(
                        provider_id=provider.id,
                        name=category.name,
                        emoji=category.emoji,
                        description=category.description,
                        sort_order=index,
                    )
                )
            await session.flush()
        offers = list(
            (
                await session.scalars(
                    select(Offer)
                    .options(selectinload(Offer.category))
                    .where(Offer.provider_id == provider.id)
                )
            ).all()
        )
        for offer in offers:
            if not await session.scalar(
                select(OfferValidityPolicy.id).where(OfferValidityPolicy.offer_id == offer.id)
            ):
                session.add(
                    OfferValidityPolicy(
                        offer_id=offer.id,
                        validity_type=ValidityType.DAYS_FROM_ACTIVATION.value,
                        duration_value=offer.duration_days or 30,
                    )
                )
            if await session.scalar(
                select(OfferCatalogPlacement.id).where(OfferCatalogPlacement.offer_id == offer.id)
            ):
                continue
            category_name = offer.category.name if offer.category else "عروض أخرى"
            section = await session.scalar(
                select(CatalogSection).where(
                    CatalogSection.provider_id == provider.id,
                    CatalogSection.name == category_name,
                )
            )
            if not section:
                section = CatalogSection(
                    provider_id=provider.id,
                    name=category_name,
                    emoji=offer.category.emoji if offer.category else "🛍",
                    sort_order=999,
                )
                session.add(section)
                await session.flush()
            service = await session.scalar(
                select(CatalogServiceItem).where(
                    CatalogServiceItem.section_id == section.id,
                    CatalogServiceItem.name == offer.title,
                )
            )
            if not service:
                service = CatalogServiceItem(
                    provider_id=provider.id,
                    section_id=section.id,
                    name=offer.title,
                    description=offer.description,
                )
                session.add(service)
                await session.flush()
            session.add(
                OfferCatalogPlacement(
                    offer_id=offer.id,
                    provider_id=provider.id,
                    section_id=section.id,
                    service_id=service.id,
                )
            )
    await session.flush()


async def _v4_platform_foundation(session: AsyncSession) -> None:
    """Backfill the V4 module registry, editable templates, and order workflows."""
    from app import __version__

    for module in BUILTIN_MODULES:
        row = await session.scalar(
            select(ModuleRecord).where(ModuleRecord.module_key == module.key)
        )
        if not row:
            session.add(
                ModuleRecord(
                    module_key=module.key,
                    name_ar=module.name_ar,
                    version=__version__,
                    is_critical=module.critical,
                    health_status="unknown",
                )
            )

    for key, (title, body, variables) in DEFAULT_TEMPLATES.items():
        row = await session.scalar(
            select(MessageTemplate).where(
                MessageTemplate.template_key == key,
                MessageTemplate.locale == "ar",
            )
        )
        if not row:
            session.add(
                MessageTemplate(
                    template_key=key,
                    locale="ar",
                    title=title,
                    body=body,
                    variables=variables,
                )
            )

    offers = list((await session.scalars(select(Offer))).all())
    for offer in offers:
        workflow = await session.scalar(
            select(OfferWorkflow).where(OfferWorkflow.offer_id == offer.id)
        )
        if not workflow:
            definition = workflow_for_delivery(offer.delivery_type)
            session.add(
                OfferWorkflow(
                    offer_id=offer.id,
                    workflow_key=definition.key,
                    version=WORKFLOW_VERSION,
                    steps=definition.steps,
                    allowed_transitions=definition.transitions,
                )
            )
    await session.flush()

    orders = list((await session.scalars(select(Order))).all())
    for order in orders:
        state = await session.scalar(
            select(OrderWorkflowState).where(OrderWorkflowState.order_id == order.id)
        )
        if state:
            continue
        offer = await session.get(Offer, order.offer_id)
        if not offer:
            continue
        workflow = await session.scalar(
            select(OfferWorkflow).where(OfferWorkflow.offer_id == offer.id)
        )
        if not workflow:
            continue
        current_step = "exception"
        for step in workflow.steps:
            if step.get("status") == order.status:
                current_step = str(step.get("key") or "")
                break
        session.add(
            OrderWorkflowState(
                order_id=order.id,
                workflow_key=workflow.workflow_key,
                workflow_version=workflow.version,
                current_status=order.status,
                current_step_key=current_step,
            )
        )
    await session.flush()


async def _v4_1_hardening(_session: AsyncSession) -> None:
    """Register the V4.1 security and reliability schema.

    New webhook and report-access tables are created by metadata.create_all before
    this migration runner executes, so no destructive ALTER is required.
    """


async def _v5_radical_update(session: AsyncSession) -> None:
    """Register V5 owner-controlled prices and feature billing defaults.

    All V5 tables are additive and are created by ``metadata.create_all`` before
    this runner executes.  This migration only inserts editable database rows;
    it never rewrites historical orders, payments, inventory, or subscriptions.
    """

    default_prices = {
        "price.service_fee_iqd": "500",
        "price.report_standard_monthly": "0",
        "price.report_plus_monthly": "0",
        "price.report_pro_monthly": "0",
        "price.report_standard_yearly": "0",
        "price.report_plus_yearly": "0",
        "price.report_pro_yearly": "0",
        "price.email_codes_monthly": "0",
        "price.menu_builder_monthly": "0",
        "price.announcements_monthly": "0",
        "minimum_offer_price_iqd": "1000",
    }
    existing_settings = {
        key
        for key in (
            await session.scalars(
                select(SystemSetting.key).where(SystemSetting.key.in_(default_prices))
            )
        ).all()
    }
    for key, value in default_prices.items():
        if key not in existing_settings:
            session.add(SystemSetting(key=key, value=value))

    feature_names = {
        "reports.standard": "التقارير الاعتيادية",
        "reports.plus": "تقارير Plus",
        "reports.pro": "تقارير Pro",
        "email_codes": "جلب رموز البريد",
        "menu_builder": "منشئ القوائم",
        "announcements": "الإعلانات والتحديثات",
        "extra_staff": "الموظفون الإضافيون",
        "advanced_exports": "التصدير المتقدم",
    }
    existing_features = {
        key
        for key in (
            await session.scalars(
                select(FeaturePrice.feature_key).where(
                    FeaturePrice.feature_key.in_(feature_names)
                )
            )
        ).all()
    }
    for key, name in feature_names.items():
        if key not in existing_features:
            session.add(
                FeaturePrice(
                    feature_key=key,
                    name_ar=name,
                    billing_mode=FeatureBillingMode.FREE.value,
                    is_enabled=True,
                )
            )
    await session.flush()


async def _v5_0_5_user_security(session: AsyncSession) -> None:
    """Add reversible user bans and an owner-controlled profile edit limit.

    Column existence is inspected before ALTER so this migration works on both
    PostgreSQL production and the SQLite test/recovery database. SQLite does not
    support ``ADD COLUMN IF NOT EXISTS`` on all deployed versions.
    """
    connection = await session.connection()
    columns = await connection.run_sync(
        lambda sync_connection: {
            column["name"]
            for column in inspect(sync_connection).get_columns("cp_users")
        }
    )
    additions = (
        ("is_banned", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("ban_reason", "VARCHAR(500) NOT NULL DEFAULT ''"),
        ("banned_at", "TIMESTAMP NULL"),
        ("banned_by_telegram_id", "BIGINT NULL"),
    )
    for column_name, definition in additions:
        if column_name in columns:
            continue
        await session.execute(
            text(f"ALTER TABLE cp_users ADD COLUMN {column_name} {definition}")
        )
        columns.add(column_name)

    await session.execute(
        text("CREATE INDEX IF NOT EXISTS ix_cp_users_is_banned ON cp_users (is_banned)")
    )
    if not await session.scalar(
        select(SystemSetting.id).where(SystemSetting.key == "profile_edit_limit")
    ):
        session.add(SystemSetting(key="profile_edit_limit", value="3"))
    await session.flush()


async def _v6_5_commercial_hardening_phase1(session: AsyncSession) -> None:
    """Add the Phase 1 security, idempotency, and outbox columns safely.

    The project still uses an additive migration runner, so every ALTER is
    guarded by schema inspection and works with PostgreSQL and SQLite recovery
    databases. Existing finance rows are never deleted or rewritten.
    """

    connection = await session.connection()

    async def columns(table: str) -> set[str]:
        return await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns(table)
            }
        )

    async def add_columns(table: str, additions: tuple[tuple[str, str], ...]) -> None:
        known = await columns(table)
        for column_name, definition in additions:
            if column_name in known:
                continue
            await session.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column_name} {definition}")
            )
            known.add(column_name)

    await add_columns(
        "cp_provider_staff",
        (
            ("can_view_finance", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("can_request_withdrawal", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("can_manage_payout_accounts", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("can_view_pii", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("can_export_data", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ),
    )
    # Preserve owner usability without granting paid entitlements or withdrawals.
    await session.execute(
        text(
            "UPDATE cp_provider_staff SET "
            "can_view_finance = TRUE, can_view_pii = TRUE, can_export_data = TRUE "
            "WHERE LOWER(title) = 'owner'"
        )
    )

    await add_columns(
        "cp_disputes",
        (("sla_breached_at", "TIMESTAMP NULL"),),
    )
    await add_columns(
        "cp_refunds",
        (
            ("transfer_reference_fingerprint", "VARCHAR(64) NULL"),
            ("transfer_reported_by_user_id", "INTEGER NULL REFERENCES cp_users(id)"),
        ),
    )
    await add_columns(
        "cp_orders",
        (
            ("idempotency_key", "VARCHAR(160) NULL"),
            ("payment_snapshot", "JSON NOT NULL DEFAULT '{}'"),
        ),
    )
    await add_columns(
        "cp_payment_proofs",
        (("reference_fingerprint", "VARCHAR(64) NULL"),),
    )
    await add_columns(
        "cp_points_transactions",
        (("idempotency_key", "VARCHAR(160) NULL"),),
    )
    await add_columns(
        "cp_ledger_entries",
        (("idempotency_key", "VARCHAR(160) NULL"),),
    )
    await add_columns(
        "cp_support_tickets",
        (
            ("closed_at", "TIMESTAMP NULL"),
            ("closed_by_user_id", "INTEGER NULL"),
            ("close_reason", "VARCHAR(500) NOT NULL DEFAULT ''"),
        ),
    )
    await add_columns(
        "cp_notifications",
        (
            ("idempotency_key", "VARCHAR(160) NULL"),
            ("delivery_status", "VARCHAR(20) NOT NULL DEFAULT 'sent'"),
            ("attempts", "INTEGER NOT NULL DEFAULT 0"),
            ("last_error", "TEXT NULL"),
            ("sent_at", "TIMESTAMP NULL"),
            ("telegram_message_id", "BIGINT NULL"),
        ),
    )
    await add_columns(
        "cp_delivery_jobs",
        (
            ("lease_owner", "VARCHAR(120) NULL"),
            ("lease_expires_at", "TIMESTAMP NULL"),
            ("started_at", "TIMESTAMP NULL"),
        ),
    )

    # Nullable idempotency values make these safe for all historical rows.
    for statement in (
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_cp_orders_idempotency_key "
        "ON cp_orders (idempotency_key)",
        "CREATE INDEX IF NOT EXISTS ix_cp_payment_proofs_reference_fingerprint "
        "ON cp_payment_proofs (reference_fingerprint)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_cp_points_idempotency_key "
        "ON cp_points_transactions (idempotency_key)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_cp_ledger_idempotency_key "
        "ON cp_ledger_entries (idempotency_key)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_cp_notifications_idempotency_key "
        "ON cp_notifications (idempotency_key)",
        "CREATE INDEX IF NOT EXISTS ix_cp_delivery_jobs_lease_expires "
        "ON cp_delivery_jobs (lease_expires_at)",
        "CREATE INDEX IF NOT EXISTS ix_cp_notifications_delivery_status "
        "ON cp_notifications (delivery_status)",
    ):
        await session.execute(text(statement))

    await session.flush()


async def _v6_6_disputes_refunds_phase2(session: AsyncSession) -> None:
    """Add dispute/refund lifecycle and exposed-inventory remediation.

    New dispute tables are additive and created by metadata.create_all. These
    ALTER statements preserve existing deployments that already have Phase 1
    tables without deleting or rewriting historical orders.
    """
    connection = await session.connection()

    async def columns(table: str) -> set[str]:
        return await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns(table)
            }
        )

    async def add_columns(table: str, additions: tuple[tuple[str, str], ...]) -> None:
        known = await columns(table)
        for column_name, definition in additions:
            if column_name in known:
                continue
            await session.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column_name} {definition}")
            )
            known.add(column_name)

    await add_columns(
        "cp_provider_staff",
        (
            ("can_manage_disputes", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("can_approve_refunds", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ),
    )
    await session.execute(
        text(
            "UPDATE cp_provider_staff SET "
            "can_manage_disputes = TRUE, can_approve_refunds = TRUE "
            "WHERE LOWER(title) = 'owner'"
        )
    )
    await add_columns(
        "cp_disputes",
        (("sla_breached_at", "TIMESTAMP NULL"),),
    )
    await add_columns(
        "cp_refunds",
        (("transfer_reference_fingerprint", "VARCHAR(64) NULL"),),
    )
    await add_columns(
        "cp_orders",
        (
            ("disputed_at", "TIMESTAMP NULL"),
            ("refunded_at", "TIMESTAMP NULL"),
            ("refund_total_iqd", "INTEGER NOT NULL DEFAULT 0"),
        ),
    )
    await add_columns(
        "cp_payments",
        (
            ("refunded_amount_iqd", "INTEGER NOT NULL DEFAULT 0"),
            ("last_refunded_at", "TIMESTAMP NULL"),
        ),
    )
    await add_columns(
        "cp_inventory_items",
        (
            ("compromised_at", "TIMESTAMP NULL"),
            ("remediation_note", "VARCHAR(500) NOT NULL DEFAULT ''"),
        ),
    )
    await add_columns(
        "cp_student_subscriptions",
        (
            ("paused_at", "TIMESTAMP NULL"),
            ("cancelled_at", "TIMESTAMP NULL"),
            ("refunded_at", "TIMESTAMP NULL"),
            ("pre_dispute_status", "VARCHAR(32) NULL"),
            ("pre_dispute_ends_at", "TIMESTAMP NULL"),
        ),
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_cp_orders_disputed_at ON cp_orders (disputed_at)",
        "CREATE INDEX IF NOT EXISTS ix_cp_orders_refunded_at ON cp_orders (refunded_at)",
        "CREATE INDEX IF NOT EXISTS ix_cp_payments_last_refunded_at "
        "ON cp_payments (last_refunded_at)",
        "CREATE INDEX IF NOT EXISTS ix_cp_inventory_compromised_at "
        "ON cp_inventory_items (compromised_at)",
        "CREATE INDEX IF NOT EXISTS ix_cp_student_subscriptions_paused_at "
        "ON cp_student_subscriptions (paused_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_cp_disputes_order_id "
        "ON cp_disputes (order_id)",
        "CREATE INDEX IF NOT EXISTS ix_cp_disputes_sla_breached_at "
        "ON cp_disputes (sla_breached_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_cp_refunds_transfer_fingerprint "
        "ON cp_refunds (transfer_reference_fingerprint) "
        "WHERE transfer_reference_fingerprint IS NOT NULL",
    ):
        await session.execute(text(statement))
    await session.flush()


async def _v6_7_privacy_evidence_phase3(session: AsyncSession) -> None:
    """Add encrypted PII fields, privacy requests and evidence references.

    New tables are created by metadata.create_all. Existing tables receive only
    additive nullable/defaulted columns so older Railway databases remain usable.
    """
    connection = await session.connection()

    async def columns(table: str) -> set[str]:
        return await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns(table)
            }
        )

    async def add_columns(table: str, additions: tuple[tuple[str, str], ...]) -> None:
        known = await columns(table)
        for column_name, definition in additions:
            if column_name in known:
                continue
            await session.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column_name} {definition}")
            )
            known.add(column_name)

    await add_columns(
        "cp_users",
        (
            ("privacy_policy_version", "VARCHAR(20) NOT NULL DEFAULT '1.0'"),
            ("privacy_accepted_at", "TIMESTAMP NULL"),
            ("ai_data_consent_at", "TIMESTAMP NULL"),
            ("deletion_anonymized_at", "TIMESTAMP NULL"),
        ),
    )
    await add_columns(
        "cp_student_profiles",
        (
            ("private_data_encrypted", "TEXT NULL"),
            ("private_data_key_version", "INTEGER NOT NULL DEFAULT 1"),
            ("pii_protected_at", "TIMESTAMP NULL"),
        ),
    )
    await add_columns(
        "cp_orders",
        (
            ("activation_data_encrypted", "TEXT NULL"),
            ("activation_data_key_version", "INTEGER NOT NULL DEFAULT 1"),
            ("activation_data_protected_at", "TIMESTAMP NULL"),
        ),
    )
    await add_columns(
        "cp_payment_proofs",
        (("evidence_asset_id", "INTEGER NULL"),),
    )
    await add_columns(
        "cp_ticket_messages",
        (("evidence_asset_id", "INTEGER NULL"),),
    )
    await add_columns(
        "cp_disputes",
        (("evidence_asset_id", "INTEGER NULL"),),
    )
    await add_columns(
        "cp_refunds",
        (("proof_evidence_asset_id", "INTEGER NULL"),),
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_cp_users_deletion_anonymized_at ON cp_users (deletion_anonymized_at)",
        "CREATE INDEX IF NOT EXISTS ix_cp_profiles_pii_protected_at ON cp_student_profiles (pii_protected_at)",
        "CREATE INDEX IF NOT EXISTS ix_cp_orders_activation_protected_at ON cp_orders (activation_data_protected_at)",
        "CREATE INDEX IF NOT EXISTS ix_cp_payment_proofs_evidence_asset_id ON cp_payment_proofs (evidence_asset_id)",
        "CREATE INDEX IF NOT EXISTS ix_cp_ticket_messages_evidence_asset_id ON cp_ticket_messages (evidence_asset_id)",
        "CREATE INDEX IF NOT EXISTS ix_cp_disputes_evidence_asset_id ON cp_disputes (evidence_asset_id)",
        "CREATE INDEX IF NOT EXISTS ix_cp_refunds_proof_evidence_asset_id ON cp_refunds (proof_evidence_asset_id)",
    ):
        await session.execute(text(statement))
    await session.flush()


async def _v6_8_user_experience_phase4(session: AsyncSession) -> None:
    """Add explicit delivery acknowledgement and activation confirmation timestamps.

    Phase 4 keeps the existing order status machine stable and adds timestamps
    instead of introducing ambiguous statuses. Existing delivered/completed rows
    remain valid and are backfilled conservatively.
    """
    connection = await session.connection()
    known = await connection.run_sync(
        lambda sync_connection: {
            column["name"]
            for column in inspect(sync_connection).get_columns("cp_orders")
        }
    )
    additions = (
        ("delivery_acknowledged_at", "TIMESTAMP NULL"),
        ("activation_confirmed_at", "TIMESTAMP NULL"),
    )
    for column_name, definition in additions:
        if column_name not in known:
            await session.execute(
                text(f"ALTER TABLE cp_orders ADD COLUMN {column_name} {definition}")
            )
            known.add(column_name)
    await session.execute(
        text(
            "UPDATE cp_orders SET delivery_acknowledged_at = COALESCE(delivery_acknowledged_at, completed_at, updated_at) "
            "WHERE status = 'completed'"
        )
    )
    await session.execute(
        text(
            "UPDATE cp_orders SET activation_confirmed_at = COALESCE(activation_confirmed_at, completed_at, updated_at) "
            "WHERE status = 'completed'"
        )
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_cp_orders_delivery_acknowledged_at "
            "ON cp_orders (delivery_acknowledged_at)"
        )
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_cp_orders_activation_confirmed_at "
            "ON cp_orders (activation_confirmed_at)"
        )
    )
    await session.flush()


async def _v6_9_operations_reliability_phase5(session: AsyncSession) -> None:
    """Register additive operations tables and persistent runtime defaults."""
    defaults = {
        "operations.runtime_mode": "combined",
        "operations.backup_enabled": "false",
        "operations.key_version": "1",
        "operations.release_version": "6.9.0-operations-reliability-phase5",
    }
    for key, value in defaults.items():
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row is None:
            session.add(SystemSetting(key=key, value=value, is_secret=False))
    await session.flush()


async def _v7_0_pilot_quality_phase6(session: AsyncSession) -> None:
    """Register pilot validation defaults without changing existing commercial data."""
    defaults = {
        "pilot.enabled": "false",
        "pilot.strict_startup": "false",
        "pilot.release_version": "7.0.0-pilot-quality-phase6",
        "pilot.last_validation_status": "not_run",
    }
    for key, value in defaults.items():
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row is None:
            session.add(SystemSetting(key=key, value=value, is_secret=False))
    await session.flush()



async def _v8_0a_enterprise_core(session: AsyncSession) -> None:
    """Seed commercial plans and enterprise defaults; all tables are metadata-created."""
    from app.db.models import BusinessPlan
    plans = (
        ("basic", "Basic", 15000, 2, 1000, 1000, {"reports": True}),
        ("pro", "Pro", 35000, 5, 10000, 700, {"reports": True, "api": True, "webhooks": True}),
        ("enterprise", "Enterprise", 75000, 20, 100000, 400, {"reports": True, "api": True, "webhooks": True, "teams": True}),
    )
    for order, (code, name, price, seats, requests, commission, features) in enumerate(plans):
        if not await session.scalar(select(BusinessPlan.id).where(BusinessPlan.code == code)):
            session.add(BusinessPlan(code=code, name=name, monthly_price_iqd=price,
                included_team_members=seats, included_api_requests=requests,
                commission_bps=commission, features_json=features, sort_order=order))
    defaults = {
        "enterprise.enabled": "true",
        "enterprise.release_version": "8.0.0-enterprise-core-a",
        "enterprise.billing_currency": "IQD",
        "enterprise.ledger_mode": "double_entry",
    }
    for key, value in defaults.items():
        if not await session.scalar(select(SystemSetting.id).where(SystemSetting.key == key)):
            session.add(SystemSetting(key=key, value=value, is_secret=False))
    await session.flush()



async def _v8_0b_enterprise_scale(session: AsyncSession) -> None:
    defaults = {
        "enterprise.scale_enabled": "true",
        "enterprise.release_version": "8.0.0-enterprise-scale-b",
        "enterprise.queue_mode": "database_leases",
        "enterprise.webhook_signing": "hmac_sha256",
        "enterprise.usage_metering": "monthly",
    }
    for key, value in defaults.items():
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row:
            row.value = value
        else:
            session.add(SystemSetting(key=key, value=value, is_secret=False))
    await session.flush()


async def _v8_1_ux_wallet_settlement(session: AsyncSession) -> None:
    """Add the simplified account menu and parent mappings without deleting old actions."""
    account = await session.scalar(select(MenuButtonConfig).where(MenuButtonConfig.key == "account"))
    if not account:
        session.add(
            MenuButtonConfig(
                key="account",
                text="👤 حسابي",
                action="account",
                style="success",
                row_number=1,
                position=2,
                role_scope=["user", "provider", "admin"],
                is_enabled=True,
            )
        )
    profile = await session.scalar(select(MenuButtonConfig).where(MenuButtonConfig.key == "profile"))
    if profile and profile.text == "👤 معلوماتي":
        profile.text = "🪪 معلوماتي"
    gemini_flag = await session.scalar(select(FeatureFlag).where(FeatureFlag.key == "gemini"))
    if gemini_flag:
        gemini_flag.is_enabled = True
    child_keys = ["profile", "orders", "subscriptions", "favorites", "points", "privacy"]
    for index, key in enumerate(child_keys, start=1):
        parent_key = f"menu.parent.{key}"
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == parent_key))
        if row:
            row.value = "account"
        else:
            session.add(SystemSetting(key=parent_key, value="account"))
        surface_key = f"menu.surface.{key}"
        surface = await session.scalar(select(SystemSetting).where(SystemSetting.key == surface_key))
        if surface:
            surface.value = "reply"
        else:
            session.add(SystemSetting(key=surface_key, value="reply"))
        button = await session.scalar(select(MenuButtonConfig).where(MenuButtonConfig.key == key))
        if button:
            button.row_number = (index + 1) // 2
            button.position = 1 if index % 2 else 2
    await session.flush()


async def _v9_0_lts_freeze(session: AsyncSession) -> None:
    """Finalize the simplified account UI without deleting privacy/security logic."""
    privacy = await session.scalar(select(MenuButtonConfig).where(MenuButtonConfig.key == "privacy"))
    if privacy:
        privacy.is_enabled = False

    wallet = await session.scalar(select(MenuButtonConfig).where(MenuButtonConfig.key == "wallet"))
    if not wallet:
        wallet = MenuButtonConfig(
            key="wallet",
            text="💰 محفظتي",
            action="wallet",
            style="success",
            row_number=1,
            position=2,
            role_scope=["user", "provider", "admin"],
            is_enabled=True,
        )
        session.add(wallet)
    else:
        wallet.text = "💰 محفظتي"
        wallet.action = "wallet"
        wallet.is_enabled = True

    parent_key = "menu.parent.wallet"
    parent = await session.scalar(select(SystemSetting).where(SystemSetting.key == parent_key))
    if parent:
        parent.value = "account"
    else:
        session.add(SystemSetting(key=parent_key, value="account"))
    surface_key = "menu.surface.wallet"
    surface = await session.scalar(select(SystemSetting).where(SystemSetting.key == surface_key))
    if surface:
        surface.value = "reply"
    else:
        session.add(SystemSetting(key=surface_key, value="reply"))

    # Keep the account page compact: profile + wallet, then orders/subscriptions,
    # favorites/points. Privacy functions remain reachable through explicit flows
    # and are not deleted from the codebase.
    layout = {
        "profile": (1, 1),
        "wallet": (1, 2),
        "orders": (2, 1),
        "subscriptions": (2, 2),
        "favorites": (3, 1),
        "points": (3, 2),
    }
    for key, (row_number, position) in layout.items():
        button = await session.scalar(select(MenuButtonConfig).where(MenuButtonConfig.key == key))
        if button:
            button.row_number = row_number
            button.position = position
            parent_setting = await session.scalar(
                select(SystemSetting).where(SystemSetting.key == f"menu.parent.{key}")
            )
            if parent_setting:
                parent_setting.value = "account"
            else:
                session.add(SystemSetting(key=f"menu.parent.{key}", value="account"))
    await session.flush()



async def _v10_2_callback_ui_inventory(_session: AsyncSession) -> None:
    """Register the callback/UI/inventory release.

    Metadata.create_all creates cp_runtime_leases before this additive runner. Existing business
    rows are intentionally untouched; compact callback tokens resolve current numeric IDs and
    still accept legacy key-based callbacks from messages sent before deployment.
    """


async def _v10_3_offer_lifecycle_security(session: AsyncSession) -> None:
    """Register safe defaults for lifecycle automation and logo moderation."""
    defaults = {
        "offers.lifecycle.enabled": "true",
        "offers.lifecycle.interval_seconds": "60",
        "branding.moderation.provider": "google_vision",
        "branding.moderation.fail_closed": "true",
        "operations.release_version": "10.3.0-offer-lifecycle-security",
    }
    for key, value in defaults.items():
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row is None:
            session.add(SystemSetting(key=key, value=value, is_secret=False))
        else:
            row.value = value
    await session.flush()


async def _v10_4_commerce_referral_payments(session: AsyncSession) -> None:
    """Add targeted student coupons and auditable custom-service replies.

    New entitlement and wallet structures are created by metadata.create_all.
    Only additive columns are applied to existing Railway databases.
    """

    async def columns(table: str) -> set[str]:
        connection = await session.connection()
        return await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns(table)
            }
        )

    async def add_columns(table: str, additions: tuple[tuple[str, str], ...]) -> None:
        known = await columns(table)
        for column_name, definition in additions:
            if column_name in known:
                continue
            await session.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column_name} {definition}")
            )
            known.add(column_name)

    await add_columns(
        "cp_order_coupons",
        (("target_user_id", "INTEGER NULL"),),
    )
    await add_columns(
        "cp_missing_service_requests",
        (
            ("response_text", "TEXT NOT NULL DEFAULT ''"),
            ("responded_by_user_id", "INTEGER NULL"),
            ("responded_at", "TIMESTAMP WITH TIME ZONE NULL"),
        ),
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_cp_order_coupons_target_user_id "
            "ON cp_order_coupons (target_user_id)"
        )
    )
    defaults = {
        "referrals.reward_points": "10",
        "referrals.wallet_reward_iqd": "500",
        "payments.proof_max_bytes": "15000000",
        "operations.release_version": "10.4.0-commerce-referral-payments",
    }
    for key, value in defaults.items():
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row is None:
            session.add(SystemSetting(key=key, value=value, is_secret=False))
        else:
            row.value = value
    await session.flush()


async def _v10_5_final_hardening(session: AsyncSession) -> None:
    """Add lifecycle indexes and final operational defaults without rewriting data."""

    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_cp_provider_active_status "
            "ON cp_providers (is_active, status, name_ar)"
        )
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_cp_offer_lifecycle "
            "ON cp_offers (status, is_active, end_at)"
        )
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_cp_inventory_lifecycle "
            "ON cp_inventory_items (status, expires_at, offer_id)"
        )
    )
    defaults = {
        "offers.lifecycle.enabled": "true",
        "offers.lifecycle.interval_seconds": "60",
        "operations.release_version": "10.5.0-final-hardening",
    }
    for key, value in defaults.items():
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row is None:
            session.add(SystemSetting(key=key, value=value, is_secret=False))
        else:
            row.value = value
    await session.flush()


async def _v10_6_platform_access_referral_cleanup(session: AsyncSession) -> None:
    """Add the platform TOS gate and finalize referral/privacy UI behavior."""

    connection = await session.connection()
    user_columns = await connection.run_sync(
        lambda sync_connection: {
            column["name"]
            for column in inspect(sync_connection).get_columns("cp_users")
        }
    )
    if "has_platform_access" not in user_columns:
        await session.execute(
            text(
                "ALTER TABLE cp_users ADD COLUMN "
                "has_platform_access BOOLEAN NOT NULL DEFAULT false"
            )
        )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_cp_users_has_platform_access "
            "ON cp_users (has_platform_access)"
        )
    )

    privacy_button = await session.scalar(
        select(MenuButtonConfig).where(MenuButtonConfig.key == "privacy")
    )
    if privacy_button is not None:
        privacy_button.is_enabled = False

    defaults = {
        "referrals.invites_per_coupon": "3",
        "referrals.reward_mode": "single_use_fee_waiver_coupon",
        "referrals.wallet_reward_iqd": "0",
        "branding.moderation.provider": "disabled",
        "operations.release_version": "10.6.0-platform-access-referral-cleanup",
    }
    for key, value in defaults.items():
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row is None:
            session.add(SystemSetting(key=key, value=value, is_secret=False))
        else:
            row.value = value
    await session.flush()


async def _v10_7_emergency_stabilization(session: AsyncSession) -> None:
    """Add typed provider roles, branding permission and safe access indexes.

    This mirrors the Alembic 1070 migration for deployments that use the
    project's built-in additive migration runner. Existing staff, providers,
    users, offers and orders are never deleted or recreated. Ambiguous legacy
    ownership is reported rather than guessed.
    """

    connection = await session.connection()
    tables = await connection.run_sync(
        lambda sync_connection: set(inspect(sync_connection).get_table_names())
    )
    if "cp_provider_staff" in tables:
        columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns("cp_provider_staff")
            }
        )
        if "role" not in columns:
            await session.execute(
                text(
                    "ALTER TABLE cp_provider_staff ADD COLUMN "
                    "role VARCHAR(20) NOT NULL DEFAULT 'STAFF'"
                )
            )
            columns.add("role")
        if "can_manage_branding" not in columns:
            await session.execute(
                text(
                    "ALTER TABLE cp_provider_staff ADD COLUMN "
                    "can_manage_branding BOOLEAN NOT NULL DEFAULT FALSE"
                )
            )
            columns.add("can_manage_branding")

        # Only explicit historic titles are normalized. Broad legacy booleans
        # are intentionally not treated as ownership evidence.
        await session.execute(
            text(
                "UPDATE cp_provider_staff SET role = 'OWNER' "
                "WHERE LOWER(TRIM(title)) IN "
                "('owner','platform_owner','provider_owner','مالك')"
            )
        )
        await session.execute(
            text(
                "UPDATE cp_provider_staff SET role = 'MANAGER' "
                "WHERE role <> 'OWNER' AND LOWER(TRIM(title)) IN "
                "('manager','admin','administrator','مدير')"
            )
        )
        await session.execute(
            text(
                "UPDATE cp_provider_staff SET can_manage_branding = TRUE "
                "WHERE role = 'OWNER'"
            )
        )
        for statement in (
            "CREATE INDEX IF NOT EXISTS ix_cp_provider_staff_role "
            "ON cp_provider_staff (role)",
            "CREATE INDEX IF NOT EXISTS ix_cp_provider_staff_user_active "
            "ON cp_provider_staff (user_id, is_active)",
            "CREATE INDEX IF NOT EXISTS ix_cp_provider_staff_provider_active "
            "ON cp_provider_staff (provider_id, is_active)",
        ):
            await session.execute(text(statement))

    duplicate_owner_groups = 0
    inactive_owner_rows = 0
    orphan_staff_rows = 0
    if "cp_provider_staff" in tables:
        duplicate_owner_groups = int(
            (
                await session.scalar(
                    text(
                        "SELECT COUNT(*) FROM ("
                        "SELECT provider_id FROM cp_provider_staff WHERE role = 'OWNER' "
                        "GROUP BY provider_id HAVING COUNT(*) > 1"
                        ") AS ambiguous_owner_groups"
                    )
                )
            )
            or 0
        )
        inactive_owner_rows = int(
            (
                await session.scalar(
                    text(
                        "SELECT COUNT(*) FROM cp_provider_staff "
                        "WHERE role = 'OWNER' AND is_active = FALSE"
                    )
                )
            )
            or 0
        )
        if {"cp_users", "cp_providers"}.issubset(tables):
            orphan_staff_rows = int(
                (
                    await session.scalar(
                        text(
                            "SELECT COUNT(*) FROM cp_provider_staff s "
                            "LEFT JOIN cp_users u ON u.id = s.user_id "
                            "LEFT JOIN cp_providers p ON p.id = s.provider_id "
                            "WHERE u.id IS NULL OR p.id IS NULL"
                        )
                    )
                )
                or 0
            )

    defaults = {
        "provider_access.backfill_report": json.dumps(
            {
                "duplicate_owner_provider_groups": duplicate_owner_groups,
                "inactive_owner_rows": inactive_owner_rows,
                "orphan_staff_rows": orphan_staff_rows,
                "note": "Ambiguous rows were reported and not reassigned automatically.",
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        "branding.moderation.provider": "disabled",
        "branding.moderation.fail_closed": "false",
        "operations.release_version": "10.7.0-emergency-stabilization",
    }
    for key, value in defaults.items():
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row is None:
            session.add(SystemSetting(key=key, value=value, is_secret=False))
        else:
            row.value = value
    await session.flush()


async def _v11_1_student_commerce(session: AsyncSession) -> None:
    """Backfill multi-level favorites and register the V11.1 commerce baseline."""
    legacy_rows = list((await session.scalars(select(Favorite))).all())
    for item in legacy_rows:
        exists_row = await session.scalar(
            select(StudentFavorite.id).where(
                StudentFavorite.user_id == item.user_id,
                StudentFavorite.target_type == FavoriteTargetType.OFFER.value,
                StudentFavorite.target_id == item.offer_id,
            )
        )
        if not exists_row:
            session.add(
                StudentFavorite(
                    user_id=item.user_id,
                    target_type=FavoriteTargetType.OFFER.value,
                    target_id=item.offer_id,
                    created_at=item.created_at,
                )
            )
    favorites_button = await session.scalar(
        select(MenuButtonConfig).where(MenuButtonConfig.key == "favorites")
    )
    if favorites_button:
        favorites_button.text = "❤️ مفضلاتي"

    release = await session.scalar(
        select(SystemSetting).where(SystemSetting.key == "operations.release_version")
    )
    if release:
        release.value = "11.1.0-student-commerce"
    else:
        session.add(
            SystemSetting(key="operations.release_version", value="11.1.0-student-commerce")
        )
    await session.flush()


async def _v11_2_provider_operations(session: AsyncSession) -> None:
    """Register provider operations defaults without rewriting commercial data."""
    providers = list((await session.scalars(select(Provider))).all())
    for provider in providers:
        for weekday in range(7):
            exists_row = await session.scalar(
                select(ProviderWorkingHour.id).where(
                    ProviderWorkingHour.provider_id == provider.id,
                    ProviderWorkingHour.weekday == weekday,
                )
            )
            if not exists_row:
                session.add(
                    ProviderWorkingHour(
                        provider_id=provider.id,
                        weekday=weekday,
                        opens_minute=600,
                        closes_minute=1380,
                        is_closed=False,
                        is_active=True,
                    )
                )
    release = await session.scalar(
        select(SystemSetting).where(SystemSetting.key == "operations.release_version")
    )
    if release:
        release.value = "11.2.0-provider-operations"
    else:
        session.add(
            SystemSetting(
                key="operations.release_version",
                value="11.2.0-provider-operations",
                is_secret=False,
            )
        )
    await session.flush()


async def _v11_3_friends_warranty(session: AsyncSession) -> None:
    """Register the friends-only escrow and warranty automation release."""
    release = await session.scalar(
        select(SystemSetting).where(SystemSetting.key == "operations.release_version")
    )
    if release:
        release.value = "11.3.0-friends-warranty"
    else:
        session.add(
            SystemSetting(
                key="operations.release_version",
                value="11.3.0-friends-warranty",
                is_secret=False,
            )
        )
    await session.flush()


async def _v11_4_owner_commerce(session: AsyncSession) -> None:
    reward_button = await session.scalar(
        select(MenuButtonConfig).where(MenuButtonConfig.key == "reward_tasks")
    )
    if not reward_button:
        reward_button = MenuButtonConfig(
            key="reward_tasks",
            text="💰 اكسب رصيد مجاني",
            action="earn",
            style="success",
            row_number=4,
            position=1,
            role_scope=["user", "provider", "admin"],
            is_enabled=True,
        )
        session.add(reward_button)
    else:
        reward_button.text = "💰 اكسب رصيد مجاني"
        reward_button.action = "earn"
        reward_button.style = "success"
    for key, value in {
        "menu.parent.reward_tasks": "account",
        "menu.surface.reward_tasks": "reply",
    }.items():
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row:
            row.value = value
        else:
            session.add(SystemSetting(key=key, value=value))
    flag = await session.scalar(select(FeatureFlag).where(FeatureFlag.key == "reward_tasks"))
    if not flag:
        session.add(FeatureFlag(
            key="reward_tasks", is_enabled=False, description="نظام المهام مقابل رصيد المحفظة"
        ))
    await session.flush()


async def _v11_5_reports_branding_health(session: AsyncSession) -> None:
    """Register official CampusPass IQ branding and V11.5 report infrastructure."""
    defaults = {
        "operations.release_version": "11.5.0-reports-branding-health",
        "brand.primary_color": "#003279",
        "brand.secondary_color": "#14A5A2",
        "brand.dark_color": "#082F63",
        "brand.name": "CampusPass IQ",
        "brand.tagline": "ACCESS. SERVICES. SUCCESS.",
    }
    for key, value in defaults.items():
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row:
            row.value = value
        else:
            session.add(SystemSetting(key=key, value=value, is_secret=False))
    await session.flush()


async def _v11_6_render_e2e_hardening(session: AsyncSession) -> None:
    defaults = {
        "operations.release_version": "11.6.0-render-e2e-hardening",
        "operations.telegram_delivery": "durable-webhook",
        "operations.render_predeploy": "enabled",
    }
    for key, value in defaults.items():
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row:
            row.value = value
        else:
            session.add(SystemSetting(key=key, value=value, is_secret=False))
    await session.flush()


async def _v11_7_lts_turbo_update_safe(session: AsyncSession) -> None:
    defaults = {
        "operations.release_version": "11.7.0-lts-turbo-update-safe",
        "operations.update_strategy": "expand-contract",
        "operations.cache_coherence": "generation-based",
        "operations.telegram_update_claim": "batch-wakeup-drain",
        "operations.fast_json": "orjson",
    }
    for key, value in defaults.items():
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row:
            row.value = value
        else:
            session.add(SystemSetting(key=key, value=value, is_secret=False))
    for namespace in ("menus", "features", "templates", "branding"):
        row = await session.scalar(
            select(RuntimeConfigGeneration).where(
                RuntimeConfigGeneration.namespace == namespace
            )
        )
        if row is None:
            session.add(RuntimeConfigGeneration(namespace=namespace, generation=1))
    await session.flush()


async def _v11_7_1_all_features_ready(session: AsyncSession) -> None:
    defaults = {
        "operations.release_version": "11.7.1-all-features-ready",
        "operations.backup_enabled": "true",
        "operations.backup_state": "enabled-pending-connector",
        "operations.evidence_external_storage": "enabled-pending-connector",
        "operations.image_moderation": "auto-local-with-external-upgrade",
        "operations.mastercard": "enabled-pending-gateway",
        "operations.provider_withdrawals": "enabled-pending-marketplace",
        "operations.gemini": "enabled-pending-api-key",
    }
    for key, value in defaults.items():
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row:
            row.value = value
        else:
            session.add(SystemSetting(key=key, value=value, is_secret=False))
    for key in ("gemini", "mastercard"):
        flag = await session.scalar(select(FeatureFlag).where(FeatureFlag.key == key))
        if flag:
            flag.is_enabled = True
        else:
            session.add(
                FeatureFlag(
                    key=key,
                    is_enabled=True,
                    description=(
                        "المساعد الذكي للأسئلة المخصصة"
                        if key == "gemini"
                        else "الدفع ببطاقات Mastercard عبر بوابة خارجية"
                    ),
                )
            )
    await session.flush()


async def _v11_7_2_render_schema_repair(session: AsyncSession) -> None:
    """Repair additive schema drift on long-lived production databases.

    ``Base.metadata.create_all`` creates missing tables but deliberately does not
    add columns to tables that already exist. Some databases upgraded from a
    pre-V11.1 release therefore lack ``cp_payment_proofs.file_fingerprint`` even
    though the current ORM model selects it. This migration is idempotent and
    additive: it never deletes or rewrites payment proofs.
    """

    connection = await session.connection()
    tables = await connection.run_sync(
        lambda sync_connection: set(inspect(sync_connection).get_table_names())
    )
    if "cp_payment_proofs" not in tables:
        return

    columns = await connection.run_sync(
        lambda sync_connection: {
            column["name"]
            for column in inspect(sync_connection).get_columns("cp_payment_proofs")
        }
    )
    if "file_fingerprint" not in columns:
        await session.execute(
            text(
                "ALTER TABLE cp_payment_proofs "
                "ADD COLUMN file_fingerprint VARCHAR(64) NULL"
            )
        )

    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_cp_payment_proofs_file_fingerprint "
            "ON cp_payment_proofs (file_fingerprint)"
        )
    )

    release = await session.scalar(
        select(SystemSetting).where(SystemSetting.key == "operations.release_version")
    )
    if release:
        release.value = "11.7.2-render-schema-repair"
    else:
        session.add(
            SystemSetting(
                key="operations.release_version",
                value="11.7.2-render-schema-repair",
                is_secret=False,
            )
        )
    await session.flush()


async def _v11_7_4_durable_ai_support(session: AsyncSession) -> None:
    """Register the durable, privacy-bounded AI support runtime.

    The durable queue table already exists from the enterprise foundation, so
    this release is schema-neutral. It only records operational capabilities
    and never overwrites an administrator's feature toggle or user data.
    """

    defaults = {
        "operations.release_version": "11.7.4-durable-ai-support",
        "operations.ai_support_queue": "postgres-durable",
        "operations.ai_support_prompt_isolation": "system-instruction-plus-trusted-context",
        "operations.ai_support_privacy": "minimum-context-with-explicit-consent",
        "operations.ai_support_resilience": "retry-circuit-breaker-human-escalation",
    }
    for key, value in defaults.items():
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row:
            row.value = value
        else:
            session.add(SystemSetting(key=key, value=value, is_secret=False))
    await session.flush()


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version="3.2.0-ui-manager",
        description="Add versioned update registry and dynamic menu presentation settings",
        apply=_register_ui_manager,
    ),
    Migration(
        version="3.3.0-catalog-subscriptions-outbox",
        description=(
            "Add provider catalog hierarchy, validity policies, student subscriptions, "
            "purchase reservations, receipts, and delivery outbox"
        ),
        apply=_backfill_catalog_and_validity,
    ),
    Migration(
        version="4.0.0-platform-foundation",
        description=(
            "Add built-in module registry, editable message templates, data-driven offer "
            "workflows, and per-order workflow state"
        ),
        apply=_v4_platform_foundation,
    ),
    Migration(
        version="4.1.0-production-hardening",
        description=(
            "Add idempotent payment webhook events, revocable report access, distributed "
            "scheduler locking, Redis runtime support, and verified order reviews"
        ),
        apply=_v4_1_hardening,
    ),
    Migration(
        version="5.0.0-radical-owner-platform-update",
        description=(
            "Add safe conversation navigation, owner menu builder and pricing, mandatory "
            "activation guides, timed announcements, email-code presets, A4 report tiers, "
            "bot issue reports, provider ratings, and report schedules"
        ),
        apply=_v5_radical_update,
    ),    Migration(
        version="5.0.5-user-security-controls",
        description="Add reversible user bans, CSV user export, and owner-controlled profile edit limits",
        apply=_v5_0_5_user_security,
    ),
    Migration(
        version="6.5.0-commercial-hardening-phase1",
        description=(
            "Centralize tenant permissions, add idempotency keys, delivery leases, "
            "notification delivery state, support close audit, and finance permissions"
        ),
        apply=_v6_5_commercial_hardening_phase1,
    ),
    Migration(
        version="6.6.0-disputes-refunds-phase2",
        description=(
            "Add transactional disputes, provider-direct refund confirmation, "
            "accounting reversals, subscription pause/restore, and exposed inventory remediation"
        ),
        apply=_v6_6_disputes_refunds_phase2,
    ),
    Migration(
        version="6.7.0-privacy-evidence-phase3",
        description=(
            "Encrypt profile and activation PII, add evidence retention/access logs, "
            "privacy export/deletion requests, and AI redaction consent"
        ),
        apply=_v6_7_privacy_evidence_phase3,
    ),
    Migration(
        version="6.8.0-user-experience-phase4",
        description=(
            "Add progressive onboarding, purchase confirmation, explicit delivery acknowledgement, "
            "activation confirmation, pagination, and centralized Arabic status labels"
        ),
        apply=_v6_8_user_experience_phase4,
    ),
    Migration(
        version="6.9.0-operations-reliability-phase5",
        description=(
            "Add deployment releases, persistent scheduled-run leases, encrypted verified backups, "
            "runtime incidents, multi-key decryption, and gradual secret rotation"
        ),
        apply=_v6_9_operations_reliability_phase5,
    ),    Migration(
        version="7.0.0-pilot-quality-phase6",
        description=(
            "Add persistent pilot validation runs and disaster-recovery drill evidence, "
            "with strict production dependency gates"
        ),
        apply=_v7_0_pilot_quality_phase6,
    ),
    Migration(
        version="8.0.0-enterprise-core-a",
        description=(
            "Add commercial plans, enterprise subscriptions and invoices, immutable balanced ledger, "
            "provider teams, API keys, and durable outbound webhooks"
        ),
        apply=_v8_0a_enterprise_core,
    ),
    Migration(
        version="8.0.0-enterprise-scale-b",
        description=(
            "Add API usage metering, distributed job leases, worker heartbeats, signed webhook attempts, "
            "subscription lifecycle automation, and final production scale controls"
        ),
        apply=_v8_0b_enterprise_scale,
    ),
    Migration(
        version="8.1.0-ux-wallet-settlement",
        description=(
            "Add simplified account grouping, visual menu movement, wallet overpayment rules, "
            "and owner-to-provider CampusPass fee collection workflow"
        ),
        apply=_v8_1_ux_wallet_settlement,
    ),    Migration(
        version="9.0.0-lts-freeze",
        description=(
            "Finalize simplified account navigation, expose wallet directly, hide the privacy menu button "
            "without removing privacy/security logic, and prepare long-term stable operation"
        ),
        apply=_v9_0_lts_freeze,
    ),
    Migration(
        version="10.2.0-callback-ui-inventory",
        description=(
            "Add a distributed polling singleton, immediate callback acknowledgement, compact callback "
            "tokens, serialized in-place UI rendering, mandatory provider branding, and expired-offer "
            "credential renewal without recreating offers"
        ),
        apply=_v10_2_callback_ui_inventory,
    ),
    Migration(
        version="10.3.0-offer-lifecycle-security",
        description=(
            "Add scheduled offer expiry and stock transitions, automatic launch broadcasts, safe logo "
            "moderation, direct credential replacement, and provider-bound FSM resolution"
        ),
        apply=_v10_3_offer_lifecycle_security,
    ),
    Migration(
        version="10.4.0-commerce-referral-payments",
        description=(
            "Add targeted student coupons, first-purchase referral wallet rewards, hardened payment "
            "proof review, and direct admin replies for missing-service requests"
        ),
        apply=_v10_4_commerce_referral_payments,
    ),
    Migration(
        version="10.5.0-final-hardening",
        description=(
            "Finalize in-place navigation, callback payload validation, FSM input guards, "
            "and indexed offer/inventory lifecycle queries"
        ),
        apply=_v10_5_final_hardening,
    ),
    Migration(
        version="10.6.0-platform-access-referral-cleanup",
        description=(
            "Hide privacy UI callbacks, add the platform TOS access gate, replace referral wallet "
            "credits with one-use coupons after three successful invites, and bypass external logo checks"
        ),
        apply=_v10_6_platform_access_referral_cleanup,
    ),
    Migration(
        version="10.7.0-emergency-stabilization",
        description=(
            "Unify provider access resolution, make reply/inline navigation deterministic, "
            "add local atomic branding, simplify the provider store, and cache the /start template"
        ),
        apply=_v10_7_emergency_stabilization,
    ),
    Migration(
        version="11.1.0-student-commerce",
        description=(
            "Add the signed Telegram Web App profile, multi-level favorites, provider working hours, "
            "immutable checkout snapshots, confirmed payment amounts, and status rewards"
        ),
        apply=_v11_1_student_commerce,
    ),
    Migration(
        version="11.2.0-provider-operations",
        description=(
            "Add provider-specific terms, canonical payment methods, unified provider inbox, "
            "student email/code relay, 60-second OTP leases, temporary logout proof, and restrictions"
        ),
        apply=_v11_2_provider_operations,
    ),
    Migration(
        version="11.3.0-friends-warranty",
        description=(
            "Add friends-only account reservation and escrow, 24-hour automatic refunds, "
            "synchronized group delivery, and student-confirmed warranty automation"
        ),
        apply=_v11_3_friends_warranty,
    ),
    Migration(
        version="11.4.0-owner-commerce",
        description=(
            "Add provider B2B billing, central owner inbox, targeted advertisements and coupons, "
            "hybrid bundles, and optional reward tasks"
        ),
        apply=_v11_4_owner_commerce,
    ),
    Migration(
        version="11.5.0-reports-branding-health",
        description=(
            "Add branded Free/Plus/Pro reports, official PDF artifacts, daily metrics, "
            "versioned UI revisions, and runtime health history"
        ),
        apply=_v11_5_reports_branding_health,
    ),
    Migration(
        version="11.6.0-render-e2e-hardening",
        description=(
            "Add durable Telegram webhook intake, deployment gates, Render pre-deploy checks, "
            "worker readiness, and end-to-end production smoke validation"
        ),
        apply=_v11_6_render_e2e_hardening,
    ),
    Migration(
        version="11.7.0-lts-turbo-update-safe",
        description=(
            "Add release compatibility contracts, generation-based cache coherence, "
            "batched low-latency Telegram update processing, graceful draining, and fast JSON"
        ),
        apply=_v11_7_lts_turbo_update_safe,
    ),
    Migration(
        version="11.7.1-all-features-ready",
        description=(
            "Enable optional integrations with safe pending-configuration readiness gates, "
            "activate local image moderation, and upgrade Gemini defaults"
        ),
        apply=_v11_7_1_all_features_ready,
    ),
    Migration(
        version="11.7.2-render-schema-repair",
        description=(
            "Repair additive payment-proof schema drift on long-lived databases without "
            "deleting or rewriting existing rows"
        ),
        apply=_v11_7_2_render_schema_repair,
    ),
    Migration(
        version="11.7.4-durable-ai-support",
        description=(
            "Add durable PostgreSQL-backed Gemini support jobs, minimum-context privacy, "
            "bounded concurrency, retries, circuit breaking, and human escalation"
        ),
        apply=_v11_7_4_durable_ai_support,
    ),

)


async def run_migrations(session: AsyncSession) -> list[str]:
    existing = set((await session.scalars(select(SchemaMigration.version))).all())
    applied: list[str] = []
    for migration in MIGRATIONS:
        if migration.version in existing:
            continue
        await migration.apply(session)
        session.add(
            SchemaMigration(
                version=migration.version,
                description=migration.description,
                checksum=migration.checksum,
            )
        )
        await session.flush()
        applied.append(migration.version)
    return applied
