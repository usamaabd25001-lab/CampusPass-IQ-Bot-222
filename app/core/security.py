from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import Settings


class SecretBox:
    def __init__(self, settings: Settings) -> None:
        raw_keys = [settings.encryption_key.strip(), *settings.encryption_keyring]
        normalized: list[bytes] = []
        for raw in raw_keys:
            if not raw:
                continue
            try:
                key = raw.encode("ascii")
                Fernet(key)
            except Exception:
                key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
            if key not in normalized:
                normalized.append(key)
        if not normalized:
            # Development/test fallback only. Production validation requires a stable key.
            digest = hashlib.sha256(
                f"{settings.bot_token}|{settings.report_secret_key}|campuspass".encode()
            ).digest()
            normalized.append(base64.urlsafe_b64encode(digest))
        self.key_version = settings.encryption_key_version
        self._primary = Fernet(normalized[0])
        self._fernet = MultiFernet([Fernet(key) for key in normalized])
        self._report_secret = (
            settings.report_secret_key or hashlib.sha256(normalized[0]).hexdigest()
        ).encode()

    def needs_rotation(self, token: str | bytes | None) -> bool:
        if not token:
            return False
        raw = token if isinstance(token, bytes) else token.encode()
        try:
            self._primary.decrypt(raw)
            return False
        except InvalidToken:
            self._fernet.decrypt(raw)
            return True

    def rotate(self, token: str) -> str:
        if not token:
            return ""
        try:
            return self._fernet.rotate(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Encrypted value cannot be rotated with configured keyring") from exc

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        return self._fernet.encrypt(value.encode()).decode()

    def encrypt_bytes(self, value: bytes) -> bytes:
        if not value:
            return b""
        return self._fernet.encrypt(value)

    def decrypt_bytes(self, value: bytes) -> bytes:
        if not value:
            return b""
        try:
            return self._fernet.decrypt(value)
        except InvalidToken as exc:
            raise ValueError("Encrypted bytes cannot be decrypted with current key") from exc

    def decrypt(self, value: str | None) -> str:
        if not value:
            return ""
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Encrypted value cannot be decrypted with current key") from exc

    @staticmethod
    def hash_value(value: str | bytes) -> str:
        raw = value if isinstance(value, bytes) else value.encode()
        return hashlib.sha256(raw).hexdigest()

    def sign_report(self, report_id: int, expires_at: datetime) -> str:
        payload = f"{report_id}:{int(expires_at.timestamp())}"
        signature = hmac.new(self._report_secret, payload.encode(), hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode().rstrip("=")

    def verify_report(self, token: str) -> int | None:
        try:
            padded = token + "=" * (-len(token) % 4)
            decoded = base64.urlsafe_b64decode(padded).decode()
            report_id_text, expiry_text, signature = decoded.split(":", 2)
            payload = f"{report_id_text}:{expiry_text}"
            expected = hmac.new(self._report_secret, payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return None
            if int(expiry_text) < int(datetime.now(UTC).timestamp()):
                return None
            return int(report_id_text)
        except Exception:
            return None

    def sign_payload(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(self._report_secret, raw, hashlib.sha256).hexdigest()

    def verify_payload(self, payload: dict[str, Any], signature: str) -> bool:
        expected = self.sign_payload(payload)
        return hmac.compare_digest(expected, signature.strip())

    @staticmethod
    def verify_raw_hmac(body: bytes, signature: str, secret: str) -> bool:
        """Verify SHA-256 HMAC signatures without coupling payment keys to report keys."""
        if not signature or not secret:
            return False
        supplied = signature.strip()
        if supplied.lower().startswith("sha256="):
            supplied = supplied.split("=", 1)[1]
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, supplied)
