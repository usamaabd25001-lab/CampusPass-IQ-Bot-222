"""CampusPass V10.3 offer lifecycle and branding security.

Revision ID: 1030_offer_lifecycle_security
Revises: 1020_callback_ui_inventory
"""

from alembic import op
import sqlalchemy as sa

revision = "1030_offer_lifecycle_security"
down_revision = "1020_callback_ui_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This release reuses additive columns/tables already present in metadata.
    # Persist release defaults idempotently for deployments using Alembic only.
    bind = op.get_bind()
    if "cp_system_settings" not in sa.inspect(bind).get_table_names():
        return
    defaults = (
        ("offers.lifecycle.enabled", "true"),
        ("offers.lifecycle.interval_seconds", "60"),
        ("branding.moderation.provider", "google_vision"),
        ("branding.moderation.fail_closed", "true"),
        ("operations.release_version", "10.3.0-offer-lifecycle-security"),
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
