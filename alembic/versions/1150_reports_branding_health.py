"""V11.5 branded reports, menu revisions, and health history.

Revision ID: 1150_reports_branding_health
Revises: 1140_owner_commerce
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "1150_reports_branding_health"
down_revision = "1140_owner_commerce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cp_report_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("cp_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("format", sa.String(12), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("filename", sa.String(255), nullable=False, server_default=""),
        sa.Column("media_type", sa.String(100), nullable=False, server_default="application/octet-stream"),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("report_id", "format", name="uq_cp_report_artifact_format"),
    )
    op.create_index("ix_cp_report_artifacts_report_id", "cp_report_artifacts", ["report_id"])
    op.create_index("ix_cp_report_artifacts_format", "cp_report_artifacts", ["format"])
    op.create_index("ix_cp_report_artifacts_sha256", "cp_report_artifacts", ["sha256"])
    op.create_index("ix_cp_report_artifact_status_created", "cp_report_artifacts", ["status", "created_at"])

    op.create_table(
        "cp_daily_provider_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("cp_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("orders_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_or_problem_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_subscriptions_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sales_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bot_fees_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_net_iqd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("average_confirmation_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider_id", "metric_date", name="uq_cp_provider_metric_day"),
    )
    op.create_index("ix_cp_daily_provider_metrics_provider_id", "cp_daily_provider_metrics", ["provider_id"])
    op.create_index("ix_cp_provider_metric_date", "cp_daily_provider_metrics", ["metric_date", "provider_id"])

    op.create_table(
        "cp_menu_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(160), nullable=False, server_default=""),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("cp_users.id"), nullable=True),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("revision", name="uq_cp_menu_revision_number"),
    )
    op.create_index("ix_cp_menu_revisions_revision", "cp_menu_revisions", ["revision"], unique=True)
    op.create_index("ix_cp_menu_revisions_checksum", "cp_menu_revisions", ["checksum"])
    op.create_index("ix_cp_menu_revision_created", "cp_menu_revisions", ["created_at"])

    op.create_table(
        "cp_system_health_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("release_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("runtime_mode", sa.String(30), nullable=False, server_default=""),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("checks_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cp_system_health_status_created", "cp_system_health_snapshots", ["status", "created_at"])


def downgrade() -> None:
    op.drop_table("cp_system_health_snapshots")
    op.drop_table("cp_menu_revisions")
    op.drop_table("cp_daily_provider_metrics")
    op.drop_table("cp_report_artifacts")
