from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.telegram_webapp import VerifiedInitData
from app.domain.student_commerce import profile_completion
from app.services.data_protection import DataProtectionService
from app.services.users import UserService
from app.services.webapp_validation import (
    normalize_iraqi_phone,
    validate_governorate,
    validate_person_full_name,
    validate_required_human_text,
)


@dataclass(frozen=True, slots=True)
class ProfilePayload:
    full_name: str
    phone: str
    governorate: str
    university: str
    college: str
    department: str
    stage: str

    def as_dict(self) -> dict[str, str]:
        return {
            "full_name": self.full_name,
            "phone": self.phone,
            "governorate": self.governorate,
            "university": self.university,
            "college": self.college,
            "department": self.department,
            "stage": self.stage,
        }


class WebAppProfileService:
    def __init__(self, users: UserService, data_protection: DataProtectionService) -> None:
        self.users = users
        self.data_protection = data_protection

    async def read(self, session: AsyncSession, verified: VerifiedInitData) -> dict:
        user = await self.users.get_or_create(
            session,
            verified.user.id,
            verified.user.username,
            verified.user.full_name or "Telegram User",
        )
        if not user.profile:
            return {
                "exists": False,
                "complete": False,
                "missing_fields": list(profile_completion(None).missing_fields),
                "profile": {
                    "full_name": verified.user.full_name,
                    "phone": "",
                    "governorate": "",
                    "university": "",
                    "college": "",
                    "department": "",
                    "stage": "",
                },
            }
        private = self.data_protection.profile_data(user.profile)
        values = {
            "full_name": str(private.get("full_name") or user.profile.full_name or ""),
            "phone": str(private.get("phone") or user.profile.phone or ""),
            "governorate": user.profile.governorate,
            "university": user.profile.university,
            "college": user.profile.college,
            "department": user.profile.department,
            "stage": user.profile.stage,
        }
        completion = profile_completion(values)
        return {
            "exists": True,
            "complete": completion.complete,
            "missing_fields": list(completion.missing_fields),
            "profile": values,
        }

    async def save(
        self,
        session: AsyncSession,
        verified: VerifiedInitData,
        payload: ProfilePayload,
    ) -> dict:
        values = {
            "full_name": validate_person_full_name(payload.full_name),
            "phone": normalize_iraqi_phone(payload.phone),
            "governorate": validate_governorate(payload.governorate),
            "university": validate_required_human_text(
                payload.university,
                label="الجامعة أو المعهد",
                min_length=2,
                max_length=180,
            ),
            "college": validate_required_human_text(
                payload.college,
                label="الكلية",
                min_length=2,
                max_length=180,
            ),
            "department": validate_required_human_text(
                payload.department,
                label="القسم أو الاختصاص",
                min_length=2,
                max_length=180,
            ),
            "stage": validate_required_human_text(
                payload.stage,
                label="المرحلة",
                min_length=1,
                max_length=80,
                min_letters=1,
            ),
        }
        completion = profile_completion(values)
        if not completion.complete:
            raise ValueError("جميع حقول الملف الشخصي مطلوبة")
        user = await self.users.get_or_create(
            session,
            verified.user.id,
            verified.user.username,
            verified.user.full_name or values["full_name"],
        )
        profile = await self.users.save_profile(
            session,
            user,
            values,
            count_edit=user.profile is not None,
        )
        return {
            "ok": True,
            "user_id": user.id,
            "profile_id": profile.id,
            "complete": True,
        }
