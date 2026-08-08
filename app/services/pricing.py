from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FeatureBillingMode, FeaturePrice, PriceChangeLog, SystemSetting, User

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


@dataclass(slots=True, frozen=True)
class PriceValidation:
    value: int
    formatted: str
    words: str
    suspiciously_low: bool
    suggested_value: int | None = None


class PriceService:
    """Owner-controlled price storage and safe IQD input validation.

    No commercial price is hard-coded in handlers. Defaults may be seeded, but the
    effective value is always read from the database and can be changed by the owner.
    """

    DEFAULT_MIN_IQD = 1_000

    @staticmethod
    def normalize_digits(value: str) -> str:
        return (value or "").translate(_ARABIC_DIGITS)

    @classmethod
    def parse_iqd(cls, raw: str, *, allow_zero: bool = False, maximum: int = 2_000_000_000) -> int:
        normalized = cls.normalize_digits(raw).strip()
        normalized = normalized.replace(",", "").replace("٬", "").replace(" ", "")
        normalized = normalized.replace("د.ع", "").replace("دينار", "")
        if not re.fullmatch(r"\d+", normalized):
            raise ValueError("اكتب الرقم فقط، مثال: 10000")
        value = int(normalized)
        minimum = 0 if allow_zero else 1
        if not minimum <= value <= maximum:
            raise ValueError(f"السعر يجب أن يكون بين {minimum:,} و{maximum:,} د.ع")
        return value

    @classmethod
    def iqd_words(cls, value: int) -> str:
        # Deliberately concise and deterministic. It covers the ranges commonly used
        # in the platform and falls back to a formatted number for larger values.
        units = {
            0: "صفر",
            1: "واحد",
            2: "اثنان",
            3: "ثلاثة",
            4: "أربعة",
            5: "خمسة",
            6: "ستة",
            7: "سبعة",
            8: "ثمانية",
            9: "تسعة",
            10: "عشرة",
            11: "أحد عشر",
            12: "اثنا عشر",
            13: "ثلاثة عشر",
            14: "أربعة عشر",
            15: "خمسة عشر",
            16: "ستة عشر",
            17: "سبعة عشر",
            18: "ثمانية عشر",
            19: "تسعة عشر",
        }
        tens = {
            20: "عشرون",
            30: "ثلاثون",
            40: "أربعون",
            50: "خمسون",
            60: "ستون",
            70: "سبعون",
            80: "ثمانون",
            90: "تسعون",
        }
        hundreds = {
            100: "مئة",
            200: "مئتان",
            300: "ثلاثمئة",
            400: "أربعمئة",
            500: "خمسمئة",
            600: "ستمئة",
            700: "سبعمئة",
            800: "ثمانمئة",
            900: "تسعمئة",
        }

        def under_1000(number: int) -> str:
            parts: list[str] = []
            if number >= 100:
                h = number // 100 * 100
                parts.append(hundreds[h])
                number %= 100
            if number:
                if parts:
                    parts.append("و")
                if number < 20:
                    parts.append(units[number])
                else:
                    u = number % 10
                    t = number - u
                    if u:
                        parts.extend([units[u], "و", tens[t]])
                    else:
                        parts.append(tens[t])
            return " ".join(parts) or units[0]

        if value < 1000:
            return f"{under_1000(value)} دينار"
        if value < 1_000_000:
            thousands, rest = divmod(value, 1000)
            if thousands == 1:
                head = "ألف"
            elif thousands == 2:
                head = "ألفان"
            elif 3 <= thousands <= 10:
                head = f"{under_1000(thousands)} آلاف"
            else:
                head = f"{under_1000(thousands)} ألف"
            return f"{head}{' و' + under_1000(rest) if rest else ''} دينار"
        if value < 1_000_000_000:
            millions, rest = divmod(value, 1_000_000)
            if millions == 1:
                head = "مليون"
            elif millions == 2:
                head = "مليونان"
            elif 3 <= millions <= 10:
                head = f"{under_1000(millions)} ملايين"
            else:
                head = f"{under_1000(millions)} مليون"
            tail = ""
            if rest:
                tail = f" و{cls.iqd_words(rest).removesuffix(' دينار')}"
            return f"{head}{tail} دينار"
        return f"{value:,} دينار عراقي"

    async def minimum_offer_price(self, session: AsyncSession) -> int:
        raw = await session.scalar(
            select(SystemSetting.value).where(SystemSetting.key == "minimum_offer_price_iqd")
        )
        try:
            return max(1, int(raw or self.DEFAULT_MIN_IQD))
        except ValueError:
            return self.DEFAULT_MIN_IQD

    async def validate_offer_price(self, session: AsyncSession, raw: str) -> PriceValidation:
        value = self.parse_iqd(raw)
        minimum = await self.minimum_offer_price(session)
        suspicious = value < minimum
        suggested = value * 1000 if 1 <= value < 250 else None
        return PriceValidation(
            value=value,
            formatted=f"{value:,} د.ع",
            words=self.iqd_words(value),
            suspiciously_low=suspicious,
            suggested_value=suggested,
        )

    async def get_system_price(self, session: AsyncSession, key: str, default: int = 0) -> int:
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == f"price.{key}"))
        if not row:
            row = SystemSetting(key=f"price.{key}", value=str(max(0, default)))
            session.add(row)
            await session.flush()
        try:
            return max(0, int(row.value))
        except ValueError:
            return max(0, default)

    async def log_price_change(
        self,
        session: AsyncSession,
        *,
        key: str,
        old_value: int | None,
        new_value: int,
        actor: User | None,
        reason: str = "",
    ) -> None:
        session.add(
            PriceChangeLog(
                actor_user_id=actor.id if actor else None,
                price_key=key[:160],
                old_value_iqd=old_value,
                new_value_iqd=new_value,
                reason=reason[:1000],
            )
        )
        await session.flush()

    async def set_system_price(
        self,
        session: AsyncSession,
        key: str,
        value: int,
        actor: User | None,
        reason: str = "",
    ) -> int:
        if value < 0:
            raise ValueError("السعر لا يمكن أن يكون سالبًا")
        setting_key = f"price.{key}"
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == setting_key))
        old_value: int | None = None
        if row:
            try:
                old_value = int(row.value)
            except ValueError:
                old_value = None
            row.value = str(value)
            row.updated_by_user_id = actor.id if actor else None
        else:
            session.add(
                SystemSetting(
                    key=setting_key,
                    value=str(value),
                    updated_by_user_id=actor.id if actor else None,
                )
            )
        await self.log_price_change(
            session,
            key=setting_key,
            old_value=old_value,
            new_value=value,
            actor=actor,
            reason=reason,
        )
        return value

    async def feature_price(
        self,
        session: AsyncSession,
        feature_key: str,
        name_ar: str | None = None,
    ) -> FeaturePrice:
        row = await session.scalar(
            select(FeaturePrice).where(FeaturePrice.feature_key == feature_key)
        )
        if not row:
            row = FeaturePrice(
                feature_key=feature_key,
                name_ar=name_ar or feature_key,
                billing_mode=FeatureBillingMode.FREE.value,
            )
            session.add(row)
            await session.flush()
        return row
