from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models import Report
from tests.v4_helpers import services_bundle

REPORTS = {
    "general": "01-general-report.html",
    "students": "02-students-report.html",
    "sales": "03-sales-report.html",
    "academics": "04-academics-report.html",
    "governorates": "05-governorates-report.html",
    "ratings": "06-ratings-report.html",
    "withdrawals": "07-withdrawals-report.html",
}

TITLES = {
    "general": "التقرير العام للمنصة",
    "students": "تقرير الطلاب",
    "sales": "تقرير المبيعات والمشتريات",
    "academics": "تقرير الكليات والتخصصات",
    "governorates": "تقرير المحافظات",
    "ratings": "تقرير التقييمات ورضا الطلاب",
    "withdrawals": "تقرير السحوبات والمستحقات",
}


def snapshot(report_type: str) -> dict:
    return {
        "provider": {
            "id": 1,
            "name_ar": "منصة Campus Technology التجريبية",
            "name_en": "Campus Technology Demo",
            "logo_url": "",
            "logo_file_id": None,
        },
        "summary": {
            "orders": 6842,
            "sales": 583_450_000,
            "service_fees": 3_421_000,
            "management_fees": 29_172_500,
            "provider_net": 550_856_500,
            "owner_net": 32_593_500,
            "completed": 4263,
            "refunded": 157,
            "support": 88,
            "rating_average": 4.3,
            "rating_count": 100,
            "withdrawals_paid": 410_000_000,
            "available_balance": 140_856_500,
        },
        "statuses": {
            "completed": 4263,
            "paid": 1471,
            "processing": 697,
            "needs_support": 254,
            "refunded": 157,
        },
        "top_offers": [
            {"title": "Microsoft 365 — سنة", "count": 2135, "sales": 213_500_000},
            {"title": "حساب Canva Pro", "count": 1428, "sales": 107_100_000},
            {"title": "اشتراك تعليم إلكتروني", "count": 1067, "sales": 96_030_000},
            {"title": "خدمات الطباعة", "count": 892, "sales": 62_440_000},
            {"title": "استشارات أكاديمية", "count": 645, "sales": 48_375_000},
        ],
        "emails": [
            {"label": "Outlook Office 01", "username": "of***01@outlook.com", "used": 4, "limit": 20, "status": "available"},
            {"label": "Gmail Codes 02", "username": "co***02@gmail.com", "used": 8, "limit": 30, "status": "available"},
        ],
        "report_meta": {
            "type": report_type,
            "title": TITLES[report_type],
            "tier": "pro",
            "tier_label": "Pro",
        },
        "students": {
            "total": 24780,
            "new": 1842,
            "top_university": {"name": "جامعة بغداد", "count": 6482},
            "top_college": {"name": "كلية الهندسة", "count": 3812},
            "top_department": {"name": "هندسة الحاسوب", "count": 2574},
            "top_stage": {"name": "المرحلة الثالثة", "count": 6210},
            "top_governorate": {"name": "بغداد", "count": 9324},
        },
        "profile_rankings": {
            "universities": [
                {"name": "جامعة بغداد", "count": 6482},
                {"name": "الجامعة المستنصرية", "count": 4285},
                {"name": "الجامعة التكنولوجية", "count": 3562},
                {"name": "جامعة النهرين", "count": 2876},
                {"name": "جامعة الكوفة", "count": 2193},
            ],
            "colleges": [
                {"name": "كلية الهندسة", "count": 3812},
                {"name": "علوم الحاسوب", "count": 3270},
                {"name": "إدارة واقتصاد", "count": 2965},
                {"name": "كلية الطب", "count": 2341},
                {"name": "كلية العلوم", "count": 2087},
            ],
            "departments": [
                {"name": "هندسة الحاسوب", "count": 2574},
                {"name": "علوم الحاسوب", "count": 2418},
                {"name": "إدارة الأعمال", "count": 2127},
                {"name": "الهندسة المدنية", "count": 1984},
                {"name": "نظم المعلومات", "count": 1812},
            ],
            "stages": [
                {"name": "المرحلة الثالثة", "count": 6210},
                {"name": "المرحلة الثانية", "count": 5784},
                {"name": "المرحلة الرابعة", "count": 5112},
                {"name": "المرحلة الأولى", "count": 4890},
                {"name": "دراسات عليا", "count": 2784},
            ],
            "governorates": [
                {"name": "بغداد", "count": 9324},
                {"name": "البصرة", "count": 3812},
                {"name": "النجف", "count": 2965},
                {"name": "كربلاء", "count": 2341},
                {"name": "نينوى", "count": 2087},
            ],
        },
        "trend": [
            {"label": "2026-01-01", "orders": 4210, "sales": 341_000_000, "completed": 2880},
            {"label": "2026-02-01", "orders": 4876, "sales": 392_000_000, "completed": 3250},
            {"label": "2026-03-01", "orders": 5631, "sales": 471_000_000, "completed": 3700},
            {"label": "2026-04-01", "orders": 6089, "sales": 522_000_000, "completed": 4010},
            {"label": "2026-05-01", "orders": 6842, "sales": 583_450_000, "completed": 4263},
        ],
        "rating_distribution": {"5": 60, "4": 25, "3": 10, "2": 3, "1": 2},
        "withdrawals": [
            {"public_id": "WD-2026-001", "amount": 68_450_000, "status": "paid", "date": "2026-05-30T14:20:00+00:00"},
            {"public_id": "WD-2026-002", "amount": 54_230_000, "status": "paid", "date": "2026-05-24T11:00:00+00:00"},
            {"public_id": "WD-2026-003", "amount": 41_980_000, "status": "pending", "date": "2026-05-19T09:15:00+00:00"},
        ],
    }


def main() -> None:
    _settings, _bot, _secrets, services = services_bundle()
    out = Path("examples/v5_reports")
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    for index, (kind, filename) in enumerate(REPORTS.items(), start=1):
        report = Report(
            id=1000 + index,
            provider_id=1,
            report_type=kind,
            period_start=now - timedelta(days=30),
            period_end=now,
            snapshot=snapshot(kind),
            plan="pro",
            created_at=now,
            expires_at=now + timedelta(days=7),
        )
        html = services.reports.render(report, f"https://example.invalid/reports/v5-demo-{kind}")
        (out / filename).write_text(html, encoding="utf-8")
    (out / "README_AR.txt").write_text(
        "هذه أمثلة HTML A4 مستقلة ببيانات تجريبية فقط. افتح أي ملف بالمتصفح.\n"
        "في التشغيل الحقيقي يستبدل البوت الأرقام والشعارات ببيانات قاعدة البيانات.\n",
        encoding="utf-8",
    )
    print(f"generated {len(REPORTS)} report examples in {out}")


if __name__ == "__main__":
    main()
