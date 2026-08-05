"""V11.4 owner commerce control plane.

Revision ID: 1140_owner_commerce
Revises: 1130_friends_warranty
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "1140_owner_commerce"
down_revision = "1130_friends_warranty"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "cp_financial_proof_registry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("submitted_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("fingerprint", name="uq_cp_financial_proof_fingerprint"),
    )
    for column in ("fingerprint", "source_type", "source_id", "submitted_by_user_id", "provider_id"):
        op.create_index(f"ix_cp_financial_proof_registry_{column}", "cp_financial_proof_registry", [column], unique=column == "fingerprint")
    op.create_index("ix_cp_financial_proof_source", "cp_financial_proof_registry", ["source_type", "source_id"])
    op.create_index("ix_cp_financial_proof_created", "cp_financial_proof_registry", ["created_at"])

    op.create_table(
        "cp_provider_billing_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cycle_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("due_hours", sa.Integer(), nullable=False, server_default="48"),
        sa.Column("fixed_service_fee_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ad_hourly_rate_iqd", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("auto_suspend", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_invoice_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        *_timestamps(),
        sa.UniqueConstraint("provider_id", name="uq_cp_provider_billing_policy_provider"),
        sa.CheckConstraint("cycle_days IN (7,30)", name="ck_cp_provider_billing_cycle"),
        sa.CheckConstraint("due_hours BETWEEN 1 AND 720", name="ck_cp_provider_billing_due"),
        sa.CheckConstraint("fixed_service_fee_iqd >= 0 AND ad_hourly_rate_iqd >= 0", name="ck_cp_provider_billing_amounts"),
    )
    op.create_index("ix_cp_provider_billing_policies_provider_id", "cp_provider_billing_policies", ["provider_id"], unique=True)
    op.create_index("ix_cp_provider_billing_next", "cp_provider_billing_policies", ["is_active", "next_invoice_at"])

    op.create_table(
        "cp_business_invoice_proofs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("cp_business_invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id"), nullable=False),
        sa.Column("submitted_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=False),
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column("file_type", sa.String(24), nullable=False, server_default="photo"),
        sa.Column("file_fingerprint", sa.String(64), nullable=False),
        sa.Column("claimed_amount_iqd", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("file_fingerprint", name="uq_cp_business_invoice_proof_fingerprint"),
        sa.CheckConstraint("claimed_amount_iqd >= 0", name="ck_cp_business_invoice_proof_amount"),
    )
    for column in ("invoice_id", "provider_id", "submitted_by_user_id", "file_fingerprint"):
        op.create_index(f"ix_cp_business_invoice_proofs_{column}", "cp_business_invoice_proofs", [column], unique=column == "file_fingerprint")
    op.create_index("ix_cp_business_invoice_proof_status", "cp_business_invoice_proofs", ["status", "created_at"])

    op.create_table(
        "cp_owner_inbox_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="new"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("cp_orders.id"), nullable=True),
        sa.Column("assigned_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("summary", sa.String(500), nullable=False, server_default=""),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("public_id", name="uq_cp_owner_inbox_public"),
        sa.UniqueConstraint("source_type", "source_id", name="uq_cp_owner_inbox_source"),
    )
    for column in ("public_id", "kind", "status", "provider_id", "user_id", "order_id"):
        op.create_index(f"ix_cp_owner_inbox_items_{column}", "cp_owner_inbox_items", [column], unique=column == "public_id")
    op.create_index("ix_cp_owner_inbox_status_kind", "cp_owner_inbox_items", ["status", "kind", "created_at"])

    op.create_table(
        "cp_ad_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id"), nullable=True),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=False),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("campaign_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("cp_offers.id"), nullable=True),
        sa.Column("audience_rule_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("duration_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("hourly_rate_iqd", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("total_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("proof_file_id", sa.Text(), nullable=True),
        sa.Column("proof_fingerprint", sa.String(64), nullable=True),
        sa.Column("announcement_id", sa.Integer(), sa.ForeignKey("cp_announcements.id"), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("rejection_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("public_id", name="uq_cp_ad_campaign_public"),
        sa.UniqueConstraint("idempotency_key", name="uq_cp_ad_campaign_key"),
        sa.UniqueConstraint("proof_fingerprint", name="uq_cp_ad_campaign_proof"),
        sa.UniqueConstraint("announcement_id", name="uq_cp_ad_campaign_announcement"),
        sa.CheckConstraint("duration_hours BETWEEN 1 AND 2160", name="ck_cp_ad_campaign_duration"),
        sa.CheckConstraint("hourly_rate_iqd >= 0 AND total_iqd >= 0", name="ck_cp_ad_campaign_amounts"),
    )
    for column in ("public_id", "provider_id", "requested_by_user_id", "campaign_type", "offer_id", "status"):
        op.create_index(f"ix_cp_ad_campaigns_{column}", "cp_ad_campaigns", [column], unique=column == "public_id")
    op.create_index("ix_cp_ad_campaign_status_schedule", "cp_ad_campaigns", ["status", "starts_at", "ends_at"])

    op.create_table(
        "cp_ad_campaign_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("cp_ad_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "user_id", name="uq_cp_ad_campaign_recipient"),
    )
    op.create_index("ix_cp_ad_campaign_recipients_campaign_id", "cp_ad_campaign_recipients", ["campaign_id"])
    op.create_index("ix_cp_ad_campaign_recipients_user_id", "cp_ad_campaign_recipients", ["user_id"])
    op.create_index("ix_cp_ad_recipient_status", "cp_ad_campaign_recipients", ["campaign_id", "status"])

    op.create_table(
        "cp_coupon_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("coupon_id", sa.Integer(), sa.ForeignKey("cp_order_coupons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id"), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=False),
        sa.Column("audience_rule_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("assigned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("coupon_id", name="uq_cp_coupon_campaign_coupon"),
        sa.CheckConstraint("assigned_count >= 0", name="ck_cp_coupon_campaign_count"),
    )
    op.create_index("ix_cp_coupon_campaigns_coupon_id", "cp_coupon_campaigns", ["coupon_id"], unique=True)
    op.create_index("ix_cp_coupon_campaigns_provider_id", "cp_coupon_campaigns", ["provider_id"])
    op.create_index("ix_cp_coupon_campaign_status", "cp_coupon_campaigns", ["status", "created_at"])

    op.create_table(
        "cp_coupon_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("cp_coupon_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("coupon_id", sa.Integer(), sa.ForeignKey("cp_order_coupons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="available"),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "user_id", name="uq_cp_coupon_assignment_user"),
    )
    for column in ("campaign_id", "coupon_id", "user_id"):
        op.create_index(f"ix_cp_coupon_assignments_{column}", "cp_coupon_assignments", [column])
    op.create_index("ix_cp_coupon_assignment_user_status", "cp_coupon_assignments", ["user_id", "status"])

    op.create_table(
        "cp_hybrid_bundles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(40), nullable=False),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("price_iqd", sa.Integer(), nullable=False),
        sa.Column("bot_fee_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("public_id", name="uq_cp_hybrid_bundle_public"),
        sa.CheckConstraint("price_iqd > 0 AND bot_fee_iqd >= 0 AND bot_fee_iqd < price_iqd", name="ck_cp_hybrid_bundle_amounts"),
    )
    op.create_index("ix_cp_hybrid_bundles_public_id", "cp_hybrid_bundles", ["public_id"], unique=True)
    op.create_index("ix_cp_hybrid_bundles_status", "cp_hybrid_bundles", ["status"])

    op.create_table(
        "cp_hybrid_bundle_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bundle_id", sa.Integer(), sa.ForeignKey("cp_hybrid_bundles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("cp_offers.id"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id"), nullable=False),
        sa.Column("provider_share_iqd", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("bundle_id", "offer_id", name="uq_cp_hybrid_bundle_offer"),
        sa.CheckConstraint("provider_share_iqd > 0", name="ck_cp_hybrid_component_share"),
    )
    for column in ("bundle_id", "offer_id", "provider_id"):
        op.create_index(f"ix_cp_hybrid_bundle_components_{column}", "cp_hybrid_bundle_components", [column])
    op.create_index("ix_cp_hybrid_component_provider", "cp_hybrid_bundle_components", ["provider_id", "bundle_id"])

    op.create_table(
        "cp_hybrid_bundle_purchases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("bundle_id", sa.Integer(), sa.ForeignKey("cp_hybrid_bundles.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("total_iqd", sa.Integer(), nullable=False),
        sa.Column("bot_fee_iqd", sa.Integer(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id", name="uq_cp_hybrid_purchase_public"),
        sa.UniqueConstraint("idempotency_key", name="uq_cp_hybrid_purchase_key"),
        sa.CheckConstraint("total_iqd > 0 AND bot_fee_iqd >= 0", name="ck_cp_hybrid_purchase_amounts"),
    )
    for column in ("public_id", "bundle_id", "user_id", "status"):
        op.create_index(f"ix_cp_hybrid_bundle_purchases_{column}", "cp_hybrid_bundle_purchases", [column], unique=column == "public_id")
    op.create_index("ix_cp_hybrid_purchase_user_status", "cp_hybrid_bundle_purchases", ["user_id", "status"])


    op.create_table(
        "cp_hybrid_inventory_holds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_id", sa.Integer(), sa.ForeignKey("cp_hybrid_bundle_purchases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("component_id", sa.Integer(), sa.ForeignKey("cp_hybrid_bundle_components.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inventory_item_id", sa.Integer(), sa.ForeignKey("cp_inventory_items.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="held"),
        sa.Column("consumed_order_id", sa.Integer(), sa.ForeignKey("cp_orders.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("purchase_id", "component_id", name="uq_cp_hybrid_hold_component"),
        sa.UniqueConstraint("consumed_order_id", name="uq_cp_hybrid_hold_order"),
    )
    for column in ("purchase_id", "component_id", "inventory_item_id", "status"):
        op.create_index(f"ix_cp_hybrid_inventory_holds_{column}", "cp_hybrid_inventory_holds", [column])
    op.create_index("ix_cp_hybrid_hold_status_expiry", "cp_hybrid_inventory_holds", ["status", "expires_at"])

    op.create_table(
        "cp_hybrid_purchase_proofs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_id", sa.Integer(), sa.ForeignKey("cp_hybrid_bundle_purchases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=False),
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column("file_type", sa.String(24), nullable=False, server_default="photo"),
        sa.Column("file_fingerprint", sa.String(64), nullable=False),
        sa.Column("claimed_amount_iqd", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("file_fingerprint", name="uq_cp_hybrid_purchase_proof_fingerprint"),
        sa.CheckConstraint("claimed_amount_iqd > 0", name="ck_cp_hybrid_purchase_proof_amount"),
    )
    for column in ("purchase_id", "user_id", "file_fingerprint"):
        op.create_index(f"ix_cp_hybrid_purchase_proofs_{column}", "cp_hybrid_purchase_proofs", [column], unique=column == "file_fingerprint")
    op.create_index("ix_cp_hybrid_purchase_proof_status", "cp_hybrid_purchase_proofs", ["status", "created_at"])

    op.create_table(
        "cp_hybrid_revenue_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_id", sa.Integer(), sa.ForeignKey("cp_hybrid_bundle_purchases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("component_id", sa.Integer(), sa.ForeignKey("cp_hybrid_bundle_components.id"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("cp_orders.id"), nullable=True),
        sa.Column("amount_iqd", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("purchase_id", "component_id", name="uq_cp_hybrid_allocation_component"),
        sa.UniqueConstraint("idempotency_key", name="uq_cp_hybrid_allocation_key"),
        sa.UniqueConstraint("order_id", name="uq_cp_hybrid_allocation_order"),
        sa.CheckConstraint("amount_iqd > 0", name="ck_cp_hybrid_allocation_amount"),
    )
    for column in ("purchase_id", "component_id", "provider_id", "order_id"):
        op.create_index(f"ix_cp_hybrid_revenue_allocations_{column}", "cp_hybrid_revenue_allocations", [column])

    op.create_table(
        "cp_reward_task_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id"), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=False),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("channel_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_url", sa.Text(), nullable=False),
        sa.Column("reward_iqd", sa.Integer(), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("capacity_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("budget_iqd", sa.Integer(), nullable=False),
        sa.Column("spent_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("proof_file_id", sa.Text(), nullable=True),
        sa.Column("proof_fingerprint", sa.String(64), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("rejection_reason", sa.Text(), nullable=False, server_default=""),
        *_timestamps(),
        sa.UniqueConstraint("public_id", name="uq_cp_reward_task_public"),
        sa.UniqueConstraint("idempotency_key", name="uq_cp_reward_task_key"),
        sa.UniqueConstraint("proof_fingerprint", name="uq_cp_reward_task_proof"),
        sa.CheckConstraint("reward_iqd > 0 AND requested_count > 0 AND capacity_count > 0", name="ck_cp_reward_task_positive"),
        sa.CheckConstraint("budget_iqd > 0 AND spent_iqd >= 0 AND spent_iqd <= budget_iqd", name="ck_cp_reward_task_budget"),
        sa.CheckConstraint("completed_count >= 0 AND completed_count <= capacity_count", name="ck_cp_reward_task_completion"),
    )
    for column in ("public_id", "provider_id", "requested_by_user_id", "status"):
        op.create_index(f"ix_cp_reward_task_campaigns_{column}", "cp_reward_task_campaigns", [column], unique=column == "public_id")

    op.create_table(
        "cp_reward_task_completions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("cp_reward_task_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("wallet_entry_id", sa.Integer(), sa.ForeignKey("cp_wallet_entries.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "user_id", name="uq_cp_reward_completion_user"),
        sa.UniqueConstraint("idempotency_key", name="uq_cp_reward_completion_key"),
        sa.UniqueConstraint("wallet_entry_id", name="uq_cp_reward_completion_wallet"),
    )
    for column in ("campaign_id", "user_id", "status"):
        op.create_index(f"ix_cp_reward_task_completions_{column}", "cp_reward_task_completions", [column])


def downgrade() -> None:
    for table in [
        "cp_reward_task_completions",
        "cp_reward_task_campaigns",
        "cp_hybrid_revenue_allocations",
        "cp_hybrid_purchase_proofs",
        "cp_hybrid_inventory_holds",
        "cp_hybrid_bundle_purchases",
        "cp_hybrid_bundle_components",
        "cp_hybrid_bundles",
        "cp_coupon_assignments",
        "cp_coupon_campaigns",
        "cp_ad_campaign_recipients",
        "cp_ad_campaigns",
        "cp_owner_inbox_items",
        "cp_business_invoice_proofs",
        "cp_provider_billing_policies",
        "cp_financial_proof_registry",
    ]:
        op.drop_table(table)
