from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class TelegramWebAppAuthError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TelegramWebAppUser:
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str | None = None
    language_code: str | None = None

    @property
    def full_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part).strip()


@dataclass(frozen=True, slots=True)
class VerifiedInitData:
    user: TelegramWebAppUser
    auth_date: int
    query_id: str | None
    raw: dict[str, str]


def verify_telegram_init_data(
    init_data: str,
    *,
    bot_token: str,
    max_age_seconds: int = 900,
    now: int | None = None,
) -> VerifiedInitData:
    """Verify Telegram Mini App initData using Telegram's HMAC construction."""

    if not init_data or not bot_token:
        raise TelegramWebAppAuthError("بيانات التحقق غير موجودة")
    values = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    supplied_hash = values.pop("hash", "")
    if not supplied_hash:
        raise TelegramWebAppAuthError("توقيع Telegram غير موجود")

    check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key,
        check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, supplied_hash):
        raise TelegramWebAppAuthError("توقيع Telegram غير صالح")

    try:
        auth_date = int(values.get("auth_date", "0"))
    except ValueError as exc:
        raise TelegramWebAppAuthError("وقت التحقق غير صالح") from exc
    current = int(time.time() if now is None else now)
    if auth_date <= 0 or current - auth_date > max(30, int(max_age_seconds)) or auth_date > current + 30:
        raise TelegramWebAppAuthError("انتهت صلاحية جلسة Web App")

    try:
        user_payload = json.loads(values.get("user", "{}"))
        user_id = int(user_payload["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TelegramWebAppAuthError("هوية المستخدم غير موجودة") from exc

    return VerifiedInitData(
        user=TelegramWebAppUser(
            id=user_id,
            first_name=str(user_payload.get("first_name") or ""),
            last_name=str(user_payload.get("last_name") or ""),
            username=str(user_payload["username"]) if user_payload.get("username") else None,
            language_code=(
                str(user_payload["language_code"])
                if user_payload.get("language_code")
                else None
            ),
        ),
        auth_date=auth_date,
        query_id=values.get("query_id") or None,
        raw=values,
    )
