"""CampusPass V10.2 callback, UI sync, and polling lease.

Revision ID: 1020_callback_ui_inventory
Revises: 690_operations_baseline
"""

from alembic import op
import sqlalchemy as sa

revision = "1020_callback_ui_inventory"
down_revision = "690_operations_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "cp_runtime_leases" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "cp_runtime_leases",
            sa.Column("lease_key", sa.String(length=120), primary_key=True),
            sa.Column("owner_id", sa.String(length=160), nullable=False, server_default=""),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
        )
        op.create_index("ix_cp_runtime_leases_owner_id", "cp_runtime_leases", ["owner_id"])
        op.create_index("ix_cp_runtime_leases_expires_at", "cp_runtime_leases", ["expires_at"])


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade is disabled; restore a verified backup instead")
