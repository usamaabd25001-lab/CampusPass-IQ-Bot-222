"""V11.7.1 activate optional integrations with readiness gates.

Revision ID: 1171_all_features_ready
Revises: 1170_lts_turbo_update_safe
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "1171_all_features_ready"
down_revision = "1170_lts_turbo_update_safe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE cp_feature_flags SET is_enabled = TRUE "
            "WHERE key IN ('gemini', 'mastercard')"
        )
    )


def downgrade() -> None:
    # Feature activation is intentionally not reverted during schema rollback.
    # Owners can disable either feature from the runtime feature panel.
    pass
