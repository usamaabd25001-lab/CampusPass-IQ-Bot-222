"""CampusPass V11.1 student commerce and secure Web App profile.

Revision ID: 1110_student_commerce
Revises: 1070_emergency_stabilization
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "1110_student_commerce"
down_revision = "1070_emergency_stabilization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cp_payment_proofs",
        sa.Column("file_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_cp_payment_proofs_file_fingerprint",
        "cp_payment_proofs",
        ["file_fingerprint"],
    )
    op.create_table(
        "cp_student_favorites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "target_type", "target_id", name="uq_cp_student_favorite_target"),
    )
    op.create_index("ix_cp_student_favorites_user_id", "cp_student_favorites", ["user_id"])
    op.create_index("ix_cp_student_favorites_target_type", "cp_student_favorites", ["target_type"])
    op.create_index("ix_cp_student_favorites_target_id", "cp_student_favorites", ["target_id"])
    op.create_index("ix_cp_student_favorite_user_type", "cp_student_favorites", ["user_id", "target_type"])

    op.create_table(
        "cp_provider_brand_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("logo_file_id", sa.Text(), nullable=True),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("primary_color", sa.String(length=7), nullable=False, server_default="#0B4AA9"),
        sa.Column("secondary_color", sa.String(length=7), nullable=False, server_default="#18C6C4"),
        sa.Column("color_extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider_id", name="uq_cp_provider_brand_profiles_provider_id"),
    )
    op.create_index("ix_cp_provider_brand_profiles_provider_id", "cp_provider_brand_profiles", ["provider_id"], unique=True)

    op.create_table(
        "cp_provider_working_hours",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("opens_minute", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("closes_minute", sa.Integer(), nullable=False, server_default="1380"),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider_id", "weekday", name="uq_cp_provider_working_day"),
    )
    op.create_index("ix_cp_provider_working_hours_provider_id", "cp_provider_working_hours", ["provider_id"])
    op.create_index("ix_cp_provider_working_hour_lookup", "cp_provider_working_hours", ["provider_id", "weekday", "is_active"])

    op.create_table(
        "cp_checkout_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("cp_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id"), nullable=False),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("cp_offers.id"), nullable=False),
        sa.Column("service_price_iqd", sa.Integer(), nullable=False),
        sa.Column("discount_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bot_fee_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wallet_fee_deduction_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cash_due_iqd", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="IQD"),
        sa.Column("pricing_version", sa.String(length=30), nullable=False, server_default="v11.1"),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("order_id", name="uq_cp_checkout_snapshot_order"),
    )
    op.create_index("ix_cp_checkout_snapshots_order_id", "cp_checkout_snapshots", ["order_id"], unique=True)
    op.create_index("ix_cp_checkout_snapshots_user_id", "cp_checkout_snapshots", ["user_id"])
    op.create_index("ix_cp_checkout_snapshots_provider_id", "cp_checkout_snapshots", ["provider_id"])
    op.create_index("ix_cp_checkout_snapshots_offer_id", "cp_checkout_snapshots", ["offer_id"])
    op.create_index("ix_cp_checkout_snapshot_user_created", "cp_checkout_snapshots", ["user_id", "created_at"])

    op.create_table(
        "cp_payment_amount_confirmations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_proof_id", sa.Integer(), sa.ForeignKey("cp_payment_proofs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("cp_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("claimed_amount_iqd", sa.Integer(), nullable=False),
        sa.Column("confirmed_amount_iqd", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("rejection_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("confirmed_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("payment_proof_id", name="uq_cp_payment_amount_proof"),
    )
    op.create_index("ix_cp_payment_amount_confirmations_payment_proof_id", "cp_payment_amount_confirmations", ["payment_proof_id"], unique=True)
    op.create_index("ix_cp_payment_amount_confirmations_order_id", "cp_payment_amount_confirmations", ["order_id"])
    op.create_index("ix_cp_payment_amount_confirmations_status", "cp_payment_amount_confirmations", ["status"])
    op.create_index("ix_cp_payment_amount_order", "cp_payment_amount_confirmations", ["order_id", "status"])

    op.create_table(
        "cp_student_reward_statuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successful_referrals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successful_purchases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status_link_shares", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_level", sa.String(length=40), nullable=False, server_default="starter"),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_cp_student_reward_statuses_user_id"),
    )
    op.create_index("ix_cp_student_reward_statuses_user_id", "cp_student_reward_statuses", ["user_id"], unique=True)

    op.create_table(
        "cp_student_reward_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("points_delta", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("reference_type", sa.String(length=40), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_cp_student_reward_event_key"),
    )
    op.create_index("ix_cp_student_reward_events_user_id", "cp_student_reward_events", ["user_id"])
    op.create_index("ix_cp_student_reward_events_event_type", "cp_student_reward_events", ["event_type"])
    op.create_index("ix_cp_student_reward_event_user_created", "cp_student_reward_events", ["user_id", "created_at"])

    # Migrate legacy offer-only favorites without removing the old table yet.
    op.execute(
        sa.text(
            "INSERT INTO cp_student_favorites (user_id, target_type, target_id, created_at) "
            "SELECT user_id, 'offer', offer_id, created_at FROM cp_favorites "
            "ON CONFLICT (user_id, target_type, target_id) DO NOTHING"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_cp_payment_proofs_file_fingerprint", table_name="cp_payment_proofs")
    op.drop_column("cp_payment_proofs", "file_fingerprint")
    for table in (
        "cp_student_reward_events",
        "cp_student_reward_statuses",
        "cp_payment_amount_confirmations",
        "cp_checkout_snapshots",
        "cp_provider_working_hours",
        "cp_provider_brand_profiles",
        "cp_student_favorites",
    ):
        op.drop_table(table)
