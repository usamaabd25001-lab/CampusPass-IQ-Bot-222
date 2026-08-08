from __future__ import annotations

import base64
import io
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.types import BufferedInputFile, PhotoSize
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Provider, ProviderBrandProfile, SystemSetting
from app.domain.branding_palette import BrandPalette, extract_brand_palette
from app.services.image_moderation import ImageModerationService


@dataclass(frozen=True, slots=True)
class BrandingCandidate:
    file_id: str
    file_unique_id: str
    file_size: int
    image_format: str
    width: int
    height: int
    primary_color: str = "#0B4AA9"
    secondary_color: str = "#14A5A2"
    dark_color: str = "#003279"
    warning: str | None = None

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


class BrandingService:
    """Local, deterministic provider branding pipeline.

    Telegram remains the source for uploaded media. Pillow validates and normalizes
    the image locally, extracts an accessible palette, and persists a bounded PNG
    data URI so Free, Plus and Pro reports can embed the exact provider logo without
    relying on temporary Telegram file URLs.
    """

    MAX_LOGO_BYTES = 8_000_000
    MAX_PIXELS = 20_000_000
    MIN_DIMENSION = 128
    MAX_EMBED_DIMENSION = 1200
    MAX_EMBED_BYTES = 1_800_000
    SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP"}

    def __init__(self, bot: Bot, settings: Settings) -> None:
        self.bot = bot
        self.settings = settings
        self.moderation = ImageModerationService(settings)

    @staticmethod
    def has_logo(provider: Provider) -> bool:
        return bool(provider.logo_file_id)

    async def _download(self, file_id: str) -> bytes:
        telegram_file = await self.bot.get_file(file_id)
        if not telegram_file.file_path:
            raise ValueError("تعذر قراءة ملف الشعار من تيليجرام.")
        buffer = io.BytesIO()
        await self.bot.download_file(telegram_file.file_path, destination=buffer)
        raw = buffer.getvalue()
        if not raw:
            raise ValueError("ملف الشعار فارغ.")
        if len(raw) > self.MAX_LOGO_BYTES:
            raise ValueError("حجم الشعار كبير جدًا. الحد الأقصى 8MB.")
        return raw

    @classmethod
    def _inspect(cls, raw: bytes) -> tuple[str, int, int, BrandPalette]:
        try:
            with Image.open(io.BytesIO(raw)) as image:
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                image_format = (image.format or "").upper()
                width, height = map(int, image.size)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValueError("الملف المرفوع ليس صورة سليمة.") from exc
        if image_format not in cls.SUPPORTED_FORMATS:
            raise ValueError("صيغة الشعار غير مدعومة. استخدم JPG أو PNG أو WebP.")
        if width < cls.MIN_DIMENSION or height < cls.MIN_DIMENSION:
            raise ValueError("دقة الشعار منخفضة. الحد الأدنى 128×128 بكسل.")
        if width * height > cls.MAX_PIXELS:
            raise ValueError("أبعاد الشعار كبيرة جدًا.")
        return image_format, width, height, extract_brand_palette(raw)

    async def validate_photo(self, photo: PhotoSize) -> BrandingCandidate:
        if not photo or not photo.file_id:
            raise ValueError("أرسل شعار المنصة كصورة داخل تيليجرام.")
        declared_size = int(photo.file_size or 0)
        if declared_size and declared_size > self.MAX_LOGO_BYTES:
            raise ValueError("حجم الشعار كبير جدًا. الحد الأقصى 8MB.")
        raw = await self._download(photo.file_id)
        await self.moderation.ensure_safe(raw)
        image_format, width, height, palette = self._inspect(raw)
        ratio = width / height
        warning = None
        if not 0.95 <= ratio <= 1.05:
            warning = "سيستخدم الشعار الأفقي في الترويسة، ويُفضّل إضافة نسخة مربعة للأيقونة."
        return BrandingCandidate(
            file_id=photo.file_id,
            file_unique_id=photo.file_unique_id,
            file_size=len(raw),
            image_format=image_format,
            width=width,
            height=height,
            primary_color=palette.primary,
            secondary_color=palette.secondary,
            dark_color=palette.dark,
            warning=warning,
        )

    @classmethod
    def _normalized_data_uri(cls, raw: bytes) -> str:
        with Image.open(io.BytesIO(raw)) as source:
            image = source.convert("RGBA")
            image.thumbnail(
                (cls.MAX_EMBED_DIMENSION, cls.MAX_EMBED_DIMENSION),
                Image.Resampling.LANCZOS,
            )
            background = Image.new("RGBA", image.size, (255, 255, 255, 0))
            background.alpha_composite(image)
            output = io.BytesIO()
            background.save(output, format="PNG", optimize=True, compress_level=9)
        payload = output.getvalue()
        if len(payload) > cls.MAX_EMBED_BYTES:
            with Image.open(io.BytesIO(payload)) as source:
                rgb = source.convert("RGB")
                output = io.BytesIO()
                rgb.save(output, format="WEBP", quality=88, method=6)
            payload = output.getvalue()
            mime = "image/webp"
        else:
            mime = "image/png"
        return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"

    async def save_candidate(
        self,
        session: AsyncSession,
        provider: Provider,
        candidate: BrandingCandidate,
    ) -> None:
        if not candidate.file_id:
            raise ValueError("بيانات معاينة الشعار غير مكتملة.")
        raw = await self._download(candidate.file_id)
        await self.moderation.ensure_safe(raw)
        image_format, width, height, extracted = self._inspect(raw)
        if image_format != candidate.image_format or width != candidate.width or height != candidate.height:
            raise ValueError("تغيّر ملف الشعار أثناء المعاينة. أعد رفعه.")
        palette = BrandPalette(
            primary=candidate.primary_color or extracted.primary,
            secondary=candidate.secondary_color or extracted.secondary,
            dark=candidate.dark_color or extracted.dark,
        )
        data_uri = self._normalized_data_uri(raw)

        provider.logo_file_id = candidate.file_id
        provider.logo_url = None
        profile = await session.scalar(
            select(ProviderBrandProfile).where(ProviderBrandProfile.provider_id == provider.id)
        )
        if profile is None:
            profile = ProviderBrandProfile(provider_id=provider.id)
            session.add(profile)
        profile.logo_file_id = candidate.file_id
        profile.logo_url = None
        profile.primary_color = palette.primary
        profile.secondary_color = palette.secondary
        profile.color_extracted_at = datetime.now(UTC)

        setting_key = f"provider.logo_data_uri.{provider.id}"
        setting = await session.scalar(select(SystemSetting).where(SystemSetting.key == setting_key))
        if setting is None:
            session.add(SystemSetting(key=setting_key, value=data_uri, is_secret=False))
        else:
            setting.value = data_uri
            setting.is_secret = False
        dark_key = f"provider.brand_dark_color.{provider.id}"
        dark_setting = await session.scalar(select(SystemSetting).where(SystemSetting.key == dark_key))
        if dark_setting is None:
            session.add(SystemSetting(key=dark_key, value=palette.dark, is_secret=False))
        else:
            dark_setting.value = palette.dark
        await session.flush()

    async def save_uploaded_bytes(
        self,
        session: AsyncSession,
        provider: Provider,
        raw: bytes,
        *,
        telegram_chat_id: int,
        filename: str = "provider-logo.png",
    ) -> BrandingCandidate:
        """Validate a Mini App upload and persist it using a Telegram file id.

        Telegram does not expose a standalone upload endpoint: media becomes reusable
        only after it is sent to a chat. The bot therefore sends the validated image
        to the authenticated actor's private chat, captures Telegram's durable file id,
        stores the normalized report copy, then best-effort deletes the transport
        message so the upload does not clutter the conversation.
        """

        if not raw:
            raise ValueError("ملف الشعار فارغ")
        if len(raw) > self.MAX_LOGO_BYTES:
            raise ValueError("حجم الشعار كبير جدًا. الحد الأقصى 8MB.")
        await self.moderation.ensure_safe(raw)
        image_format, width, height, palette = self._inspect(raw)
        ratio = width / height
        warning = None
        if not 0.95 <= ratio <= 1.05:
            warning = "يُفضّل استخدام شعار مربع تقريبًا للحصول على أفضل نتيجة داخل تيليجرام."
        transport = await self.bot.send_photo(
            int(telegram_chat_id),
            BufferedInputFile(raw, filename=filename[:120] or "provider-logo.png"),
            caption="جاري اعتماد شعار المنصة…",
        )
        if not transport.photo:
            raise ValueError("تعذر اعتماد ملف الشعار في تيليجرام")
        photo = transport.photo[-1]
        candidate = BrandingCandidate(
            file_id=photo.file_id,
            file_unique_id=photo.file_unique_id,
            file_size=len(raw),
            image_format=image_format,
            width=width,
            height=height,
            primary_color=palette.primary,
            secondary_color=palette.secondary,
            dark_color=palette.dark,
            warning=warning,
        )
        data_uri = self._normalized_data_uri(raw)
        provider.logo_file_id = candidate.file_id
        provider.logo_url = None
        profile = await session.scalar(
            select(ProviderBrandProfile).where(ProviderBrandProfile.provider_id == provider.id)
        )
        if profile is None:
            profile = ProviderBrandProfile(provider_id=provider.id)
            session.add(profile)
        profile.logo_file_id = candidate.file_id
        profile.logo_url = None
        profile.primary_color = palette.primary
        profile.secondary_color = palette.secondary
        profile.color_extracted_at = datetime.now(UTC)

        setting_key = f"provider.logo_data_uri.{provider.id}"
        setting = await session.scalar(select(SystemSetting).where(SystemSetting.key == setting_key))
        if setting is None:
            session.add(SystemSetting(key=setting_key, value=data_uri, is_secret=False))
        else:
            setting.value = data_uri
            setting.is_secret = False
        dark_key = f"provider.brand_dark_color.{provider.id}"
        dark_setting = await session.scalar(select(SystemSetting).where(SystemSetting.key == dark_key))
        if dark_setting is None:
            session.add(SystemSetting(key=dark_key, value=palette.dark, is_secret=False))
        else:
            dark_setting.value = palette.dark
        await session.flush()
        try:
            await self.bot.delete_message(int(telegram_chat_id), transport.message_id)
        except Exception:
            pass
        return candidate

    async def save_photo(
        self,
        session: AsyncSession,
        provider: Provider,
        photo: PhotoSize,
    ) -> None:
        candidate = await self.validate_photo(photo)
        await self.save_candidate(session, provider, candidate)

    async def save_url(
        self,
        session: AsyncSession,
        provider: Provider,
        url: str,
    ) -> None:
        raise ValueError("أرسل صورة شعار مباشرة داخل تيليجرام؛ روابط الصور غير مقبولة.")
