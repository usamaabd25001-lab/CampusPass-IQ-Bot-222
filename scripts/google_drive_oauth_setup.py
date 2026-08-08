from __future__ import annotations

import argparse
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPE = "https://www.googleapis.com/auth/drive.file"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create Google Drive offline credentials for encrypted CampusPass backups"
    )
    parser.add_argument("client_json", type=Path, help="OAuth desktop client JSON from Google Cloud")
    args = parser.parse_args()
    if not args.client_json.is_file():
        raise SystemExit("OAuth client JSON file not found")

    payload = json.loads(args.client_json.read_text(encoding="utf-8"))
    client_info = payload.get("installed") or payload.get("web") or {}
    flow = InstalledAppFlow.from_client_secrets_file(str(args.client_json), scopes=[SCOPE])
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        authorization_prompt_message="افتح الرابط التالي وسجّل الدخول إلى Google Drive:\n{url}",
        success_message="تم الربط. يمكنك إغلاق هذه الصفحة والعودة إلى الطرفية.",
        open_browser=True,
        access_type="offline",
        prompt="consent",
    )
    if not credentials.refresh_token:
        raise SystemExit("Google did not return a refresh token; revoke access and run again")

    print("\nضع القيم التالية كـ GitHub Secrets أو Railway Variables ولا تشاركها:")
    print(f"GOOGLE_DRIVE_CLIENT_ID={client_info.get('client_id', '')}")
    print(f"GOOGLE_DRIVE_CLIENT_SECRET={client_info.get('client_secret', '')}")
    print(f"GOOGLE_DRIVE_REFRESH_TOKEN={credentials.refresh_token}")


if __name__ == "__main__":
    main()
