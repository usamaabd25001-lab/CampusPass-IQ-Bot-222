from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace

from app.domain.branding_palette import contrast_ratio, extract_brand_palette
from app.services.report_artifacts import ReportArtifactRenderer
from app.services.system_metrics import RuntimeMetricsService

ROOT = Path(__file__).resolve().parents[1]

def test_official_brand_palette() -> None:
    raw = (ROOT / "app/reports/assets/campuspass-iq-square-v11.png").read_bytes()
    palette = extract_brand_palette(raw)
    assert palette.primary.startswith("#") and len(palette.primary) == 7
    assert palette.secondary.startswith("#") and len(palette.secondary) == 7
    assert contrast_ratio(palette.dark, "#FFFFFF") >= 4.5

def test_artifact_html_and_pdf() -> None:
    html = "<html lang='ar' dir='rtl'><body><h1>CampusPass IQ</h1><p>تقرير رسمي</p></body></html>"
    artifact = ReportArtifactRenderer.html(html, "report.html")
    assert artifact.content.startswith(b"<html")
    pdf = ReportArtifactRenderer.pdf(html, "report.pdf")
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.sha256) == 64

def test_runtime_metrics_are_bounded() -> None:
    metrics = RuntimeMetricsService().snapshot()
    assert metrics.process_rss_bytes > 0
    assert 0 <= metrics.system_memory_percent <= 100
    assert 0 <= metrics.disk_percent <= 100

def test_template_has_locked_branding_and_no_csv() -> None:
    template = (ROOT / "app/reports/templates/provider_v5.html").read_text(encoding="utf-8")
    assert "watermark" in template
    assert "Official Automated Report" in template
    assert "ولا يحتاج إلى توقيع" in template
    assert "CSV" not in template

def test_v115_models_registered() -> None:
    from app.db.models import DailyProviderMetric, MenuRevision, ReportArtifact, SystemHealthSnapshot
    assert ReportArtifact.__tablename__ == "cp_report_artifacts"
    assert DailyProviderMetric.__tablename__ == "cp_daily_provider_metrics"
    assert MenuRevision.__tablename__ == "cp_menu_revisions"
    assert SystemHealthSnapshot.__tablename__ == "cp_system_health_snapshots"
