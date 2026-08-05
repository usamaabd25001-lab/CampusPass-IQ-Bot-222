"""V11.3 friends-only escrow and warranty automation.

Revision ID: 1130_friends_warranty
Revises: 1120_provider_operations
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "1130_friends_warranty"
down_revision = "1120_provider_operations"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "cp_friend_package_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("cp_offers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("required_members", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("join_window_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("full_bot_fee_per_member", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("terms_version", sa.String(30), nullable=False, server_default="v1"),
        sa.Column("accepted_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        *_timestamps(),
        sa.UniqueConstraint("offer_id", name="uq_cp_friend_package_offer"),
        sa.CheckConstraint("required_members BETWEEN 2 AND 50", name="ck_cp_friend_package_members"),
        sa.CheckConstraint("join_window_hours = 24", name="ck_cp_friend_package_window"),
    )
    op.create_index("ix_cp_friend_package_configs_provider_id", "cp_friend_package_configs", ["provider_id"])
    op.create_index("ix_cp_friend_package_configs_offer_id", "cp_friend_package_configs", ["offer_id"], unique=True)
    op.create_index("ix_cp_friend_package_provider_enabled", "cp_friend_package_configs", ["provider_id", "is_enabled"])

    op.create_table(
        "cp_friend_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(40), nullable=False),
        sa.Column("join_token_hash", sa.String(64), nullable=False),
        sa.Column("config_id", sa.Integer(), sa.ForeignKey("cp_friend_package_configs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id"), nullable=False),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("cp_offers.id"), nullable=False),
        sa.Column("creator_user_id", sa.Integer(), sa.ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inventory_item_id", sa.Integer(), sa.ForeignKey("cp_inventory_items.id"), nullable=False),
        sa.Column("reservation_order_id", sa.Integer(), sa.ForeignKey("cp_orders.id"), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("required_members", sa.Integer(), nullable=False),
        sa.Column("paid_members", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("service_total_iqd", sa.Integer(), nullable=False),
        sa.Column("bot_fee_per_member_iqd", sa.Integer(), nullable=False),
        sa.Column("escrow_service_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("escrow_bot_fee_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        *_timestamps(),
        sa.UniqueConstraint("public_id", name="uq_cp_friend_group_public"),
        sa.UniqueConstraint("join_token_hash", name="uq_cp_friend_group_token"),
        sa.CheckConstraint("required_members BETWEEN 2 AND 50", name="ck_cp_friend_group_members"),
        sa.CheckConstraint("paid_members BETWEEN 0 AND required_members", name="ck_cp_friend_group_paid"),
        sa.CheckConstraint("service_total_iqd >= 0", name="ck_cp_friend_group_service_total"),
        sa.CheckConstraint("bot_fee_per_member_iqd >= 0", name="ck_cp_friend_group_bot_fee"),
        sa.CheckConstraint("escrow_service_iqd >= 0 AND escrow_bot_fee_iqd >= 0", name="ck_cp_friend_group_escrow"),
    )
    for column in ("public_id", "join_token_hash", "config_id", "provider_id", "offer_id", "creator_user_id", "inventory_item_id", "reservation_order_id", "status", "expires_at"):
        op.create_index(f"ix_cp_friend_groups_{column}", "cp_friend_groups", [column], unique=column in {"public_id", "join_token_hash"})
    op.create_index("ix_cp_friend_group_expiry", "cp_friend_groups", ["status", "expires_at"])
    op.create_index("ix_cp_friend_group_offer_status", "cp_friend_groups", ["offer_id", "status"])

    op.create_table(
        "cp_friend_group_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("cp_friend_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("cp_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_index", sa.Integer(), nullable=False),
        sa.Column("is_creator", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(24), nullable=False, server_default="awaiting_payment"),
        sa.Column("service_share_iqd", sa.Integer(), nullable=False),
        sa.Column("bot_fee_iqd", sa.Integer(), nullable=False),
        sa.Column("wallet_fee_deduction_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cash_due_iqd", sa.Integer(), nullable=False),
        sa.Column("paid_amount_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("group_id", "user_id", name="uq_cp_friend_group_user"),
        sa.UniqueConstraint("order_id", name="uq_cp_friend_member_order"),
        sa.CheckConstraint("member_index >= 0", name="ck_cp_friend_member_index"),
        sa.CheckConstraint("service_share_iqd >= 0 AND bot_fee_iqd >= 0", name="ck_cp_friend_member_amounts"),
        sa.CheckConstraint("wallet_fee_deduction_iqd >= 0 AND cash_due_iqd >= 0 AND paid_amount_iqd >= 0", name="ck_cp_friend_member_payments"),
    )
    for column in ("group_id", "user_id", "order_id", "status"):
        op.create_index(f"ix_cp_friend_group_members_{column}", "cp_friend_group_members", [column], unique=column == "order_id")
    op.create_index("ix_cp_friend_member_group_status", "cp_friend_group_members", ["group_id", "status"])

    op.create_table(
        "cp_friend_escrow_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("cp_friend_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("cp_friend_group_members.id", ondelete="SET NULL"), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("cp_orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("service_amount_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bot_fee_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_cp_friend_escrow_key"),
    )
    for column in ("group_id", "member_id", "order_id", "entry_type"):
        op.create_index(f"ix_cp_friend_escrow_entries_{column}", "cp_friend_escrow_entries", [column])
    op.create_index("ix_cp_friend_escrow_group_created", "cp_friend_escrow_entries", ["group_id", "created_at"])

    op.create_table(
        "cp_warranty_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("cp_offers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("coverage_mode", sa.String(32), nullable=False, server_default="subscription_period"),
        sa.Column("response_sla_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        *_timestamps(),
        sa.UniqueConstraint("offer_id", name="uq_cp_warranty_policy_offer"),
        sa.CheckConstraint("response_sla_minutes BETWEEN 5 AND 1440", name="ck_cp_warranty_response_sla"),
    )
    op.create_index("ix_cp_warranty_policies_provider_id", "cp_warranty_policies", ["provider_id"])
    op.create_index("ix_cp_warranty_policies_offer_id", "cp_warranty_policies", ["offer_id"], unique=True)
    op.create_index("ix_cp_warranty_provider_enabled", "cp_warranty_policies", ["provider_id", "is_enabled"])

    op.create_table(
        "cp_warranty_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("cp_warranty_policies.id"), nullable=False),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("cp_student_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("cp_orders.id"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="open"),
        sa.Column("screenshot_file_id", sa.Text(), nullable=True),
        sa.Column("student_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("provider_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("resolution_type", sa.String(40), nullable=True),
        sa.Column("assigned_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("resolved_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("student_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("public_id", name="uq_cp_warranty_claim_public"),
        sa.UniqueConstraint("idempotency_key", name="uq_cp_warranty_claim_key"),
    )
    for column in ("public_id", "policy_id", "subscription_id", "order_id", "provider_id", "user_id", "category", "status"):
        op.create_index(f"ix_cp_warranty_claims_{column}", "cp_warranty_claims", [column], unique=column == "public_id")
    op.create_index("ix_cp_warranty_claim_provider_status", "cp_warranty_claims", ["provider_id", "status", "created_at"])
    op.create_index("ix_cp_warranty_claim_subscription", "cp_warranty_claims", ["subscription_id", "status"])
    # PostgreSQL safety net: one active warranty workflow per subscription.
    op.create_index(
        "uq_cp_warranty_active_subscription",
        "cp_warranty_claims",
        ["subscription_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('open','in_review','waiting_student_action','replacement_pending','waiting_student_confirmation')"
        ),
    )

    op.create_table(
        "cp_warranty_claim_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("cp_warranty_claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("from_status", sa.String(40), nullable=True),
        sa.Column("to_status", sa.String(40), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_cp_warranty_event_key"),
    )
    op.create_index("ix_cp_warranty_claim_events_claim_id", "cp_warranty_claim_events", ["claim_id"])
    op.create_index("ix_cp_warranty_claim_events_event_type", "cp_warranty_claim_events", ["event_type"])
    op.create_index("ix_cp_warranty_event_claim", "cp_warranty_claim_events", ["claim_id", "created_at"])

    op.create_table(
        "cp_warranty_replacements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("cp_warranty_claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("old_inventory_item_id", sa.Integer(), sa.ForeignKey("cp_inventory_items.id"), nullable=True),
        sa.Column("new_inventory_item_id", sa.Integer(), sa.ForeignKey("cp_inventory_items.id"), nullable=False),
        sa.Column("delivery_job_id", sa.Integer(), sa.ForeignKey("cp_delivery_jobs.id"), nullable=True),
        sa.Column("replaced_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("claim_id", name="uq_cp_warranty_replacement_claim"),
        sa.UniqueConstraint("new_inventory_item_id", name="uq_cp_warranty_replacement_item"),
        sa.UniqueConstraint("delivery_job_id", name="uq_cp_warranty_replacement_job"),
    )
    op.create_index("ix_cp_warranty_replacements_claim_id", "cp_warranty_replacements", ["claim_id"], unique=True)
    op.create_index("ix_cp_warranty_replacements_new_inventory_item_id", "cp_warranty_replacements", ["new_inventory_item_id"], unique=True)


def downgrade() -> None:
    for table in [
        "cp_warranty_replacements",
        "cp_warranty_claim_events",
        "cp_warranty_claims",
        "cp_warranty_policies",
        "cp_friend_escrow_entries",
        "cp_friend_group_members",
        "cp_friend_groups",
        "cp_friend_package_configs",
    ]:
        op.drop_table(table)
