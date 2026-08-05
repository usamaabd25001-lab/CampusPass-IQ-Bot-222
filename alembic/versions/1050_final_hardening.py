"""CampusPass V10.5 final navigation, FSM, and lifecycle hardening.

Revision ID: 1050_final_hardening
Revises: 1040_commerce_referral_payments
"""

from alembic import op
import sqlalchemy as sa

revision = "1050_final_hardening"
down_revision = "1040_commerce_referral_payments"
branch_labels = None
depends_on = None


def _index_names(table_name: str) -> set[str]:
    return {
        str(item.get("name"))
        for item in sa.inspect(op.get_bind()).get_indexes(table_name)
        if item.get("name")
    }


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "cp_providers" in tables and "ix_cp_provider_active_status" not in _index_names("cp_providers"):
        op.create_index(
            "ix_cp_provider_active_status",
            "cp_providers",
            ["is_active", "status", "name_ar"],
        )
    if "cp_offers" in tables and "ix_cp_offer_lifecycle" not in _index_names("cp_offers"):
        op.create_index(
            "ix_cp_offer_lifecycle",
            "cp_offers",
            ["status", "is_active", "end_at"],
        )
    if (
        "cp_inventory_items" in tables
        and "ix_cp_inventory_lifecycle" not in _index_names("cp_inventory_items")
    ):
        op.create_index(
            "ix_cp_inventory_lifecycle",
            "cp_inventory_items",
            ["status", "expires_at", "offer_id"],
        )

    if "cp_system_settings" in tables:
        defaults = (
            ("offers.lifecycle.enabled", "true"),
            ("offers.lifecycle.interval_seconds", "60"),
            ("operations.release_version", "10.5.0-final-hardening"),
        )
        bind = op.get_bind()
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
