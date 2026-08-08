"""V11.6 durable webhook and deployment gates.

Revision ID: 1160_render_e2e_hardening
Revises: 1150_reports_branding_health
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "1160_render_e2e_hardening"
down_revision = "1150_reports_branding_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cp_telegram_update_inbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(160), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_id", sa.String(160), nullable=False, server_default=""),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("update_id", name="uq_cp_telegram_update_id"),
    )
    op.create_index("ix_cp_telegram_update_inbox_update_id", "cp_telegram_update_inbox", ["update_id"], unique=True)
    op.create_index("ix_cp_telegram_update_inbox_payload_sha256", "cp_telegram_update_inbox", ["payload_sha256"])
    op.create_index("ix_cp_telegram_update_inbox_status", "cp_telegram_update_inbox", ["status"])
    op.create_index("ix_cp_telegram_update_inbox_available_at", "cp_telegram_update_inbox", ["available_at"])
    op.create_index("ix_cp_telegram_update_inbox_lease_owner", "cp_telegram_update_inbox", ["lease_owner"])
    op.create_index("ix_cp_telegram_update_inbox_lease_expires_at", "cp_telegram_update_inbox", ["lease_expires_at"])
    op.create_index("ix_cp_telegram_update_claim", "cp_telegram_update_inbox", ["status", "available_at", "update_id"])
    op.create_index("ix_cp_telegram_update_lease", "cp_telegram_update_inbox", ["lease_expires_at"])

    op.create_table(
        "cp_deployment_gate_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(40), nullable=False),
        sa.Column("release_id", sa.String(160), nullable=False),
        sa.Column("environment", sa.String(30), nullable=False, server_default=""),
        sa.Column("runtime_mode", sa.String(30), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("checks_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("public_id", name="uq_cp_deployment_gate_public_id"),
    )
    op.create_index("ix_cp_deployment_gate_runs_public_id", "cp_deployment_gate_runs", ["public_id"], unique=True)
    op.create_index("ix_cp_deployment_gate_runs_release_id", "cp_deployment_gate_runs", ["release_id"])
    op.create_index("ix_cp_deployment_gate_runs_status", "cp_deployment_gate_runs", ["status"])
    op.create_index("ix_cp_deployment_gate_release_started", "cp_deployment_gate_runs", ["release_id", "started_at"])
    op.create_index("ix_cp_deployment_gate_status_started", "cp_deployment_gate_runs", ["status", "started_at"])


def downgrade() -> None:
    op.drop_table("cp_deployment_gate_runs")
    op.drop_table("cp_telegram_update_inbox")
