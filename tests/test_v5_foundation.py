from pathlib import Path

import pytest

from app.services.activation_guides import ActivationGuideService
from app.services.pricing import PriceService
from app.services.reviews import ReviewService


def test_v5_iqd_validation_accepts_arabic_digits_and_warns_on_ten():
    assert PriceService.parse_iqd("١٠٠٠٠ د.ع") == 10_000
    assert PriceService.parse_iqd("10,000") == 10_000
    assert PriceService.iqd_words(10_000).startswith("عشرة آلاف")
    with pytest.raises(ValueError):
        PriceService.parse_iqd("عشرة آلاف")


def test_v5_provider_rating_renders_filled_and_empty_stars():
    assert ReviewService.stars(3.1) == "⭐⭐⭐☆☆"
    assert ReviewService.stars(4.7) == "⭐⭐⭐⭐⭐"
    assert ReviewService.stars(0) == "☆☆☆☆☆"


def test_v5_activation_guide_requires_meaningful_steps():
    normalized = ActivationGuideService._normalize_steps(
        [
            {"kind": "text", "text": "افتح الموقع الرسمي"},
            {"kind": "photo", "telegram_file_id": "photo-file", "text": "اضغط تسجيل الدخول"},
            {"kind": "link", "url": "https://example.com", "button_text": "فتح الموقع"},
            {"kind": "text", "text": ""},
        ]
    )
    assert [item["kind"] for item in normalized] == ["text", "photo", "link"]


def test_v5_a4_report_template_contains_branding_ratings_and_downloads():
    template = Path("app/reports/templates/provider_v5.html").read_text(encoding="utf-8")
    assert "@page { size: A4" in template
    assert "CampusPass IQ" in template
    assert "مكان شعار المنصة" in template
    assert "تقييم المنصة" in template
    assert "تنزيل HTML" in template
    assert "تنزيل CSV" in template
