from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db.models import ModuleRecord


@dataclass(frozen=True, slots=True)
class BuiltinModule:
    key: str
    name_ar: str
    critical: bool = False


BUILTIN_MODULES: tuple[BuiltinModule, ...] = (
    BuiltinModule("users", "المستخدمون والتسجيل", True),
    BuiltinModule("ui", "الواجهة والقوائم", True),
    BuiltinModule("catalog", "المنصات والأقسام والخدمات والعروض", True),
    BuiltinModule("orders", "الطلبات والحجوزات", True),
    BuiltinModule("payments", "الدفع ومراجعة الإثباتات", True),
    BuiltinModule("inventory", "المخزون والتسليم الآمن", True),
    BuiltinModule("student_subscriptions", "اشتراكات الطلاب والوصول", True),
    BuiltinModule("email_codes", "رموز التحقق عبر البريد"),
    BuiltinModule("support", "الدعم والتذاكر"),
    BuiltinModule("reports", "التقارير"),
    BuiltinModule("provider_plans", "باقات المنصات والصلاحيات"),
    BuiltinModule("workflow", "محرك خطوات الطلب", True),
    BuiltinModule("message_templates", "قوالب الرسائل"),
    BuiltinModule("health", "فحص صحة النظام", True),
)


class ModuleRegistryService:
    async def sync(self, session: AsyncSession) -> list[ModuleRecord]:
        rows: list[ModuleRecord] = []
        for module in BUILTIN_MODULES:
            row = await session.scalar(
                select(ModuleRecord).where(ModuleRecord.module_key == module.key)
            )
            if not row:
                row = ModuleRecord(
                    module_key=module.key,
                    name_ar=module.name_ar,
                    version=__version__,
                    is_critical=module.critical,
                    health_status="unknown",
                )
                session.add(row)
            else:
                row.name_ar = module.name_ar
                row.version = __version__
                row.is_critical = module.critical
            rows.append(row)
        await session.flush()
        return rows

    async def list(self, session: AsyncSession) -> list[ModuleRecord]:
        await self.sync(session)
        return list(
            (
                await session.scalars(
                    select(ModuleRecord).order_by(ModuleRecord.is_critical.desc(), ModuleRecord.id)
                )
            ).all()
        )

    async def mark_health(
        self,
        session: AsyncSession,
        module_key: str,
        status: str,
        error: str | None = None,
    ) -> None:
        row = await session.scalar(
            select(ModuleRecord).where(ModuleRecord.module_key == module_key)
        )
        if not row:
            await self.sync(session)
            row = await session.scalar(
                select(ModuleRecord).where(ModuleRecord.module_key == module_key)
            )
        if row:
            row.health_status = status
            row.last_error = error[:2000] if error else None
            row.checked_at = datetime.now(UTC)
            await session.flush()
