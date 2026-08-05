"""CampusPass V10.6 platform access, referral and privacy UI cleanup.

Revision ID: 1060_platform_access_referral_cleanup
Revises: 1050_final_hardening
"""

from alembic import op
import sqlalchemy as sa

revision = "1060_platform_access_referral_cleanup"
down_revision = "1050_final_hardening"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    return {
        str(item.get("name"))
        for item in sa.inspect(op.get_bind()).get_columns(table_name)
        if item.get("name")
    }


def _index_names(table_name: str) -> set[str]:
    return {
        str(item.get("name"))
        for item in sa.inspect(op.get_bind()).get_indexes(table_name)
        if item.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "cp_users" in tables:
        if "has_platform_access" not in _column_names("cp_users"):
            op.add_column(
                "cp_users",
                sa.Column(
                    "has_platform_access",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )
        if "ix_cp_users_has_platform_access" not in _index_names("cp_users"):
            op.create_index(
                "ix_cp_users_has_platform_access",
                "cp_users",
                ["has_platform_access"],
            )

    if "cp_menu_buttons" in tables:
        bind.execute(
            sa.text(
                "UPDATE cp_menu_buttons SET is_enabled = false WHERE key = 'privacy'"
            )
        )

    if "cp_system_settings" in tables:
        defaults = (
            ("referrals.invites_per_coupon", "3"),
            ("referrals.reward_mode", "single_use_fee_waiver_coupon"),
            ("referrals.wallet_reward_iqd", "0"),
            ("branding.moderation.provider", "disabled"),
            ("operations.release_version", "10.6.0-platform-access-referral-cleanup"),
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
