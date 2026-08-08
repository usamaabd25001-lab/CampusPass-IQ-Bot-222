"""CampusPass V6.9 operations baseline.

Revision ID: 690_operations_baseline
Revises: None

The existing additive migration runner remains authoritative for upgrades from
older releases. This Alembic revision establishes the reviewed V6.9 metadata
baseline so structural migrations after the Phase 6 restore drill can be
managed and code-reviewed with Alembic.
"""

revision = "690_operations_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade is disabled; restore a verified backup instead")
