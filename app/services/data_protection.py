from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import SecretBox
from app.db.models import Order, SecretAccessLog, StudentProfile, User

_SENSITIVE_KEY_RE = re.compile(
    r"password|passcode|otp|token|secret|card|cvv|pin|رمز|كلمة.?مرور|بطاقة",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?964|0)?7\d{9}(?!\d)")
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_LONG_NUMBER_RE = re.compile(r"(?<!\d)\d{8,}(?!\d)")


class DataProtectionService:
    """Encryption and redaction boundary for CampusPass V11.

    This service intentionally contains no user-facing privacy-request workflow.
    It only protects sensitive data required for normal operation and audit.
    """

    PROFILE_KEY_VERSION = 1
    ACTIVATION_KEY_VERSION = 1

    def __init__(self, settings: Settings, secrets: SecretBox) -> None:
        self.settings = settings
        self.secrets = secrets

    @staticmethod
    def mask_name(value: str) -> str:
        words = [part for part in value.strip().split() if part]
        if not words:
            return "مستخدم"
        return " ".join(word[0] + "***" for word in words[:3])

    @staticmethod
    def mask_phone(value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) < 4:
            return "***"
        return f"***{digits[-4:]}"

    def _encrypt_json(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return self.secrets.encrypt(raw)

    def _decrypt_json(self, value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        parsed = json.loads(self.secrets.decrypt(value))
        return parsed if isinstance(parsed, dict) else {}

    async def protect_profile(
        self,
        session: AsyncSession,
        profile: StudentProfile,
        full_name: str,
        phone: str,
    ) -> StudentProfile:
        profile.private_data_encrypted = self._encrypt_json(
            {"full_name": full_name.strip(), "phone": phone.strip()}
        )
        profile.private_data_key_version = self.PROFILE_KEY_VERSION
        profile.pii_protected_at = datetime.now(UTC)
        profile.full_name = self.mask_name(full_name)
        profile.phone = self.mask_phone(phone)
        await session.flush()
        return profile

    def profile_data(self, profile: StudentProfile | None) -> dict[str, str]:
        if not profile:
            return {}
        protected = self._decrypt_json(profile.private_data_encrypted)
        return {
            "full_name": str(protected.get("full_name") or profile.full_name or ""),
            "phone": str(protected.get("phone") or profile.phone or ""),
            "governorate": profile.governorate,
            "university": profile.university,
            "college": profile.college,
            "department": profile.department,
            "stage": profile.stage,
        }

    async def protect_order_activation(
        self,
        session: AsyncSession,
        order: Order,
        activation_data: dict[str, Any],
    ) -> None:
        clean = dict(activation_data or {})
        order.activation_data_encrypted = self._encrypt_json(clean)
        order.activation_data_key_version = self.ACTIVATION_KEY_VERSION
        order.activation_data_protected_at = datetime.now(UTC)
        order.activation_data = self.mask_mapping(clean)
        await session.flush()

    def order_activation_data(self, order: Order) -> dict[str, Any]:
        protected = self._decrypt_json(order.activation_data_encrypted)
        return protected or dict(order.activation_data or {})

    async def reveal_order_activation(
        self,
        session: AsyncSession,
        order: Order,
        actor: User,
        purpose: str,
        allowed: bool,
    ) -> dict[str, Any]:
        if not allowed:
            raise PermissionError("غير مصرح بعرض بيانات التفعيل")
        data = self.order_activation_data(order)
        session.add(
            SecretAccessLog(
                actor_user_id=actor.id,
                subject_user_id=order.user_id,
                entity_type="order_activation",
                entity_id=str(order.id),
                purpose=purpose[:160],
                fields=list(data.keys()),
            )
        )
        await session.flush()
        return data

    @classmethod
    def mask_mapping(cls, value: Any) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if _SENSITIVE_KEY_RE.search(str(key)):
                    result[str(key)] = "***"
                elif isinstance(item, (dict, list)):
                    result[str(key)] = cls.mask_mapping(item)
                else:
                    text = str(item)
                    result[str(key)] = text if len(text) <= 3 else f"{text[:2]}***"
            return result
        if isinstance(value, list):
            return [cls.mask_mapping(item) for item in value]
        return "***"

    @staticmethod
    def redact_for_ai(text: str) -> str:
        value = text or ""
        value = _EMAIL_RE.sub("[EMAIL_REDACTED]", value)
        value = _PHONE_RE.sub("[PHONE_REDACTED]", value)
        value = _CARD_RE.sub("[CARD_REDACTED]", value)
        value = _LONG_NUMBER_RE.sub("[NUMBER_REDACTED]", value)
        lines: list[str] = []
        for line in value.splitlines():
            if _SENSITIVE_KEY_RE.search(line):
                key = line.split(":", 1)[0][:80]
                lines.append(f"{key}: [SECRET_REDACTED]")
            else:
                lines.append(line)
        return "\n".join(lines)[:5000]

    async def protect_legacy_rows(self, session: AsyncSession, batch_size: int = 100) -> int:
        """One-way encryption backfill retained for safe V10-to-V11 migration."""
        limit = max(1, min(batch_size, 500))
        profiles = list(
            (
                await session.scalars(
                    select(StudentProfile)
                    .where(StudentProfile.private_data_encrypted.is_(None))
                    .limit(limit)
                )
            ).all()
        )
        for profile in profiles:
            await self.protect_profile(session, profile, profile.full_name, profile.phone)

        orders = list(
            (
                await session.scalars(
                    select(Order)
                    .where(Order.activation_data_encrypted.is_(None))
                    .limit(limit)
                )
            ).all()
        )
        for order in orders:
            await self.protect_order_activation(session, order, dict(order.activation_data or {}))
        return len(profiles) + len(orders)
