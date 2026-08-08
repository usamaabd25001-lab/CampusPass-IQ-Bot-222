"""CampusPass V11.2 provider operations, OTP queue and temporary access.

Revision ID: 1120_provider_operations
Revises: 1110_student_commerce
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "1120_provider_operations"
down_revision = "1110_student_commerce"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "cp_provider_terms_acceptances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("terms_version", sa.String(32), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("provider_id", "user_id", "terms_version", name="uq_cp_provider_terms_version"),
    )
    op.create_index("ix_cp_provider_terms_acceptances_provider_id", "cp_provider_terms_acceptances", ["provider_id"])
    op.create_index("ix_cp_provider_terms_acceptances_user_id", "cp_provider_terms_acceptances", ["user_id"])
    op.create_index("ix_cp_provider_terms_user_provider", "cp_provider_terms_acceptances", ["user_id", "provider_id"])

    op.create_table(
        "cp_provider_offer_fulfillment_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("cp_offers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_type", sa.String(32), nullable=False),
        sa.Column("activation_mode", sa.String(40), nullable=False),
        sa.Column("shared_capacity", sa.Integer(), nullable=True),
        sa.Column("unlimited_capacity", sa.Boolean(), nullable=False),
        sa.Column("temporary_access_minutes", sa.Integer(), nullable=True),
        sa.Column("logout_proof_required", sa.Boolean(), nullable=False),
        sa.Column("student_email_required", sa.Boolean(), nullable=False),
        sa.Column("student_code_relay_enabled", sa.Boolean(), nullable=False),
        sa.Column("otp_lease_seconds", sa.Integer(), nullable=False),
        sa.Column("max_otp_attempts", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("offer_id", name="uq_cp_provider_offer_fulfillment_offer"),
    )
    op.create_index("ix_cp_provider_offer_fulfillment_profiles_offer_id", "cp_provider_offer_fulfillment_profiles", ["offer_id"], unique=True)
    op.create_index("ix_cp_provider_offer_fulfillment_profiles_provider_id", "cp_provider_offer_fulfillment_profiles", ["provider_id"])

    op.create_table(
        "cp_provider_payment_method_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_method_id", sa.Integer(), sa.ForeignKey("cp_payment_methods.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("balance_mode", sa.String(32), nullable=True),
        sa.Column("proof_guide_file_id", sa.Text(), nullable=True),
        sa.Column("proof_guide_text", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("payment_method_id", name="uq_cp_provider_payment_method_config"),
    )
    op.create_index("ix_cp_provider_payment_method_configs_payment_method_id", "cp_provider_payment_method_configs", ["payment_method_id"], unique=True)
    op.create_index("ix_cp_provider_payment_method_configs_provider_id", "cp_provider_payment_method_configs", ["provider_id"])

    op.create_table(
        "cp_provider_inbox_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("cp_orders.id", ondelete="CASCADE"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("file_id", sa.Text(), nullable=True),
        sa.Column("amount_iqd", sa.Integer(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("assigned_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("processed_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("idempotency_key", name="uq_cp_provider_inbox_item_key"),
    )
    for col in ("provider_id", "kind", "status", "priority", "order_id", "user_id"):
        op.create_index(f"ix_cp_provider_inbox_items_{col}", "cp_provider_inbox_items", [col])
    op.create_index("ix_cp_provider_inbox_active", "cp_provider_inbox_items", ["provider_id", "status", "priority", "created_at"])
    op.create_index("ix_cp_provider_inbox_order", "cp_provider_inbox_items", ["order_id", "kind"])

    op.create_table(
        "cp_provider_inbox_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inbox_item_id", sa.Integer(), sa.ForeignKey("cp_provider_inbox_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("from_status", sa.String(24), nullable=True),
        sa.Column("to_status", sa.String(24), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cp_provider_inbox_events_inbox_item_id", "cp_provider_inbox_events", ["inbox_item_id"])
    op.create_index("ix_cp_provider_inbox_events_event_type", "cp_provider_inbox_events", ["event_type"])
    op.create_index("ix_cp_provider_inbox_event_item", "cp_provider_inbox_events", ["inbox_item_id", "created_at"])

    op.create_table(
        "cp_student_activation_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("cp_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("encrypted_email", sa.Text(), nullable=False),
        sa.Column("email_hint", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("code_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        *_timestamps(),
    )
    for col in ("order_id", "provider_id", "user_id", "status"):
        op.create_index(f"ix_cp_student_activation_requests_{col}", "cp_student_activation_requests", [col])
    op.create_index("ix_cp_student_activation_provider_status", "cp_student_activation_requests", ["provider_id", "status", "created_at"])
    op.create_index("ix_cp_student_activation_order", "cp_student_activation_requests", ["order_id", "created_at"])

    op.create_table(
        "cp_student_code_relays",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("activation_request_id", sa.Integer(), sa.ForeignKey("cp_student_activation_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("encrypted_code", sa.Text(), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("activation_request_id", "attempt", name="uq_cp_code_relay_attempt"),
    )
    op.create_index("ix_cp_student_code_relays_activation_request_id", "cp_student_code_relays", ["activation_request_id"])
    op.create_index("ix_cp_student_code_relays_code_hash", "cp_student_code_relays", ["code_hash"])
    op.create_index("ix_cp_student_code_relays_status", "cp_student_code_relays", ["status"])
    op.create_index("ix_cp_student_code_relays_expires_at", "cp_student_code_relays", ["expires_at"])
    op.create_index("ix_cp_code_relay_status_expiry", "cp_student_code_relays", ["status", "expires_at"])

    op.create_table(
        "cp_otp_account_leases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email_account_id", sa.Integer(), sa.ForeignKey("cp_email_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("cp_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("holder_user_id", sa.Integer(), sa.ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_cp_otp_account_lease_token"),
    )
    for col in ("email_account_id", "order_id", "holder_user_id", "status", "expires_at"):
        op.create_index(f"ix_cp_otp_account_leases_{col}", "cp_otp_account_leases", [col])
    op.create_index("ix_cp_otp_lease_account_expiry", "cp_otp_account_leases", ["email_account_id", "expires_at"])
    op.create_index("ix_cp_otp_lease_order", "cp_otp_account_leases", ["order_id", "status"])

    op.create_table(
        "cp_temporary_logout_proofs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("temporary_session_id", sa.Integer(), sa.ForeignKey("cp_temporary_access_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("cp_orders.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=False),
        sa.Column("evidence_asset_id", sa.Integer(), sa.ForeignKey("cp_evidence_assets.id"), nullable=True),
        sa.Column("telegram_file_id", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("student_note", sa.Text(), nullable=False),
        sa.Column("provider_note", sa.Text(), nullable=False),
        sa.Column("confirmed_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("temporary_session_id", name="uq_cp_logout_proof_session"),
    )
    for col in ("temporary_session_id", "provider_id", "order_id", "user_id", "status"):
        op.create_index(f"ix_cp_temporary_logout_proofs_{col}", "cp_temporary_logout_proofs", [col], unique=(col == "temporary_session_id"))
    op.create_index("ix_cp_logout_proof_provider_status", "cp_temporary_logout_proofs", ["provider_id", "status", "created_at"])

    op.create_table(
        "cp_student_operational_restrictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id"), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("cp_orders.id"), nullable=True),
        sa.Column("restriction_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("imposed_by", sa.String(30), nullable=False),
        sa.Column("imposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lifted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lifted_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
    )
    for col in ("user_id", "provider_id", "order_id", "restriction_type", "status"):
        op.create_index(f"ix_cp_student_operational_restrictions_{col}", "cp_student_operational_restrictions", [col])
    op.create_index("ix_cp_student_restriction_active", "cp_student_operational_restrictions", ["user_id", "status", "restriction_type"])


def downgrade() -> None:
    for table in [
        "cp_student_operational_restrictions",
        "cp_temporary_logout_proofs",
        "cp_otp_account_leases",
        "cp_student_code_relays",
        "cp_student_activation_requests",
        "cp_provider_inbox_events",
        "cp_provider_inbox_items",
        "cp_provider_payment_method_configs",
        "cp_provider_offer_fulfillment_profiles",
        "cp_provider_terms_acceptances",
    ]:
        op.drop_table(table)
