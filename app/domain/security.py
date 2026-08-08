from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum


class IdempotencyScope(StrEnum):
    PAYMENT_CONFIRMATION = "payment-confirmation"
    WALLET_FEE_DEBIT = "wallet-fee-debit"
    OVERPAYMENT_CREDIT = "overpayment-credit"
    FRIEND_PACKAGE_PAYMENT = "friend-package-payment"
    WARRANTY_REPLACEMENT = "warranty-replacement"


@dataclass(slots=True, frozen=True)
class ReceiptFingerprint:
    sha256: str
    size_bytes: int

    @classmethod
    def from_bytes(cls, payload: bytes) -> "ReceiptFingerprint":
        if not payload:
            raise ValueError("receipt payload cannot be empty")
        return cls(sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload))


def idempotency_key(scope: IdempotencyScope, *parts: object) -> str:
    normalized = ":".join(str(part).strip() for part in parts)
    if not normalized or any(not str(part).strip() for part in parts):
        raise ValueError("idempotency key parts cannot be empty")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
    return f"{scope.value}:{digest}"
