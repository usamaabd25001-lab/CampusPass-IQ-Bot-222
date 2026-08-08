"""Provider commerce Web App hardening.

Revision ID: 1180_provider_commerce_webapp
Revises: 1171_all_features_ready
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "1180_provider_commerce_webapp"
down_revision = "1171_all_features_ready"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("cp_providers")}
    if "default_service_fee_iqd" not in columns:
        op.add_column(
            "cp_providers",
            sa.Column("default_service_fee_iqd", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    # Production upgrades are intentionally additive. A manual rollback may
    # remove the column only after verifying that no newer application uses it.
    pass
