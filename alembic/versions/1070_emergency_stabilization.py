"""CampusPass emergency stabilization: typed provider roles and branding permission.

Revision ID: 1070_emergency_stabilization
Revises: 1060_platform_access_referral_cleanup

The migration is additive and reversible. Existing staff rows are retained; the
new role column is backfilled from explicit historic titles only. Ambiguous
providers are counted in a non-sensitive SystemSetting audit report.
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa

revision = "1070_emergency_stabilization"
down_revision = "1060_platform_access_referral_cleanup"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {
        str(item.get("name"))
        for item in sa.inspect(op.get_bind()).get_columns(table_name)
        if item.get("name")
    }


def _indexes(table_name: str) -> set[str]:
    return {
        str(item.get("name"))
        for item in sa.inspect(op.get_bind()).get_indexes(table_name)
        if item.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "cp_provider_staff" in tables:
        columns = _columns("cp_provider_staff")
        if "role" not in columns:
            op.add_column(
                "cp_provider_staff",
                sa.Column("role", sa.String(length=20), nullable=False, server_default="STAFF"),
            )
        if "can_manage_branding" not in columns:
            op.add_column(
                "cp_provider_staff",
                sa.Column(
                    "can_manage_branding",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )

        # Backfill only explicit titles. Rows without a clear title stay STAFF;
        # no ownership is guessed from broad boolean permissions.
        bind.execute(
            sa.text(
                "UPDATE cp_provider_staff SET role = 'OWNER' "
                "WHERE LOWER(TRIM(title)) IN ('owner','platform_owner','provider_owner','مالك')"
            )
        )
        bind.execute(
            sa.text(
                "UPDATE cp_provider_staff SET role = 'MANAGER' "
                "WHERE role <> 'OWNER' AND LOWER(TRIM(title)) IN "
                "('manager','admin','administrator','مدير')"
            )
        )
        bind.execute(
            sa.text(
                "UPDATE cp_provider_staff SET can_manage_branding = true "
                "WHERE role = 'OWNER'"
            )
        )
        indexes = _indexes("cp_provider_staff")
        if "ix_cp_provider_staff_role" not in indexes:
            op.create_index("ix_cp_provider_staff_role", "cp_provider_staff", ["role"])
        if "ix_cp_provider_staff_user_active" not in indexes:
            op.create_index(
                "ix_cp_provider_staff_user_active",
                "cp_provider_staff",
                ["user_id", "is_active"],
            )
        if "ix_cp_provider_staff_provider_active" not in indexes:
            op.create_index(
                "ix_cp_provider_staff_provider_active",
                "cp_provider_staff",
                ["provider_id", "is_active"],
            )

    if "cp_system_settings" in tables:
        duplicate_owners = 0
        inactive_owners = 0
        orphan_staff = 0
        if "cp_provider_staff" in tables:
            duplicate_owners = int(
                bind.execute(
                    sa.text(
                        "SELECT COUNT(*) FROM ("
                        "SELECT provider_id FROM cp_provider_staff WHERE role = 'OWNER' "
                        "GROUP BY provider_id HAVING COUNT(*) > 1"
                        ") AS ambiguous_owner_groups"
                    )
                ).scalar()
                or 0
            )
            inactive_owners = int(
                bind.execute(
                    sa.text(
                        "SELECT COUNT(*) FROM cp_provider_staff "
                        "WHERE role = 'OWNER' AND is_active = false"
                    )
                ).scalar()
                or 0
            )
            if {"cp_users", "cp_providers"}.issubset(tables):
                orphan_staff = int(
                    bind.execute(
                        sa.text(
                            "SELECT COUNT(*) FROM cp_provider_staff s "
                            "LEFT JOIN cp_users u ON u.id = s.user_id "
                            "LEFT JOIN cp_providers p ON p.id = s.provider_id "
                            "WHERE u.id IS NULL OR p.id IS NULL"
                        )
                    ).scalar()
                    or 0
                )
        report = json.dumps(
            {
                "duplicate_owner_provider_groups": duplicate_owners,
                "inactive_owner_rows": inactive_owners,
                "orphan_staff_rows": orphan_staff,
                "note": "Ambiguous rows were reported and not reassigned automatically.",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        defaults = (
            ("provider_access.backfill_report", report),
            ("branding.moderation.provider", "disabled"),
            ("branding.moderation.fail_closed", "false"),
            ("operations.release_version", "10.7.0-emergency-stabilization"),
        )
        for key, value in defaults:
            bind.execute(
                sa.text(
                    "INSERT INTO cp_system_settings (key, value, is_secret, updated_at) "
                    "VALUES (:key, :value, false, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
                    "updated_at = CURRENT_TIMESTAMP"
                ),
                {"key": key, "value": value},
            )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "cp_system_settings" in tables:
        bind.execute(
            sa.text(
                "DELETE FROM cp_system_settings WHERE key IN "
                "('provider_access.backfill_report', 'operations.release_version')"
            )
        )
    if "cp_provider_staff" not in tables:
        return
    indexes = _indexes("cp_provider_staff")
    for index_name in (
        "ix_cp_provider_staff_provider_active",
        "ix_cp_provider_staff_user_active",
        "ix_cp_provider_staff_role",
    ):
        if index_name in indexes:
            op.drop_index(index_name, table_name="cp_provider_staff")
    columns = _columns("cp_provider_staff")
    if "can_manage_branding" in columns:
        op.drop_column("cp_provider_staff", "can_manage_branding")
    if "role" in columns:
        op.drop_column("cp_provider_staff", "role")
