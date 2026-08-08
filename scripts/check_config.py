from __future__ import annotations

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.db_url import safe_database_label


try:
    settings = get_settings()
except ValidationError as exc:
    print("❌ Variables are incomplete or invalid")
    for item in exc.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item.get("loc", ())) or "settings"
        print(f"- {location}: {item.get('msg', 'invalid value')}")
    raise SystemExit(1) from None

print("✅ Variables are valid")
print(f"Environment: {settings.environment}")
print(f"Admins: {len(settings.admin_ids)}")
print(f"Database: {safe_database_label(settings.database_url)}")
print(f"External database required: {settings.require_external_database}")
print(f"Database SSL mode: {settings.db_ssl_mode}")
