from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import Database
from app.db.models import Provider, ProviderStaff, SystemSetting, User


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only audit for provider ownership and staff consistency."
    )
    parser.add_argument("--json", type=Path, help="Optional destination for the count-only report")
    return parser.parse_args()


async def build_report() -> dict[str, object]:
    settings = get_settings()
    database = Database(settings)
    try:
        async with database.session_factory() as session:
            title = func.lower(func.trim(func.coalesce(ProviderStaff.title, "")))
            role = func.upper(func.trim(func.coalesce(ProviderStaff.role, "")))
            explicit_owner = (role == "OWNER") | title.in_(("owner", "مالك", "platform_owner", "provider_owner"))

            owner_counts = list(
                (
                    await session.execute(
                        select(ProviderStaff.provider_id, func.count(ProviderStaff.id))
                        .where(explicit_owner)
                        .group_by(ProviderStaff.provider_id)
                    )
                ).all()
            )
            ambiguous_owner_groups = sum(1 for _provider_id, count in owner_counts if int(count) > 1)
            missing_owner_groups = int(
                await session.scalar(
                    select(func.count(Provider.id)).where(
                        ~Provider.id.in_(select(ProviderStaff.provider_id).where(explicit_owner))
                    )
                )
                or 0
            )
            inactive_owner_rows = int(
                await session.scalar(
                    select(func.count(ProviderStaff.id)).where(
                        explicit_owner, ProviderStaff.is_active.is_(False)
                    )
                )
                or 0
            )
            orphan_staff_rows = int(
                await session.scalar(
                    select(func.count(ProviderStaff.id))
                    .outerjoin(User, User.id == ProviderStaff.user_id)
                    .outerjoin(Provider, Provider.id == ProviderStaff.provider_id)
                    .where((User.id.is_(None)) | (Provider.id.is_(None)))
                )
                or 0
            )
            duplicate_memberships = int(
                await session.scalar(
                    select(func.count()).select_from(
                        select(ProviderStaff.provider_id, ProviderStaff.user_id)
                        .group_by(ProviderStaff.provider_id, ProviderStaff.user_id)
                        .having(func.count(ProviderStaff.id) > 1)
                        .subquery()
                    )
                )
                or 0
            )
            active_settings = list(
                (
                    await session.execute(
                        select(SystemSetting.key, SystemSetting.value).where(
                            SystemSetting.key.like("provider.active.%")
                        )
                    )
                ).all()
            )
            malformed_active_selections = 0
            for key, value in active_settings:
                try:
                    int(str(key).rsplit(".", 1)[1])
                    int(value)
                except (TypeError, ValueError, IndexError):
                    malformed_active_selections += 1

            role_counts = Counter(
                str(value or "UNSET").upper()
                for value in (
                    await session.scalars(select(ProviderStaff.role))
                ).all()
            )
            return {
                "schema": "campuspass-provider-access-audit-v1",
                "read_only": True,
                "counts": {
                    "providers": int(await session.scalar(select(func.count(Provider.id))) or 0),
                    "staff_rows": int(await session.scalar(select(func.count(ProviderStaff.id))) or 0),
                    "ambiguous_owner_groups": ambiguous_owner_groups,
                    "providers_without_explicit_owner": missing_owner_groups,
                    "inactive_owner_rows": inactive_owner_rows,
                    "orphan_staff_rows": orphan_staff_rows,
                    "duplicate_provider_user_memberships": duplicate_memberships,
                    "malformed_active_provider_settings": malformed_active_selections,
                },
                "role_counts": dict(sorted(role_counts.items())),
                "note": "No Telegram IDs, tokens, URLs, or personal data are included.",
            }
    finally:
        await database.close()


async def main() -> None:
    args = parse_args()
    report = await build_report()
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
