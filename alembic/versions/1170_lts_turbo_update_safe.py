"""V11.7 LTS turbo and update-safe runtime.

Revision ID: 1170_lts_turbo_update_safe
Revises: 1160_render_e2e_hardening
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "1170_lts_turbo_update_safe"
down_revision = "1160_render_e2e_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cp_runtime_config_generations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("namespace", sa.String(80), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(255), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("namespace", name="uq_cp_runtime_config_namespace"),
    )
    op.create_index(
        "ix_cp_runtime_config_generations_namespace",
        "cp_runtime_config_generations",
        ["namespace"],
        unique=True,
    )
    op.create_index(
        "ix_cp_runtime_config_updated",
        "cp_runtime_config_generations",
        ["updated_at"],
    )

    op.create_table(
        "cp_release_compatibility",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("release_id", sa.String(160), nullable=False),
        sa.Column("version", sa.String(100), nullable=False, server_default=""),
        sa.Column("schema_head", sa.String(160), nullable=False, server_default=""),
        sa.Column("minimum_release_version", sa.String(100), nullable=False, server_default=""),
        sa.Column("minimum_schema_head", sa.String(160), nullable=False, server_default=""),
        sa.Column("callback_schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rollout_percent", sa.Float(), nullable=False, server_default="100"),
        sa.Column("status", sa.String(20), nullable=False, server_default="starting"),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("release_id", name="uq_cp_release_compatibility_release"),
    )
    op.create_index(
        "ix_cp_release_compatibility_release_id",
        "cp_release_compatibility",
        ["release_id"],
        unique=True,
    )
    op.create_index(
        "ix_cp_release_compatibility_status_checked",
        "cp_release_compatibility",
        ["status", "checked_at"],
    )

    generations = sa.table(
        "cp_runtime_config_generations",
        sa.column("namespace", sa.String),
        sa.column("generation", sa.Integer),
        sa.column("reason", sa.String),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    from datetime import UTC, datetime

    op.bulk_insert(
        generations,
        [
            {
                "namespace": namespace,
                "generation": 1,
                "reason": "v11.7 initial generation",
                "updated_at": datetime.now(UTC),
            }
            for namespace in ("menus", "features", "templates", "branding")
        ],
    )


def downgrade() -> None:
    op.drop_table("cp_release_compatibility")
    op.drop_table("cp_runtime_config_generations")
