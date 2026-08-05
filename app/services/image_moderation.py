from __future__ import annotations

import base64
import io
import logging

import httpx
from PIL import Image, UnidentifiedImageError

from app.core.config import Settings

logger = logging.getLogger(__name__)


class ImageModerationService:
    """Image integrity validation with optional Google Vision SafeSearch.

    ``auto`` always performs local validation and upgrades to Google Vision when
    ``GOOGLE_VISION_API_KEY`` is present. Missing external credentials never make
    ordinary uploads crash; the feature remains locally active and health reports
    the connector as pending.
    """

    _LIKELIHOOD_ORDER = {
        "UNKNOWN": 0,
        "VERY_UNLIKELY": 1,
        "UNLIKELY": 2,
        "POSSIBLE": 3,
        "LIKELY": 4,
        "VERY_LIKELY": 5,
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def validate_image(raw: bytes) -> tuple[str, int, int]:
        try:
            with Image.open(io.BytesIO(raw)) as image:
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                width, height = image.size
                fmt = (image.format or "").upper()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValueError("الملف المرفوع ليس صورة سليمة.") from exc
        if width < 128 or height < 128:
            raise ValueError("دقة الشعار منخفضة جدًا. الحد الأدنى 128×128.")
        if width * height > 20_000_000:
            raise ValueError("أبعاد الشعار كبيرة جدًا.")
        if fmt not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("صيغة الشعار غير مدعومة. استخدم JPG أو PNG أو WebP.")
        return fmt, width, height

    async def _google_safe_search(self, raw: bytes) -> None:
        payload = {
            "requests": [
                {
                    "image": {"content": base64.b64encode(raw).decode("ascii")},
                    "features": [{"type": "SAFE_SEARCH_DETECTION", "maxResults": 1}],
                }
            ]
        }
        url = "https://vision.googleapis.com/v1/images:annotate"
        async with httpx.AsyncClient(
            timeout=self.settings.image_moderation_timeout_seconds,
            follow_redirects=False,
        ) as client:
            response = await client.post(
                url,
                params={"key": self.settings.google_vision_api_key},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        try:
            first = data["responses"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Google Vision returned an unexpected response") from exc
        if first.get("error"):
            raise RuntimeError(str(first["error"].get("message") or "Vision API error")[:500])
        annotation = first.get("safeSearchAnnotation") or {}
        threshold = self._LIKELIHOOD_ORDER[self.settings.image_moderation_block_likelihood]
        blocked = {
            key: value
            for key, value in annotation.items()
            if key in {"adult", "violence", "racy"}
            and self._LIKELIHOOD_ORDER.get(str(value).upper(), 0) >= threshold
        }
        if blocked:
            labels = ", ".join(f"{k}={v}" for k, v in sorted(blocked.items()))
            raise ValueError(f"تم رفض الصورة بسبب نتيجة فحص الأمان: {labels}")

    async def ensure_safe(self, raw: bytes) -> None:
        self.validate_image(raw)
        if not self.settings.image_moderation_enabled:
            return
        provider = self.settings.image_moderation_provider
        if provider == "disabled" or provider == "local":
            return
        if not self.settings.image_moderation_external_ready:
            if provider == "google_vision" and self.settings.image_moderation_fail_closed:
                raise ValueError("فحص الصور الخارجي يحتاج GOOGLE_VISION_API_KEY.")
            return
        try:
            await self._google_safe_search(raw)
        except ValueError:
            raise
        except Exception as exc:
            logger.warning("External image moderation unavailable: %s", exc)
            if self.settings.image_moderation_fail_closed:
                raise ValueError("تعذر التحقق من أمان الصورة حالياً.") from exc
