# مصفوفة تتبع V11.5

| المطلب | التنفيذ | قاعدة البيانات | الاختبار |
|---|---|---|---|
| RPT-001 Free | `ReportService.free_message` + Scheduler | `cp_daily_provider_metrics` | `test_v11_5_reports_branding_health.py` |
| RPT-002 Plus HTML | `render_artifact(format=html)` | `cp_report_artifacts` | HTML artifact test |
| RPT-003 Pro PDF/Web | API dashboard/PDF + WeasyPrint | `cp_report_artifacts` | PDF signature + rendered sample |
| RPT-004 Branding all tiers | `BrandingService`, `branding_palette.py` | `cp_provider_brand_profiles` | palette/contrast test |
| RPT-005 Official A4 | `provider_v5.html` | report reference/access | visual two-page sample |
| RPT-006 Background metrics | Scheduler + daily materialization | `cp_daily_provider_metrics` | validator |
| OWN-004 UI Builder | snapshot/list/restore | `cp_menu_revisions` | compile + validator |
| OWN-010 Health | `HealthService`, `system_metrics.py` | `cp_system_health_snapshots` | runtime metrics test |
