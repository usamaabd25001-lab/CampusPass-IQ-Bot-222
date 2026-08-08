from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.config import Settings
from app.core.security import SecretBox


@dataclass(slots=True)
class CheckoutSession:
    reference: str
    checkout_url: str
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GatewayNotification:
    event_key: str
    reference: str
    order_public_id: str
    status: str
    amount_iqd: int
    currency: str
    successful: bool
    failed: bool
    raw: dict[str, Any]


class MastercardGateway:
    """Generic hosted-checkout adapter with a strict, idempotent webhook contract.

    Acquirers use different field names. The parser accepts common aliases at the
    top level and under ``data``, ``transaction``, ``payment`` or ``event``. Once a
    specific bank is contracted, this file is the only integration surface that
    should need adapting.
    """

    _CONTAINERS = ("data", "transaction", "payment", "event", "object")

    def __init__(self, settings: Settings, secrets: SecretBox) -> None:
        self.settings = settings
        self.secrets = secrets

    @property
    def enabled(self) -> bool:
        return self.settings.mastercard_ready

    async def create_checkout(
        self,
        order_public_id: str,
        amount_iqd: int,
        return_url: str,
        webhook_url: str,
    ) -> CheckoutSession:
        if not self.enabled:
            raise RuntimeError("Mastercard gateway is disabled")
        payload = {
            "merchant_id": self.settings.payment_gateway_merchant_id,
            "order_id": order_public_id,
            "amount": amount_iqd,
            "currency": "IQD",
            "return_url": return_url,
            "webhook_url": webhook_url,
        }
        async with httpx.AsyncClient(timeout=40, follow_redirects=False) as client:
            response = await client.post(
                self.settings.payment_gateway_create_url,
                headers={
                    "Authorization": f"Bearer {self.settings.payment_gateway_api_key}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": f"checkout:{order_public_id}",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Gateway response must be a JSON object")
        reference = str(self._first(data, "reference", "transaction_id", "payment_id", "id") or "")
        checkout_url = str(
            self._first(data, "checkout_url", "payment_url", "redirect_url", "url") or ""
        )
        if not reference or not checkout_url:
            raise RuntimeError("Gateway response has no reference/checkout_url")
        if not checkout_url.lower().startswith("https://"):
            raise RuntimeError("Gateway checkout URL must use HTTPS")
        return CheckoutSession(reference=reference[:160], checkout_url=checkout_url, raw=data)

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        return self.secrets.verify_raw_hmac(
            body,
            signature,
            self.settings.payment_webhook_secret,
        )

    def parse_webhook(self, payload: dict[str, Any]) -> GatewayNotification:
        if not isinstance(payload, dict):
            raise ValueError("Webhook payload must be a JSON object")

        reference = self._text(
            self._first(payload, "reference", "transaction_id", "payment_id", "gateway_reference")
        )
        order_id = self._text(
            self._first(payload, "order_id", "merchant_order_id", "order", "order_reference")
        )
        status = self._text(
            self._first(payload, "status", "payment_status", "transaction_status", "state")
        ).lower()
        currency = self._text(self._first(payload, "currency", "currency_code") or "IQD").upper()
        amount = self._amount(self._first(payload, "amount", "amount_iqd", "total", "value"))
        supplied_event = self._text(
            self._first(payload, "event_id", "webhook_id", "notification_id", "id")
        )

        missing = [
            name
            for name, value in {
                "reference": reference,
                "order_id": order_id,
                "status": status,
                "amount": amount,
            }.items()
            if value in {"", None}
        ]
        if missing:
            raise ValueError(f"Webhook payload is missing: {', '.join(missing)}")
        if amount is None or amount <= 0:
            raise ValueError("Webhook amount must be a positive IQD integer")

        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        event_key = supplied_event or self.secrets.hash_value(canonical)
        success = status in set(self.settings.payment_success_statuses)
        failed = status in set(self.settings.payment_failure_statuses)
        return GatewayNotification(
            event_key=event_key[:160],
            reference=reference[:160],
            order_public_id=order_id[:40],
            status=status[:40],
            amount_iqd=amount,
            currency=currency[:8],
            successful=success,
            failed=failed,
            raw=payload,
        )

    @classmethod
    def _first(cls, payload: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in payload and payload[key] not in (None, ""):
                return payload[key]
        for container_name in cls._CONTAINERS:
            nested = payload.get(container_name)
            if isinstance(nested, dict):
                for key in keys:
                    if key in nested and nested[key] not in (None, ""):
                        value = nested[key]
                        if isinstance(value, dict):
                            for candidate in ("id", "reference", "value", "amount"):
                                if candidate in value and value[candidate] not in (None, ""):
                                    return value[candidate]
                        return value
        return None

    @staticmethod
    def _text(value: Any) -> str:
        if isinstance(value, dict):
            for key in ("id", "reference", "value", "code"):
                if key in value:
                    return str(value[key]).strip()
            return ""
        return str(value or "").strip()

    @staticmethod
    def _amount(value: Any) -> int | None:
        if isinstance(value, dict):
            value = value.get("value") or value.get("amount")
        if value is None or isinstance(value, bool):
            return None
        try:
            amount = Decimal(str(value).replace(",", "").strip())
        except (InvalidOperation, ValueError):
            return None
        if amount != amount.to_integral_value():
            return None
        return int(amount)
