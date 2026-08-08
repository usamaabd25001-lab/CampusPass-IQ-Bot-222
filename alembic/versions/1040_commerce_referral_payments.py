"""CampusPass V10.4 commerce, referrals, and payment review hardening.

Revision ID: 1040_commerce_referral_payments
Revises: 1030_offer_lifecycle_security
"""

from alembic import op
import sqlalchemy as sa

revision = "1040_commerce_referral_payments"
down_revision = "1030_offer_lifecycle_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "cp_order_coupons" in tables:
        columns = {column["name"] for column in inspector.get_columns("cp_order_coupons")}
        if "target_user_id" not in columns:
            op.add_column(
                "cp_order_coupons",
                sa.Column("target_user_id", sa.Integer(), nullable=True),
            )
            op.create_foreign_key(
                "fk_cp_order_coupons_target_user",
                "cp_order_coupons",
                "cp_users",
                ["target_user_id"],
                ["id"],
            )
            op.create_index(
                "ix_cp_order_coupons_target_user_id",
                "cp_order_coupons",
                ["target_user_id"],
            )

    if "cp_missing_service_requests" in tables:
        columns = {
            column["name"]
            for column in inspector.get_columns("cp_missing_service_requests")
        }
        if "response_text" not in columns:
            op.add_column(
                "cp_missing_service_requests",
                sa.Column("response_text", sa.Text(), nullable=False, server_default=""),
            )
        if "responded_by_user_id" not in columns:
            op.add_column(
                "cp_missing_service_requests",
                sa.Column("responded_by_user_id", sa.Integer(), nullable=True),
            )
            op.create_foreign_key(
                "fk_cp_missing_service_responded_by",
                "cp_missing_service_requests",
                "cp_users",
                ["responded_by_user_id"],
                ["id"],
            )
        if "responded_at" not in columns:
            op.add_column(
                "cp_missing_service_requests",
                sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
            )

    if "cp_user_benefits" not in tables:
        op.create_table(
            "cp_user_benefits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("cp_users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id"), nullable=True),
            sa.Column("benefit_key", sa.String(length=40), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "source_coupon_id",
                sa.Integer(),
                sa.ForeignKey("cp_order_coupons.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint(
                "source_coupon_id", "user_id", name="uq_cp_user_benefit_coupon_user"
            ),
        )
        op.create_index("ix_cp_user_benefits_user_id", "cp_user_benefits", ["user_id"])
        op.create_index("ix_cp_user_benefits_provider_id", "cp_user_benefits", ["provider_id"])
        op.create_index("ix_cp_user_benefits_benefit_key", "cp_user_benefits", ["benefit_key"])
        op.create_index(
            "ix_cp_user_benefit_active",
            "cp_user_benefits",
            ["user_id", "benefit_key", "expires_at"],
        )

    if "cp_system_settings" in tables:
        defaults = (
            ("referrals.reward_points", "10"),
            ("referrals.wallet_reward_iqd", "500"),
            ("payments.proof_max_bytes", "15000000"),
            ("operations.release_version", "10.4.0-commerce-referral-payments"),
        )
        for key, value in defaults:
            bind.execute(
                sa.text(
                    "INSERT INTO cp_system_settings (key, value, is_secret, updated_at) "
                    "VALUES (:key, :value, false, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP"
                ),
                {"key": key, "value": value},
            )


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade is disabled; restore a verified backup instead")
