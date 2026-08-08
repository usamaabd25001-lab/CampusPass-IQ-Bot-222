from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets


@dataclass(slots=True, frozen=True)
class FriendPackageInvoice:
    """Invoice for one member of «باقة أصدقائي فقط».

    The full bot fee is charged to every member and is never divided. The
    service share is deterministic, so concurrent joins cannot create different
    totals for the same member position.
    """

    member_share_iqd: int
    bot_fee_iqd: int

    def __post_init__(self) -> None:
        for field_name, value in (
            ("member_share_iqd", self.member_share_iqd),
            ("bot_fee_iqd", self.bot_fee_iqd),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} cannot be negative")

    @property
    def amount_due_iqd(self) -> int:
        return self.member_share_iqd + self.bot_fee_iqd


@dataclass(slots=True, frozen=True)
class FriendPackageProgress:
    required_members: int
    paid_members: int

    def __post_init__(self) -> None:
        if self.required_members < 2:
            raise ValueError("required_members must be at least 2")
        if self.paid_members < 0:
            raise ValueError("paid_members cannot be negative")
        if self.paid_members > self.required_members:
            raise ValueError("paid_members cannot exceed required_members")

    @property
    def remaining_members(self) -> int:
        return self.required_members - self.paid_members

    @property
    def is_complete(self) -> bool:
        return self.paid_members == self.required_members

    @property
    def status_text(self) -> str:
        if self.is_complete:
            return "اكتمل عدد الأصدقاء وسيتم إرسال الحساب لجميع الأعضاء."
        return (
            f"اكتمل دفع {self.paid_members} من {self.required_members}، "
            f"والمتبقي {self.remaining_members}."
        )


def service_share_for_index(total_iqd: int, members: int, member_index: int) -> int:
    """Split an integer IQD total without losing dinars.

    Remainder dinars are assigned to the first positions. The sum of all
    positions always equals ``total_iqd``.
    """
    if isinstance(total_iqd, bool) or total_iqd < 0:
        raise ValueError("total_iqd must be a non-negative integer")
    if members < 2:
        raise ValueError("members must be at least 2")
    if member_index < 0 or member_index >= members:
        raise ValueError("member_index is out of range")
    base, remainder = divmod(int(total_iqd), int(members))
    return base + (1 if member_index < remainder else 0)


def issue_join_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(24)
    return token, hash_join_token(token)


def hash_join_token(token: str) -> str:
    normalized = str(token).strip()
    if len(normalized) < 20:
        raise ValueError("invalid friend-group token")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
