from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Float,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


class UserRole(StrEnum):
    USER = "user"
    PROVIDER = "provider"
    STAFF = "staff"
    ADMIN = "admin"


class ProviderStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    SUSPENDED = "suspended"
    REJECTED = "rejected"


class OfferStatus(StrEnum):
    DRAFT = "draft"
    REVIEW = "review"
    ACTIVE = "active"
    PAUSED = "paused"
    OUT_OF_STOCK = "out_of_stock"
    EXPIRED = "expired"
    REJECTED = "rejected"


class DeliveryType(StrEnum):
    INVENTORY_CODE = "inventory_code"
    INVENTORY_ACCOUNT = "inventory_account"
    EMAIL_CODE = "email_code"
    STUDENT_EMAIL_INVITE = "student_email_invite"
    MANUAL = "manual"
    FILE_SERVICE = "file_service"


class OrderStatus(StrEnum):
    DRAFT = "draft"
    WAITING_PAYMENT = "waiting_payment"
    PAYMENT_PROOF_RECEIVED = "payment_proof_received"
    PAYMENT_REVIEW = "payment_review"
    PAYMENT_REJECTED = "payment_rejected"
    PAID = "paid"
    WAITING_FULFILLMENT = "waiting_fulfillment"
    EMAIL_RESERVED = "email_reserved"
    WAITING_CODE = "waiting_code"
    CODE_FOUND = "code_found"
    DELIVERED = "delivered"
    PROCESSING = "processing"
    COMPLETED = "completed"
    NEEDS_SUPPORT = "needs_support"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    DISPUTED = "disputed"


class PaymentProofStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    MORE_INFO = "more_info"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    REFUNDED = "refunded"


class EmailAccountStatus(StrEnum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    DAILY_LIMIT = "daily_limit"
    PAUSED = "paused"
    RECONNECT = "reconnect"
    EXPIRED = "expired"
    BLOCKED = "blocked"


class EmailReservationStatus(StrEnum):
    WAITING = "waiting"
    DELIVERED = "delivered"
    REVIEW = "review"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class InventoryStatus(StrEnum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    DELIVERED = "delivered"
    PROBLEM = "problem"
    EXPIRED = "expired"


class TicketStatus(StrEnum):
    OPEN = "open"
    WAITING_USER = "waiting_user"
    WAITING_PROVIDER = "waiting_provider"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class WithdrawalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    PAID = "paid"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class DisputeStatus(StrEnum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    WAITING_USER = "waiting_user"
    WAITING_PROVIDER = "waiting_provider"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    CLOSED = "closed"


class DisputeResolution(StrEnum):
    NONE = "none"
    FULL_REFUND = "full_refund"
    PARTIAL_REFUND = "partial_refund"
    SUBSCRIPTION_EXTENSION = "subscription_extension"
    REPLACEMENT_REQUIRED = "replacement_required"
    REJECTED = "rejected"


class RefundStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    TRANSFER_REPORTED = "transfer_reported"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"


class InventoryRemediationStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    ROTATED = "rotated"
    RETIRED = "retired"
    NOT_REQUIRED = "not_required"


class EvidenceStatus(StrEnum):
    REGISTERED = "registered"
    ARCHIVED = "archived"
    FAILED = "failed"
    DELETED = "deleted"


class PrivacyRequestType(StrEnum):
    EXPORT = "export"
    DELETE = "delete"


class PrivacyRequestStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    APPROVED = "approved"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ReportPlan(StrEnum):
    FREE = "free"
    LITE = "lite"
    PRO = "pro"


class ProviderSubscriptionStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    GRACE = "grace"
    EXPIRED = "expired"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class CouponKind(StrEnum):
    TRIAL = "trial"
    PLAN = "plan"
    PERCENT_DISCOUNT = "percent_discount"
    FIXED_DISCOUNT = "fixed_discount"
    FEATURE = "feature"


class MenuStyle(StrEnum):
    DEFAULT = "default"
    PRIMARY = "primary"
    SUCCESS = "success"
    DANGER = "danger"


class User(Base):
    __tablename__ = "cp_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(20), default=UserRole.USER.value, index=True)
    referral_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    referred_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    points: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ban_reason: Mapped[str] = mapped_column(String(500), default="")
    banned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    banned_by_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    privacy_policy_version: Mapped[str] = mapped_column(String(20), default="1.0")
    privacy_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    has_platform_access: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ai_data_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deletion_anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    profile: Mapped[StudentProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    orders: Mapped[list[Order]] = relationship(back_populates="user")


class StudentProfile(Base):
    __tablename__ = "cp_student_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), unique=True)
    full_name: Mapped[str] = mapped_column(String(180))
    phone: Mapped[str] = mapped_column(String(20), index=True)
    governorate: Mapped[str] = mapped_column(String(80))
    university: Mapped[str] = mapped_column(String(180))
    college: Mapped[str] = mapped_column(String(180))
    department: Mapped[str] = mapped_column(String(180))
    stage: Mapped[str] = mapped_column(String(80))
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    name_review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    edit_count: Mapped[int] = mapped_column(Integer, default=0)
    private_data_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    private_data_key_version: Mapped[int] = mapped_column(Integer, default=1)
    pii_protected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="profile")


class Provider(Base):
    __tablename__ = "cp_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name_ar: Mapped[str] = mapped_column(String(180), unique=True)
    name_en: Mapped[str] = mapped_column(String(180), default="")
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    logo_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    management_percent: Mapped[int] = mapped_column(Integer, default=0)
    default_service_fee_iqd: Mapped[int] = mapped_column(Integer, default=0)
    report_plan: Mapped[str] = mapped_column(String(20), default=ReportPlan.FREE.value)
    status: Mapped[str] = mapped_column(String(20), default=ProviderStatus.PENDING.value)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    offers: Mapped[list[Offer]] = relationship(back_populates="provider")
    staff: Mapped[list[ProviderStaff]] = relationship(back_populates="provider")
    subscription: Mapped[ProviderSubscription | None] = relationship(
        back_populates="provider", uselist=False, cascade="all, delete-orphan"
    )


class ProviderStaff(Base):
    __tablename__ = "cp_provider_staff"
    __table_args__ = (UniqueConstraint("provider_id", "user_id", name="uq_cp_provider_staff"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(80), default="manager")
    role: Mapped[str] = mapped_column(String(20), default="STAFF", index=True)
    can_review_payments: Mapped[bool] = mapped_column(Boolean, default=True)
    can_manage_offers: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage_inventory: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage_branding: Mapped[bool] = mapped_column(Boolean, default=False)
    can_support: Mapped[bool] = mapped_column(Boolean, default=True)
    can_view_reports: Mapped[bool] = mapped_column(Boolean, default=True)
    can_view_finance: Mapped[bool] = mapped_column(Boolean, default=False)
    can_request_withdrawal: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage_payout_accounts: Mapped[bool] = mapped_column(Boolean, default=False)
    can_view_pii: Mapped[bool] = mapped_column(Boolean, default=False)
    can_export_data: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage_disputes: Mapped[bool] = mapped_column(Boolean, default=False)
    can_approve_refunds: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    provider: Mapped[Provider] = relationship(back_populates="staff")
    user: Mapped[User] = relationship()


class Category(Base):
    __tablename__ = "cp_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    emoji: Mapped[str] = mapped_column(String(16), default="🛍")
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Offer(Base):
    __tablename__ = "cp_offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[int] = mapped_column(ForeignKey("cp_categories.id"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str] = mapped_column(Text, default="")
    image_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_price_iqd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_iqd: Mapped[int] = mapped_column(Integer)
    service_fee_iqd: Mapped[int] = mapped_column(Integer, default=500)
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    devices_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_type: Mapped[str] = mapped_column(String(40), default=DeliveryType.MANUAL.value)
    activation_fields: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    terms: Mapped[str] = mapped_column(Text, default="")
    refund_policy: Mapped[str] = mapped_column(Text, default="")
    daily_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sold_today: Mapped[int] = mapped_column(Integer, default=0)
    counter_date: Mapped[date] = mapped_column(Date, default=date.today)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default=OfferStatus.DRAFT.value, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sender_filter: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject_regex: Mapped[str | None] = mapped_column(String(500), nullable=True)
    code_regex: Mapped[str] = mapped_column(String(500), default=r"\b(\d{4,8})\b")
    max_code_attempts: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    provider: Mapped[Provider] = relationship(back_populates="offers")
    category: Mapped[Category] = relationship()
    orders: Mapped[list[Order]] = relationship(back_populates="offer")


class PaymentMethod(Base):
    __tablename__ = "cp_payment_methods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("cp_providers.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    method_type: Mapped[str] = mapped_column(String(40), default="manual")
    recipient: Mapped[str] = mapped_column(String(255), default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(16), default="💳")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Order(Base):
    __tablename__ = "cp_orders"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_cp_order_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("cp_offers.id"), index=True)
    payment_method_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_payment_methods.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(40), default=OrderStatus.DRAFT.value, index=True)
    activation_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    activation_data_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    activation_data_key_version: Mapped[int] = mapped_column(Integer, default=1)
    activation_data_protected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    payment_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    subtotal_iqd: Mapped[int] = mapped_column(Integer, default=0)
    service_fee_iqd: Mapped[int] = mapped_column(Integer, default=0)
    total_iqd: Mapped[int] = mapped_column(Integer, default=0)
    management_fee_iqd: Mapped[int] = mapped_column(Integer, default=0)
    provider_net_iqd: Mapped[int] = mapped_column(Integer, default=0)
    owner_net_iqd: Mapped[int] = mapped_column(Integer, default=0)
    code_attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivery_acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    activation_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disputed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refund_total_iqd: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="orders")
    provider: Mapped[Provider] = relationship()
    offer: Mapped[Offer] = relationship(back_populates="orders")
    payment_method: Mapped[PaymentMethod | None] = relationship()


class OrderEvent(Base):
    __tablename__ = "cp_order_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    old_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    new_status: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentProof(Base):
    __tablename__ = "cp_payment_proofs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True
    )
    photo_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender_phone: Mapped[str] = mapped_column(String(30), default="")
    claimed_amount_iqd: Mapped[int] = mapped_column(Integer)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reference_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    file_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    evidence_asset_id: Mapped[int | None] = mapped_column(ForeignKey("cp_evidence_assets.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default=PaymentProofStatus.PENDING.value)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentReferenceClaim(Base):
    __tablename__ = "cp_payment_reference_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True
    )
    normalized_reference: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Payment(Base):
    __tablename__ = "cp_payments"
    __table_args__ = (
        UniqueConstraint("gateway_reference", name="uq_cp_payment_gateway_reference"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True
    )
    payment_method_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_payment_methods.id"), nullable=True
    )
    gateway_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    amount_iqd: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default=PaymentStatus.PENDING.value)
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_amount_iqd: Mapped[int] = mapped_column(Integer, default=0)
    last_refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailAccount(Base):
    __tablename__ = "cp_email_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    offer_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_offers.id"), nullable=True, index=True
    )
    label: Mapped[str] = mapped_column(String(120))
    email_provider: Mapped[str] = mapped_column(String(40), default="imap")
    imap_host: Mapped[str] = mapped_column(String(255))
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    username: Mapped[str] = mapped_column(String(255), index=True)
    encrypted_secret: Mapped[str] = mapped_column(Text)
    security_mode: Mapped[str] = mapped_column(String(20), default="ssl")
    sender_filter: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject_regex: Mapped[str | None] = mapped_column(String(500), nullable=True)
    code_regex: Mapped[str] = mapped_column(String(500), default=r"\b(\d{4,8})\b")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    daily_limit: Mapped[int] = mapped_column(Integer, default=10)
    used_today: Mapped[int] = mapped_column(Integer, default=0)
    counter_date: Mapped[date] = mapped_column(Date, default=date.today)
    status: Mapped[str] = mapped_column(String(24), default=EmailAccountStatus.AVAILABLE.value)
    last_message_uid: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailReservation(Base):
    __tablename__ = "cp_email_reservations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True
    )
    email_account_id: Mapped[int] = mapped_column(ForeignKey("cp_email_accounts.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default=EmailReservationStatus.WAITING.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VerificationMessage(Base):
    __tablename__ = "cp_verification_messages"
    __table_args__ = (
        UniqueConstraint("email_account_id", "message_uid", name="uq_cp_email_message_uid"),
        UniqueConstraint("email_reservation_id", name="uq_cp_reservation_message"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_account_id: Mapped[int] = mapped_column(ForeignKey("cp_email_accounts.id"), index=True)
    email_reservation_id: Mapped[int] = mapped_column(
        ForeignKey("cp_email_reservations.id"), index=True
    )
    message_uid: Mapped[str] = mapped_column(String(160))
    message_id_header: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender: Mapped[str] = mapped_column(String(255), default="")
    subject: Mapped[str] = mapped_column(String(500), default="")
    code_hash: Mapped[str] = mapped_column(String(64), index=True)
    encrypted_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="found")


class InventoryItem(Base):
    __tablename__ = "cp_inventory_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    offer_id: Mapped[int] = mapped_column(
        ForeignKey("cp_offers.id", ondelete="CASCADE"), index=True
    )
    item_kind: Mapped[str] = mapped_column(String(40), default="code")
    label: Mapped[str] = mapped_column(String(120), default="")
    encrypted_payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(24), default=InventoryStatus.AVAILABLE.value, index=True
    )
    reserved_order_id: Mapped[int | None] = mapped_column(ForeignKey("cp_orders.id"), nullable=True)
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    compromised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remediation_note: Mapped[str] = mapped_column(String(500), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupportFAQ(Base):
    __tablename__ = "cp_support_faqs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question: Mapped[str] = mapped_column(String(255))
    answer: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(80), default="general")
    emoji: Mapped[str] = mapped_column(String(16), default="❓")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SupportTicket(Base):
    __tablename__ = "cp_support_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_providers.id"), nullable=True, index=True
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_orders.id"), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(String(80), default="general")
    subject: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(30), default=TicketStatus.OPEN.value, index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    ai_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    close_reason: Mapped[str] = mapped_column(String(500), default="")


class TicketMessage(Base):
    __tablename__ = "cp_ticket_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("cp_support_tickets.id", ondelete="CASCADE"), index=True
    )
    sender_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    sender_role: Mapped[str] = mapped_column(String(30), default="user")
    text: Mapped[str] = mapped_column(Text, default="")
    file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    evidence_asset_id: Mapped[int | None] = mapped_column(ForeignKey("cp_evidence_assets.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Favorite(Base):
    __tablename__ = "cp_favorites"
    __table_args__ = (UniqueConstraint("user_id", "offer_id", name="uq_cp_favorite"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"))
    offer_id: Mapped[int] = mapped_column(ForeignKey("cp_offers.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MissingServiceRequest(Base):
    __tablename__ = "cp_missing_service_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"))
    service_name: Mapped[str] = mapped_column(String(255))
    details: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="new")
    response_text: Mapped[str] = mapped_column(Text, default="")
    responded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Dispute(Base):
    __tablename__ = "cp_disputes"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_cp_dispute_idempotency"),
        UniqueConstraint("order_id", name="uq_cp_dispute_order"),
        Index("ix_cp_dispute_provider_status", "provider_id", "status"),
        Index("ix_cp_dispute_order_status", "order_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True)
    support_ticket_id: Mapped[int | None] = mapped_column(ForeignKey("cp_support_tickets.id"), nullable=True, index=True)
    reason_code: Mapped[str] = mapped_column(String(60), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    evidence_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_file_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    evidence_asset_id: Mapped[int | None] = mapped_column(ForeignKey("cp_evidence_assets.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default=DisputeStatus.OPEN.value, index=True)
    previous_order_status: Mapped[str] = mapped_column(String(40), default=OrderStatus.DELIVERED.value)
    requested_refund_iqd: Mapped[int] = mapped_column(Integer, default=0)
    resolution_type: Mapped[str] = mapped_column(String(40), default=DisputeResolution.NONE.value)
    resolution_note: Mapped[str] = mapped_column(Text, default="")
    extension_days: Mapped[int] = mapped_column(Integer, default=0)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    sla_breached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DisputeEvent(Base):
    __tablename__ = "cp_dispute_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dispute_id: Mapped[int] = mapped_column(ForeignKey("cp_disputes.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    old_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Refund(Base):
    __tablename__ = "cp_refunds"
    __table_args__ = (
        UniqueConstraint("dispute_id", name="uq_cp_refund_dispute"),
        UniqueConstraint("idempotency_key", name="uq_cp_refund_idempotency"),
        Index("ix_cp_refund_provider_status", "provider_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    dispute_id: Mapped[int] = mapped_column(ForeignKey("cp_disputes.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True)
    amount_iqd: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default=RefundStatus.REQUESTED.value, index=True)
    method: Mapped[str] = mapped_column(String(40), default="provider_direct")
    transfer_reference: Mapped[str] = mapped_column(String(160), default="")
    transfer_reference_fingerprint: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    proof_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    proof_evidence_asset_id: Mapped[int | None] = mapped_column(ForeignKey("cp_evidence_assets.id"), nullable=True, index=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    transfer_reported_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    completed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transfer_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class InventoryRemediation(Base):
    __tablename__ = "cp_inventory_remediations"
    __table_args__ = (
        UniqueConstraint("dispute_id", name="uq_cp_inventory_remediation_dispute"),
        Index("ix_cp_inventory_remediation_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dispute_id: Mapped[int] = mapped_column(ForeignKey("cp_disputes.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True)
    inventory_item_id: Mapped[int | None] = mapped_column(ForeignKey("cp_inventory_items.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default=InventoryRemediationStatus.PENDING.value, index=True)
    action_required: Mapped[str] = mapped_column(String(60), default="rotate_or_retire")
    note: Mapped[str] = mapped_column(Text, default="")
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PointsTransaction(Base):
    __tablename__ = "cp_points_transactions"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_cp_points_idempotency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(255))
    reference_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Review(Base):
    __tablename__ = "cp_reviews"
    __table_args__ = (UniqueConstraint("user_id", "order_id", name="uq_cp_review_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id"))
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id"))
    offer_id: Mapped[int] = mapped_column(ForeignKey("cp_offers.id"))
    order_id: Mapped[int] = mapped_column(ForeignKey("cp_orders.id"))
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LedgerEntry(Base):
    __tablename__ = "cp_ledger_entries"
    __table_args__ = (
        UniqueConstraint("order_id", "account_code", name="uq_cp_ledger_order_account"),
        UniqueConstraint("idempotency_key", name="uq_cp_ledger_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_providers.id"), nullable=True, index=True
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_orders.id"), nullable=True, index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    account_code: Mapped[str] = mapped_column(String(60), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    amount_iqd: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default="posted")
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WithdrawalRequest(Base):
    __tablename__ = "cp_withdrawal_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id"), index=True)
    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id"))
    amount_iqd: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(80))
    destination: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default=WithdrawalStatus.PENDING.value)
    processed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    proof_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Report(Base):
    __tablename__ = "cp_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_providers.id"), nullable=True, index=True
    )
    report_type: Mapped[str] = mapped_column(String(60))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    plan: Mapped[str] = mapped_column(String(20), default=ReportPlan.FREE.value)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReportAccess(Base):
    __tablename__ = "cp_report_access"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("cp_reports.id", ondelete="CASCADE"), unique=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    max_accesses: Mapped[int] = mapped_column(Integer, default=20)
    last_access_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentWebhookEvent(Base):
    __tablename__ = "cp_payment_webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    gateway_reference: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    order_public_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    gateway_status: Mapped[str] = mapped_column(String(40), default="unknown")
    processing_status: Mapped[str] = mapped_column(String(32), default="received", index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SubscriptionPlan(Base):
    __tablename__ = "cp_subscription_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name_ar: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    price_iqd: Mapped[int] = mapped_column(Integer, default=0)
    billing_days: Mapped[int] = mapped_column(Integer, default=30)
    grace_days: Mapped[int] = mapped_column(Integer, default=3)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    features: Mapped[list[PlanEntitlement]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class PlanEntitlement(Base):
    __tablename__ = "cp_plan_entitlements"
    __table_args__ = (UniqueConstraint("plan_id", "feature_key", name="uq_cp_plan_feature"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("cp_subscription_plans.id", ondelete="CASCADE"), index=True
    )
    feature_key: Mapped[str] = mapped_column(String(100), index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    limit_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    plan: Mapped[SubscriptionPlan] = relationship(back_populates="features")


class ProviderSubscription(Base):
    __tablename__ = "cp_provider_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), unique=True, index=True
    )
    plan_id: Mapped[int] = mapped_column(ForeignKey("cp_subscription_plans.id"), index=True)
    status: Mapped[str] = mapped_column(
        String(24), default=ProviderSubscriptionStatus.ACTIVE.value, index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False)
    custom_price_iqd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    reminder_3d_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_1d_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    expiry_notice_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    provider: Mapped[Provider] = relationship(back_populates="subscription")
    plan: Mapped[SubscriptionPlan] = relationship()


class ProviderFeatureOverride(Base):
    __tablename__ = "cp_provider_feature_overrides"
    __table_args__ = (
        Index(
            "ix_cp_provider_feature_override_lookup", "provider_id", "feature_key", "valid_until"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    feature_key: Mapped[str] = mapped_column(String(100), index=True)
    enabled_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    limit_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderCommissionOverride(Base):
    __tablename__ = "cp_provider_commission_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    management_percent: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderCoupon(Base):
    __tablename__ = "cp_provider_coupons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(30), default=CouponKind.TRIAL.value)
    value_int: Mapped[int] = mapped_column(Integer, default=0)
    plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_subscription_plans.id"), nullable=True
    )
    feature_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    feature_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("cp_providers.id"), nullable=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderCouponType(StrEnum):
    FIXED = "fixed"
    PERCENT = "percent"
    FEE_WAIVER = "fee_waiver"
    FREE_REPORT = "free_report"


class OrderCoupon(Base):
    __tablename__ = "cp_order_coupons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    coupon_type: Mapped[str] = mapped_column(String(20), default=OrderCouponType.FIXED.value)
    value_int: Mapped[int] = mapped_column(Integer, default=0)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("cp_providers.id"), nullable=True, index=True)
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True, index=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderCouponRedemption(Base):
    __tablename__ = "cp_order_coupon_redemptions"
    __table_args__ = (
        UniqueConstraint("coupon_id", "order_id", name="uq_cp_order_coupon_order"),
        Index("ix_cp_order_coupon_user", "coupon_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    coupon_id: Mapped[int] = mapped_column(ForeignKey("cp_order_coupons.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id"), index=True)
    discount_iqd: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserBenefit(Base):
    """Non-cash student entitlements granted by targeted coupons.

    The first supported benefit is ``free_report``. Keeping it in a separate
    additive table makes the coupon useful without changing historical orders,
    payments, or wallet balances.
    """

    __tablename__ = "cp_user_benefits"
    __table_args__ = (
        UniqueConstraint("source_coupon_id", "user_id", name="uq_cp_user_benefit_coupon_user"),
        Index("ix_cp_user_benefit_active", "user_id", "benefit_key", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("cp_providers.id"), nullable=True, index=True)
    benefit_key: Mapped[str] = mapped_column(String(40), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    source_coupon_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_order_coupons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderCouponRedemption(Base):
    __tablename__ = "cp_provider_coupon_redemptions"
    __table_args__ = (
        UniqueConstraint("coupon_id", "provider_id", name="uq_cp_coupon_provider_redemption"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    coupon_id: Mapped[int] = mapped_column(ForeignKey("cp_provider_coupons.id", ondelete="CASCADE"))
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id", ondelete="CASCADE"))
    redeemed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SubscriptionChangeLog(Base):
    __tablename__ = "cp_subscription_change_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id"), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    old_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    new_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MenuButtonConfig(Base):
    __tablename__ = "cp_menu_buttons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    text: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(80), index=True)
    style: Mapped[str] = mapped_column(String(20), default=MenuStyle.DEFAULT.value)
    row_number: Mapped[int] = mapped_column(Integer, default=0)
    position: Mapped[int] = mapped_column(Integer, default=0)
    role_scope: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["user"])
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ScheduledRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class BackupRunStatus(StrEnum):
    STARTED = "started"
    UPLOADED = "uploaded"
    VERIFIED = "verified"
    FAILED = "failed"
    DELETED = "deleted"


class DeploymentStatus(StrEnum):
    STARTING = "starting"
    READY = "ready"
    STOPPED = "stopped"
    FAILED = "failed"


class RuntimeIncidentStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"



class SystemSetting(Base):
    __tablename__ = "cp_system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SchemaMigration(Base):
    __tablename__ = "cp_schema_migrations"

    version: Mapped[str] = mapped_column(String(80), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    checksum: Mapped[str] = mapped_column(String(64))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeploymentRelease(Base):
    __tablename__ = "cp_deployment_releases"
    __table_args__ = (
        UniqueConstraint(
            "release_id", "runtime_mode", name="uq_cp_deployment_release_component"
        ),
        Index("ix_cp_deployment_environment_status", "environment", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[str] = mapped_column(String(80), index=True)
    environment: Mapped[str] = mapped_column(String(24), index=True)
    runtime_mode: Mapped[str] = mapped_column(String(24), default="combined")
    git_sha: Mapped[str] = mapped_column(String(120), default="")
    previous_release_id: Mapped[str] = mapped_column(String(120), default="")
    migration_version: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(
        String(24), default=DeploymentStatus.STARTING.value, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RuntimeLease(Base):
    __tablename__ = "cp_runtime_leases"

    lease_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ScheduledRun(Base):
    __tablename__ = "cp_scheduled_runs"
    __table_args__ = (
        UniqueConstraint("task_name", "schedule_key", name="uq_cp_scheduled_run_task_key"),
        Index("ix_cp_scheduled_status_started", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_name: Mapped[str] = mapped_column(String(100), index=True)
    schedule_key: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(
        String(24), default=ScheduledRunStatus.RUNNING.value, index=True
    )
    lease_owner: Mapped[str] = mapped_column(String(120), default="", index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class BackupRun(Base):
    __tablename__ = "cp_backup_runs"
    __table_args__ = (Index("ix_cp_backup_status_started", "status", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    status: Mapped[str] = mapped_column(
        String(24), default=BackupRunStatus.STARTED.value, index=True
    )
    backend: Mapped[str] = mapped_column(String(24), default="s3")
    storage_key: Mapped[str] = mapped_column(Text, default="")
    content_sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    release_id: Mapped[str] = mapped_column(String(120), default="")
    migration_version: Mapped[str] = mapped_column(String(80), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class RuntimeIncident(Base):
    __tablename__ = "cp_runtime_incidents"
    __table_args__ = (Index("ix_cp_incident_status_last_seen", "status", "last_seen_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="warning", index=True)
    source: Mapped[str] = mapped_column(String(80), default="runtime", index=True)
    summary: Mapped[str] = mapped_column(String(255), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(
        String(24), default=RuntimeIncidentStatus.OPEN.value, index=True
    )
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SecretRotationRun(Base):
    __tablename__ = "cp_secret_rotation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_version: Mapped[int] = mapped_column(Integer)
    to_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)
    profiles_rotated: Mapped[int] = mapped_column(Integer, default=0)
    orders_rotated: Mapped[int] = mapped_column(Integer, default=0)
    evidence_rotated: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class FeatureFlag(Base):
    __tablename__ = "cp_feature_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(String(255), default="")
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EvidenceAsset(Base):
    __tablename__ = "cp_evidence_assets"
    __table_args__ = (
        Index("ix_cp_evidence_retention_status", "retention_until", "status"),
        Index("ix_cp_evidence_provider_purpose", "provider_id", "purpose"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id"), index=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("cp_providers.id"), nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("cp_orders.id"), nullable=True, index=True)
    dispute_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("cp_support_tickets.id"), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(80), index=True)
    file_type: Mapped[str] = mapped_column(String(30), default="document")
    original_name: Mapped[str] = mapped_column(String(255), default="")
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    encrypted_telegram_file_id: Mapped[str] = mapped_column(Text, default="")
    storage_backend: Mapped[str] = mapped_column(String(20), default="telegram", index=True)
    storage_key: Mapped[str] = mapped_column(Text, default="")
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default=EvidenceStatus.REGISTERED.value, index=True)
    encryption_key_version: Mapped[int] = mapped_column(Integer, default=1)
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_access_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceAccessLog(Base):
    __tablename__ = "cp_evidence_access_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evidence_asset_id: Mapped[int] = mapped_column(ForeignKey("cp_evidence_assets.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(160), default="")
    outcome: Mapped[str] = mapped_column(String(30), default="allowed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SecretAccessLog(Base):
    __tablename__ = "cp_secret_access_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True, index=True)
    subject_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str] = mapped_column(String(80), default="")
    purpose: Mapped[str] = mapped_column(String(160), default="")
    fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PrivacyRequest(Base):
    __tablename__ = "cp_privacy_requests"
    __table_args__ = (Index("ix_cp_privacy_user_status", "user_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    request_type: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(24), default=PrivacyRequestStatus.PENDING.value, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    execute_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    result_reference: Mapped[str] = mapped_column(String(255), default="")
    rejection_reason: Mapped[str] = mapped_column(Text, default="")


class MediaAsset(Base):
    __tablename__ = "cp_media_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    telegram_file_id: Mapped[str] = mapped_column(Text)
    file_type: Mapped[str] = mapped_column(String(30))
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "cp_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), default="")
    entity_id: Mapped[str] = mapped_column(String(80), default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "cp_notifications"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_cp_notification_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    notification_type: Mapped[str] = mapped_column(String(60))
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    delivery_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PluginRecord(Base):
    __tablename__ = "cp_plugins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_name: Mapped[str] = mapped_column(String(180), unique=True)
    display_name: Mapped[str] = mapped_column(String(180), default="")
    version: Mapped[str] = mapped_column(String(40), default="")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    loaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ValidityType(StrEnum):
    DAYS_FROM_ACTIVATION = "days_from_activation"
    MONTHS_FROM_ACTIVATION = "months_from_activation"
    FIXED_OFFER_END = "fixed_offer_end"
    INVENTORY_END = "inventory_end"
    MANUAL = "manual"


class SubscriptionStartTrigger(StrEnum):
    PAYMENT_APPROVED = "payment_approved"
    DELIVERY = "delivery"
    USER_ACTIVATED = "user_activated"
    FIXED = "fixed"


class StudentSubscriptionStatus(StrEnum):
    PENDING = "pending"
    WAITING_ACTIVATION = "waiting_activation"
    ACTIVE = "active"
    EXPIRING = "expiring"
    EXPIRED = "expired"
    PAUSED = "paused"
    NEEDS_SUPPORT = "needs_support"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class ReservationStatus(StrEnum):
    HELD = "held"
    CONFIRMED = "confirmed"
    RELEASED = "released"
    EXPIRED = "expired"


class DeliveryJobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CatalogSection(Base):
    __tablename__ = "cp_catalog_sections"
    __table_args__ = (UniqueConstraint("provider_id", "name", name="uq_cp_provider_section_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(140))
    emoji: Mapped[str] = mapped_column(String(16), default="📂")
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CatalogServiceItem(Base):
    __tablename__ = "cp_catalog_services"
    __table_args__ = (UniqueConstraint("section_id", "name", name="uq_cp_section_service_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    section_id: Mapped[int] = mapped_column(
        ForeignKey("cp_catalog_sections.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    emoji: Mapped[str] = mapped_column(String(16), default="🧩")
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OfferCatalogPlacement(Base):
    __tablename__ = "cp_offer_catalog_placements"
    __table_args__ = (UniqueConstraint("offer_id", name="uq_cp_offer_catalog_placement"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    offer_id: Mapped[int] = mapped_column(
        ForeignKey("cp_offers.id", ondelete="CASCADE"), index=True
    )
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    section_id: Mapped[int] = mapped_column(
        ForeignKey("cp_catalog_sections.id", ondelete="CASCADE"), index=True
    )
    service_id: Mapped[int] = mapped_column(
        ForeignKey("cp_catalog_services.id", ondelete="CASCADE"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OfferValidityPolicy(Base):
    __tablename__ = "cp_offer_validity_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    offer_id: Mapped[int] = mapped_column(
        ForeignKey("cp_offers.id", ondelete="CASCADE"), unique=True, index=True
    )
    validity_type: Mapped[str] = mapped_column(
        String(40), default=ValidityType.DAYS_FROM_ACTIVATION.value
    )
    duration_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fixed_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_trigger: Mapped[str] = mapped_column(
        String(40), default=SubscriptionStartTrigger.DELIVERY.value
    )
    min_remaining_days: Mapped[int] = mapped_column(Integer, default=1)
    warranty_hours: Mapped[int] = mapped_column(Integer, default=24)
    objection_hours: Mapped[int] = mapped_column(Integer, default=24)
    renewal_mode: Mapped[str] = mapped_column(String(40), default="new_resource")
    reminder_days: Mapped[list[int]] = mapped_column(JSON, default=lambda: [7, 3, 1, 0])
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PurchaseReservation(Base):
    __tablename__ = "cp_purchase_reservations"
    __table_args__ = (UniqueConstraint("order_id", name="uq_cp_purchase_reservation_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True
    )
    offer_id: Mapped[int] = mapped_column(ForeignKey("cp_offers.id"), index=True)
    inventory_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_inventory_items.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(24), default=ReservationStatus.HELD.value)
    held_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StudentSubscription(Base):
    __tablename__ = "cp_student_subscriptions"
    __table_args__ = (UniqueConstraint("order_id", name="uq_cp_student_subscription_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("cp_offers.id"), index=True)
    inventory_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_inventory_items.id"), nullable=True
    )
    provider_name_snapshot: Mapped[str] = mapped_column(String(180))
    service_name_snapshot: Mapped[str] = mapped_column(String(220))
    offer_name_snapshot: Mapped[str] = mapped_column(String(220))
    validity_type: Mapped[str] = mapped_column(String(40))
    duration_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default=StudentSubscriptionStatus.PENDING.value, index=True
    )
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payment_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    warranty_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    objection_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pre_dispute_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pre_dispute_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_7d_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_3d_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_1d_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    expiry_notice_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ReceiptSnapshot(Base):
    __tablename__ = "cp_receipt_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), unique=True, index=True
    )
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_student_subscriptions.id"), nullable=True
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeliveryJob(Base):
    __tablename__ = "cp_delivery_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True
    )
    inventory_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_inventory_items.id"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(String(40), default="inventory_delivery")
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    status: Mapped[str] = mapped_column(
        String(24), default=DeliveryJobStatus.PENDING.value, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InventoryFingerprint(Base):
    __tablename__ = "cp_inventory_fingerprints"
    __table_args__ = (
        UniqueConstraint("offer_id", "fingerprint", name="uq_cp_inventory_fingerprint"),
        UniqueConstraint("inventory_item_id", name="uq_cp_inventory_fingerprint_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("cp_offers.id"), index=True)
    inventory_item_id: Mapped[int] = mapped_column(
        ForeignKey("cp_inventory_items.id", ondelete="CASCADE"), index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModuleRecord(Base):
    __tablename__ = "cp_module_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name_ar: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(40), default="")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    health_status: Mapped[str] = mapped_column(String(24), default="unknown")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MessageTemplate(Base):
    __tablename__ = "cp_message_templates"
    __table_args__ = (
        UniqueConstraint("template_key", "locale", name="uq_cp_message_template_locale"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_key: Mapped[str] = mapped_column(String(120), index=True)
    locale: Mapped[str] = mapped_column(String(12), default="ar")
    title: Mapped[str] = mapped_column(String(180), default="")
    body: Mapped[str] = mapped_column(Text)
    variables: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class OfferWorkflow(Base):
    __tablename__ = "cp_offer_workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    offer_id: Mapped[int] = mapped_column(
        ForeignKey("cp_offers.id", ondelete="CASCADE"), unique=True, index=True
    )
    workflow_key: Mapped[str] = mapped_column(String(80), default="standard")
    version: Mapped[int] = mapped_column(Integer, default=1)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    allowed_transitions: Mapped[dict[str, list[str]]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class OrderWorkflowState(Base):
    __tablename__ = "cp_order_workflow_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), unique=True, index=True
    )
    workflow_key: Mapped[str] = mapped_column(String(80), default="standard")
    workflow_version: Mapped[int] = mapped_column(Integer, default=1)
    current_status: Mapped[str] = mapped_column(String(40), index=True)
    current_step_key: Mapped[str] = mapped_column(String(80), default="")
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


Index("ix_cp_provider_active_status", Provider.is_active, Provider.status, Provider.name_ar)
Index("ix_cp_orders_provider_status_created", Order.provider_id, Order.status, Order.created_at)
Index("ix_cp_orders_user_created", Order.user_id, Order.created_at)
Index("ix_cp_offer_lifecycle", Offer.status, Offer.is_active, Offer.end_at)
Index("ix_cp_inventory_offer_status", InventoryItem.offer_id, InventoryItem.status)
Index(
    "ix_cp_inventory_lifecycle",
    InventoryItem.status,
    InventoryItem.expires_at,
    InventoryItem.offer_id,
)
Index("ix_cp_email_offer_status", EmailAccount.offer_id, EmailAccount.status)
Index("ix_cp_tickets_provider_status", SupportTicket.provider_id, SupportTicket.status)

# ---------------------------------------------------------------------------
# CampusPass IQ V5 — owner-controlled UI, activation guides, announcements,
# report packages, issue reporting and safe commerce settings.
# These are additive tables so existing V4 installations can upgrade without
# destructive ALTER statements.
# ---------------------------------------------------------------------------


class ActivationMode(StrEnum):
    EMAIL_PASSWORD = "email_password"
    EMAIL_CODE = "email_code"
    EMAIL_PASSWORD_CODE = "email_password_code"
    ACTIVATION_CODE = "activation_code"
    CUSTOM_DATA = "custom_data"
    MANUAL = "manual"


class GuideStepKind(StrEnum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    LINK = "link"


class AnnouncementStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    FINISHED = "finished"
    CANCELLED = "cancelled"


class FeatureBillingMode(StrEnum):
    FREE = "free"
    ONE_TIME = "one_time"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    TRIAL = "trial"
    HIDDEN = "hidden"


class ReportTier(StrEnum):
    STANDARD = "standard"
    PLUS = "plus"
    PRO = "pro"


class ReportFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class MenuContentType(StrEnum):
    SYSTEM_ACTION = "system_action"
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    LINK = "link"
    SUBMENU = "submenu"
    REPORT = "report"


class OfferActivationGuide(Base):
    __tablename__ = "cp_offer_activation_guides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    offer_id: Mapped[int] = mapped_column(
        ForeignKey("cp_offers.id", ondelete="CASCADE"), unique=True, index=True
    )
    activation_mode: Mapped[str] = mapped_column(
        String(40), default=ActivationMode.MANUAL.value, index=True
    )
    title: Mapped[str] = mapped_column(String(220), default="طريقة التسجيل والتفعيل")
    intro_text: Mapped[str] = mapped_column(Text, default="")
    acknowledgement_required: Mapped[bool] = mapped_column(Boolean, default=True)
    show_before_delivery: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    steps: Mapped[list[OfferGuideStep]] = relationship(
        back_populates="guide", cascade="all, delete-orphan", order_by="OfferGuideStep.position"
    )


class OfferGuideStep(Base):
    __tablename__ = "cp_offer_guide_steps"
    __table_args__ = (
        UniqueConstraint("guide_id", "position", name="uq_cp_offer_guide_step_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guide_id: Mapped[int] = mapped_column(
        ForeignKey("cp_offer_activation_guides.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(24), default=GuideStepKind.TEXT.value)
    text: Mapped[str] = mapped_column(Text, default="")
    telegram_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    button_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    guide: Mapped[OfferActivationGuide] = relationship(back_populates="steps")


class OrderGuideAcknowledgement(Base):
    __tablename__ = "cp_order_guide_acknowledgements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), unique=True, index=True
    )
    guide_id: Mapped[int] = mapped_column(ForeignKey("cp_offer_activation_guides.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id"), index=True)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MenuButtonContent(Base):
    __tablename__ = "cp_menu_button_contents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    button_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    content_type: Mapped[str] = mapped_column(
        String(30), default=MenuContentType.SYSTEM_ACTION.value, index=True
    )
    parent_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    telegram_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_action: Mapped[str | None] = mapped_column(String(100), nullable=True)
    report_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class FeaturePrice(Base):
    __tablename__ = "cp_feature_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feature_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name_ar: Mapped[str] = mapped_column(String(180))
    billing_mode: Mapped[str] = mapped_column(
        String(24), default=FeatureBillingMode.FREE.value, index=True
    )
    one_time_price_iqd: Mapped[int] = mapped_column(Integer, default=0)
    monthly_price_iqd: Mapped[int] = mapped_column(Integer, default=0)
    yearly_price_iqd: Mapped[int] = mapped_column(Integer, default=0)
    trial_days: Mapped[int] = mapped_column(Integer, default=0)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PriceChangeLog(Base):
    __tablename__ = "cp_price_change_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    price_key: Mapped[str] = mapped_column(String(160), index=True)
    old_value_iqd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_value_iqd: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Announcement(Base):
    __tablename__ = "cp_announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(220))
    body: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    button_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    button_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_scope: Mapped[str] = mapped_column(String(40), default="all", index=True)
    target_value: Mapped[str | None] = mapped_column(String(180), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pin_message: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(
        String(24), default=AnnouncementStatus.DRAFT.value, index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AnnouncementDelivery(Base):
    __tablename__ = "cp_announcement_deliveries"
    __table_args__ = (
        UniqueConstraint("announcement_id", "user_id", name="uq_cp_announcement_delivery"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    announcement_id: Mapped[int] = mapped_column(
        ForeignKey("cp_announcements.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unpinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class BotIssueReport(Base):
    __tablename__ = "cp_bot_issue_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str] = mapped_column(Text)
    file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_action: Mapped[str | None] = mapped_column(String(120), nullable=True)
    conversation_state: Mapped[str | None] = mapped_column(String(180), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    owner_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProviderReportSchedule(Base):
    __tablename__ = "cp_provider_report_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    report_type: Mapped[str] = mapped_column(String(60), default="general")
    tier: Mapped[str] = mapped_column(String(20), default=ReportTier.STANDARD.value)
    frequency: Mapped[str] = mapped_column(String(20), default=ReportFrequency.MONTHLY.value)
    custom_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# CampusPass IQ V6 — wallets, provider settlements, seat pools, scoped
# features and temporary-access safety.  All tables are additive.
# ---------------------------------------------------------------------------

class WalletOwnerType(StrEnum):
    USER = "user"
    PROVIDER = "provider"


class WalletEntryType(StrEnum):
    TOPUP = "topup"
    OVERPAYMENT = "overpayment"
    PURCHASE = "purchase"
    BOT_FEE = "bot_fee"
    BOT_FEE_REFUND = "bot_fee_refund"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"
    SETTLEMENT = "settlement"
    COMMISSION = "commission"
    REFERRAL = "referral"


class Wallet(Base):
    __tablename__ = "cp_wallets"
    __table_args__ = (
        UniqueConstraint("owner_type", "owner_id", name="uq_cp_wallet_owner"),
        Index("ix_cp_wallet_owner", "owner_type", "owner_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_type: Mapped[str] = mapped_column(String(20), index=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="IQD")
    balance_iqd: Mapped[int] = mapped_column(Integer, default=0)
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WalletEntry(Base):
    __tablename__ = "cp_wallet_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_cp_wallet_entry_idempotency"),
        Index("ix_cp_wallet_entries_wallet_created", "wallet_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("cp_wallets.id", ondelete="CASCADE"), index=True)
    entry_type: Mapped[str] = mapped_column(String(30), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    amount_iqd: Mapped[int] = mapped_column(Integer)
    balance_after_iqd: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("cp_orders.id"), nullable=True, index=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("cp_providers.id"), nullable=True, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SettlementStatus(StrEnum):
    OPEN = "open"
    NOTIFIED = "notified"
    PROOF_RECEIVED = "proof_received"
    UNDER_REVIEW = "under_review"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    OVERDUE = "overdue"
    WAIVED = "waived"


class ProviderSettlement(Base):
    __tablename__ = "cp_provider_settlements"
    __table_args__ = (
        UniqueConstraint("provider_id", "period_start", "period_end", name="uq_cp_provider_settlement_period"),
        Index("ix_cp_settlement_status_due", "status", "due_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    orders_count: Mapped[int] = mapped_column(Integer, default=0)
    gross_sales_iqd: Mapped[int] = mapped_column(Integer, default=0)
    owner_due_iqd: Mapped[int] = mapped_column(Integer, default=0)
    wallet_applied_iqd: Mapped[int] = mapped_column(Integer, default=0)
    remaining_due_iqd: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default=SettlementStatus.OPEN.value, index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    first_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proof_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    proof_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    submitted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ResourcePoolKind(StrEnum):
    SHARED_ACCOUNT = "shared_account"
    INDIVIDUAL_ACCOUNT = "individual_account"
    LICENSE = "license"
    INVITE = "invite"
    CODE = "code"
    TEMPORARY_ACCESS = "temporary_access"


class OfferResourcePool(Base):
    __tablename__ = "cp_offer_resource_pools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("cp_offers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(30), default=ResourcePoolKind.SHARED_ACCOUNT.value)
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    reserve_capacity: Mapped[int] = mapped_column(Integer, default=0)
    reusable_after_expiry: Mapped[bool] = mapped_column(Boolean, default=True)
    access_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deletion_required: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_pause_when_full: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ResourceSeatStatus(StrEnum):
    AVAILABLE = "available"
    HELD = "held"
    ACTIVE = "active"
    RELEASE_PENDING = "release_pending"
    BLOCKED = "blocked"


class ResourceSeat(Base):
    __tablename__ = "cp_resource_seats"
    __table_args__ = (
        UniqueConstraint("pool_id", "seat_number", name="uq_cp_pool_seat_number"),
        Index("ix_cp_resource_seat_available", "pool_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("cp_offer_resource_pools.id", ondelete="CASCADE"), index=True)
    seat_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default=ResourceSeatStatus.AVAILABLE.value, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("cp_orders.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True, index=True)
    held_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class TemporaryAccessSession(Base):
    __tablename__ = "cp_temporary_access_sessions"
    __table_args__ = (UniqueConstraint("order_id", name="uq_cp_temp_access_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True)
    seat_id: Mapped[int | None] = mapped_column(ForeignKey("cp_resource_seats.id"), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    deletion_required: Mapped[bool] = mapped_column(Boolean, default=True)
    deletion_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_30m_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_10m_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    expiry_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScopedFeatureOverride(Base):
    __tablename__ = "cp_scoped_feature_overrides"
    __table_args__ = (
        UniqueConstraint("feature_key", "scope_type", "scope_id", name="uq_cp_scoped_feature"),
        Index("ix_cp_scoped_feature_lookup", "feature_key", "scope_type", "scope_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feature_key: Mapped[str] = mapped_column(String(120), index=True)
    scope_type: Mapped[str] = mapped_column(String(24), default="global", index=True)
    scope_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------------------
# CampusPass IQ V7.0 — pilot validation and recovery evidence.
# ---------------------------------------------------------------------------

class PilotValidationStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


class RecoveryDrillStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


class PilotValidationRun(Base):
    __tablename__ = "cp_pilot_validation_runs"
    __table_args__ = (Index("ix_cp_pilot_validation_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[str] = mapped_column(String(160), index=True)
    environment: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20), default=PilotValidationStatus.RUNNING.value, index=True)
    checks_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    blocking_failures: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecoveryDrill(Base):
    __tablename__ = "cp_recovery_drills"
    __table_args__ = (Index("ix_cp_recovery_drill_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    drill_type: Mapped[str] = mapped_column(String(40), index=True)
    source_backup_id: Mapped[int | None] = mapped_column(ForeignKey("cp_backup_runs.id"), nullable=True)
    target_fingerprint: Mapped[str] = mapped_column(String(128), default="")
    restored_fingerprint: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(20), default=RecoveryDrillStatus.PLANNED.value, index=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# CampusPass IQ V8.0-A — Enterprise Core (commercial plans, billing,
# immutable double-entry ledger, teams, API keys and outbound webhooks).
# All structures are additive and preserve previous provider subscriptions.
# ---------------------------------------------------------------------------

class BusinessSubscriptionStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    GRACE = "grace"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class BusinessInvoiceStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    VOID = "void"
    OVERDUE = "overdue"


class LedgerDirection(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class WebhookDeliveryStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    RETRY = "retry"
    DEAD = "dead"


class BusinessPlan(Base):
    __tablename__ = "cp_business_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    monthly_price_iqd: Mapped[int] = mapped_column(Integer, default=0)
    included_team_members: Mapped[int] = mapped_column(Integer, default=1)
    included_api_requests: Mapped[int] = mapped_column(Integer, default=0)
    commission_bps: Mapped[int] = mapped_column(Integer, default=0)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class BusinessSubscription(Base):
    __tablename__ = "cp_business_subscriptions"
    __table_args__ = (
        UniqueConstraint("provider_id", name="uq_cp_business_subscription_provider"),
        Index("ix_cp_business_subscription_status_period", "status", "current_period_end"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("cp_business_plans.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default=BusinessSubscriptionStatus.TRIAL.value, index=True)
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    grace_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    seats_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    api_requests_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class BusinessInvoice(Base):
    __tablename__ = "cp_business_invoices"
    __table_args__ = (
        UniqueConstraint("invoice_number", name="uq_cp_business_invoice_number"),
        UniqueConstraint("idempotency_key", name="uq_cp_business_invoice_idempotency"),
        Index("ix_cp_business_invoice_provider_status", "provider_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True)
    subscription_id: Mapped[int | None] = mapped_column(ForeignKey("cp_business_subscriptions.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default=BusinessInvoiceStatus.DRAFT.value, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="IQD")
    subtotal_iqd: Mapped[int] = mapped_column(Integer, default=0)
    discount_iqd: Mapped[int] = mapped_column(Integer, default=0)
    tax_iqd: Mapped[int] = mapped_column(Integer, default=0)
    total_iqd: Mapped[int] = mapped_column(Integer, default=0)
    paid_iqd: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    line_items_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class LedgerTransaction(Base):
    __tablename__ = "cp_ledger_transactions"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_cp_ledger_transaction_idempotency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    reference_type: Mapped[str] = mapped_column(String(40), index=True)
    reference_id: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    currency: Mapped[str] = mapped_column(String(8), default="IQD")
    total_iqd: Mapped[int] = mapped_column(Integer)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AccountingEntry(Base):
    __tablename__ = "cp_accounting_entries"
    __table_args__ = (Index("ix_cp_accounting_entry_account_created", "account_code", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("cp_ledger_transactions.id", ondelete="RESTRICT"), index=True)
    account_code: Mapped[str] = mapped_column(String(80), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    amount_iqd: Mapped[int] = mapped_column(Integer)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("cp_providers.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderTeamMember(Base):
    __tablename__ = "cp_provider_team_members"
    __table_args__ = (
        UniqueConstraint("provider_id", "user_id", name="uq_cp_provider_team_member"),
        Index("ix_cp_provider_team_active", "provider_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    role_code: Mapped[str] = mapped_column(String(40), default="viewer")
    permissions_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    invited_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProviderApiKey(Base):
    __tablename__ = "cp_provider_api_keys"
    __table_args__ = (Index("ix_cp_provider_api_key_active", "provider_id", "is_active"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    scopes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderWebhookEndpoint(Base):
    __tablename__ = "cp_provider_webhook_endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    secret_encrypted: Mapped[str] = mapped_column(Text)
    events_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderWebhookDelivery(Base):
    __tablename__ = "cp_provider_webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("endpoint_id", "event_id", name="uq_cp_webhook_endpoint_event"),
        Index("ix_cp_webhook_delivery_status_retry", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(ForeignKey("cp_provider_webhook_endpoints.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(String(80), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(20), default=WebhookDeliveryStatus.PENDING.value, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# CampusPass IQ V8.0-B — Enterprise Scale & Final Validation.
# Additive runtime control plane for usage metering, distributed jobs,
# worker heartbeats, signed webhook attempts, and subscription lifecycle.
# ---------------------------------------------------------------------------

class DistributedJobStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    RETRY = "retry"
    DEAD = "dead"


class ApiUsageEvent(Base):
    __tablename__ = "cp_api_usage_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_cp_api_usage_event_idempotency"),
        Index("ix_cp_api_usage_provider_created", "provider_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True)
    api_key_id: Mapped[int | None] = mapped_column(ForeignKey("cp_provider_api_keys.id", ondelete="SET NULL"), nullable=True, index=True)
    route: Mapped[str] = mapped_column(String(180), index=True)
    units: Mapped[int] = mapped_column(Integer, default=1)
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApiUsageMonthlyAggregate(Base):
    __tablename__ = "cp_api_usage_monthly"
    __table_args__ = (
        UniqueConstraint("provider_id", "period_key", name="uq_cp_api_usage_monthly_provider_period"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True)
    period_key: Mapped[str] = mapped_column(String(7), index=True)
    request_units: Mapped[int] = mapped_column(Integer, default=0)
    rejected_units: Mapped[int] = mapped_column(Integer, default=0)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DistributedJob(Base):
    __tablename__ = "cp_distributed_jobs"
    __table_args__ = (
        UniqueConstraint("queue_name", "idempotency_key", name="uq_cp_distributed_job_queue_idempotency"),
        Index("ix_cp_distributed_job_claim", "queue_name", "status", "available_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    queue_name: Mapped[str] = mapped_column(String(80), index=True)
    job_type: Mapped[str] = mapped_column(String(100), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default=DistributedJobStatus.PENDING.value, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(180))
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=8)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WorkerHeartbeat(Base):
    __tablename__ = "cp_worker_heartbeats"
    __table_args__ = (UniqueConstraint("worker_id", name="uq_cp_worker_heartbeat_worker"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    runtime_mode: Mapped[str] = mapped_column(String(40), default="worker")
    release_id: Mapped[str] = mapped_column(String(160), default="")
    queues_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    hostname: Mapped[str] = mapped_column(String(180), default="")
    process_id: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookDeliveryAttempt(Base):
    __tablename__ = "cp_webhook_delivery_attempts"
    __table_args__ = (Index("ix_cp_webhook_attempt_delivery_created", "delivery_id", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("cp_provider_webhook_deliveries.id", ondelete="CASCADE"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    signature: Mapped[str] = mapped_column(String(128), default="")
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SubscriptionLifecycleEvent(Base):
    __tablename__ = "cp_subscription_lifecycle_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_cp_subscription_lifecycle_idempotency"),
        Index("ix_cp_subscription_lifecycle_provider_created", "provider_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("cp_business_subscriptions.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    from_status: Mapped[str] = mapped_column(String(24), default="")
    to_status: Mapped[str] = mapped_column(String(24), default="")
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# ---------------------------------------------------------------------------
# CampusPass IQ V11.1 — student commerce, Web App profile, dynamic marketplace.


class FavoriteTargetType(StrEnum):
    PROVIDER = "provider"
    SECTION = "section"
    OFFER = "offer"


class StudentFavorite(Base):
    __tablename__ = "cp_student_favorites"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "target_type",
            "target_id",
            name="uq_cp_student_favorite_target",
        ),
        Index("ix_cp_student_favorite_user_type", "user_id", "target_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("cp_users.id", ondelete="CASCADE"), index=True
    )
    target_type: Mapped[str] = mapped_column(String(20), index=True)
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderBrandProfile(Base):
    __tablename__ = "cp_provider_brand_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), unique=True, index=True
    )
    logo_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_color: Mapped[str] = mapped_column(String(7), default="#0B4AA9")
    secondary_color: Mapped[str] = mapped_column(String(7), default="#18C6C4")
    color_extracted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProviderWorkingHour(Base):
    __tablename__ = "cp_provider_working_hours"
    __table_args__ = (
        UniqueConstraint("provider_id", "weekday", name="uq_cp_provider_working_day"),
        Index("ix_cp_provider_working_hour_lookup", "provider_id", "weekday", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(Integer)
    opens_minute: Mapped[int] = mapped_column(Integer, default=600)
    closes_minute: Mapped[int] = mapped_column(Integer, default=1380)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CheckoutSnapshot(Base):
    __tablename__ = "cp_checkout_snapshots"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_cp_checkout_snapshot_order"),
        Index("ix_cp_checkout_snapshot_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), unique=True, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("cp_users.id", ondelete="CASCADE"), index=True
    )
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("cp_offers.id"), index=True)
    service_price_iqd: Mapped[int] = mapped_column(Integer)
    discount_iqd: Mapped[int] = mapped_column(Integer, default=0)
    bot_fee_iqd: Mapped[int] = mapped_column(Integer, default=0)
    wallet_fee_deduction_iqd: Mapped[int] = mapped_column(Integer, default=0)
    cash_due_iqd: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="IQD")
    pricing_version: Mapped[str] = mapped_column(String(30), default="v11.1")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PaymentAmountConfirmation(Base):
    __tablename__ = "cp_payment_amount_confirmations"
    __table_args__ = (
        UniqueConstraint("payment_proof_id", name="uq_cp_payment_amount_proof"),
        Index("ix_cp_payment_amount_order", "order_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_proof_id: Mapped[int] = mapped_column(
        ForeignKey("cp_payment_proofs.id", ondelete="CASCADE"), unique=True, index=True
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True
    )
    claimed_amount_iqd: Mapped[int] = mapped_column(Integer)
    confirmed_amount_iqd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudentRewardStatus(Base):
    __tablename__ = "cp_student_reward_statuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("cp_users.id", ondelete="CASCADE"), unique=True, index=True
    )
    status_points: Mapped[int] = mapped_column(Integer, default=0)
    successful_referrals: Mapped[int] = mapped_column(Integer, default=0)
    successful_purchases: Mapped[int] = mapped_column(Integer, default=0)
    status_link_shares: Mapped[int] = mapped_column(Integer, default=0)
    current_level: Mapped[str] = mapped_column(String(40), default="starter")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class StudentRewardEvent(Base):
    __tablename__ = "cp_student_reward_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_cp_student_reward_event_key"),
        Index("ix_cp_student_reward_event_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("cp_users.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    points_delta: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    reference_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# CampusPass IQ V11.2 — provider operations, unified inbox and fulfillment.
# ---------------------------------------------------------------------------


class ProviderInboxItemStatus(StrEnum):
    NEW = "new"
    OPENED = "opened"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class ProviderInboxItemKind(StrEnum):
    PAYMENT_PROOF = "payment_proof"
    STUDENT_ACTIVATION_EMAIL = "student_activation_email"
    STUDENT_CODE_RELAY = "student_code_relay"
    LOGOUT_PROOF = "logout_proof"
    WARRANTY = "warranty"
    OTP_MANUAL_REVIEW = "otp_manual_review"


class ActivationRequestStatus(StrEnum):
    WAITING_PROVIDER = "waiting_provider"
    WAITING_STUDENT_CODE = "waiting_student_code"
    CODE_RECEIVED = "code_received"
    ACTIVATED = "activated"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StudentCodeRelayStatus(StrEnum):
    PENDING = "pending"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    REJECTED = "rejected"


class LogoutProofStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    OVERDUE = "overdue"


class StudentRestrictionStatus(StrEnum):
    ACTIVE = "active"
    REVIEW = "review"
    LIFTED = "lifted"


class ProviderTermsAcceptance(Base):
    __tablename__ = "cp_provider_terms_acceptances"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "user_id",
            "terms_version",
            name="uq_cp_provider_terms_version",
        ),
        Index("ix_cp_provider_terms_user_provider", "user_id", "provider_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("cp_users.id", ondelete="CASCADE"), index=True
    )
    terms_version: Mapped[str] = mapped_column(String(32), default="provider-v1")
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ProviderOfferFulfillmentProfile(Base):
    __tablename__ = "cp_provider_offer_fulfillment_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    offer_id: Mapped[int] = mapped_column(
        ForeignKey("cp_offers.id", ondelete="CASCADE"), unique=True, index=True
    )
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    account_type: Mapped[str] = mapped_column(String(32), default="private")
    activation_mode: Mapped[str] = mapped_column(String(40), default="manual")
    shared_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unlimited_capacity: Mapped[bool] = mapped_column(Boolean, default=False)
    temporary_access_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logout_proof_required: Mapped[bool] = mapped_column(Boolean, default=False)
    student_email_required: Mapped[bool] = mapped_column(Boolean, default=False)
    student_code_relay_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    otp_lease_seconds: Mapped[int] = mapped_column(Integer, default=60)
    max_otp_attempts: Mapped[int] = mapped_column(Integer, default=3)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProviderPaymentMethodConfig(Base):
    __tablename__ = "cp_provider_payment_method_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_method_id: Mapped[int] = mapped_column(
        ForeignKey("cp_payment_methods.id", ondelete="CASCADE"), unique=True, index=True
    )
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(32), default="electronic")
    balance_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    proof_guide_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    proof_guide_text: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProviderInboxItem(Base):
    __tablename__ = "cp_provider_inbox_items"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_cp_provider_inbox_item_key"),
        Index(
            "ix_cp_provider_inbox_active",
            "provider_id",
            "status",
            "priority",
            "created_at",
        ),
        Index("ix_cp_provider_inbox_order", "order_id", "kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(
        String(24), default=ProviderInboxItemStatus.NEW.value, index=True
    )
    priority: Mapped[str] = mapped_column(String(20), default="normal", index=True)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_type: Mapped[str] = mapped_column(String(40), default="")
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_iqd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    assigned_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    processed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProviderInboxEvent(Base):
    __tablename__ = "cp_provider_inbox_events"
    __table_args__ = (Index("ix_cp_provider_inbox_event_item", "inbox_item_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inbox_item_id: Mapped[int] = mapped_column(
        ForeignKey("cp_provider_inbox_items.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudentActivationRequest(Base):
    __tablename__ = "cp_student_activation_requests"
    __table_args__ = (
        Index("ix_cp_student_activation_provider_status", "provider_id", "status", "created_at"),
        Index("ix_cp_student_activation_order", "order_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True
    )
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id"), index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("cp_users.id", ondelete="CASCADE"), index=True
    )
    encrypted_email: Mapped[str] = mapped_column(Text)
    email_hint: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(
        String(32), default=ActivationRequestStatus.WAITING_PROVIDER.value, index=True
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    code_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class StudentCodeRelay(Base):
    __tablename__ = "cp_student_code_relays"
    __table_args__ = (
        UniqueConstraint("activation_request_id", "attempt", name="uq_cp_code_relay_attempt"),
        Index("ix_cp_code_relay_status_expiry", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activation_request_id: Mapped[int] = mapped_column(
        ForeignKey("cp_student_activation_requests.id", ondelete="CASCADE"), index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    encrypted_code: Mapped[str] = mapped_column(Text)
    code_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(
        String(24), default=StudentCodeRelayStatus.PENDING.value, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OtpAccountLease(Base):
    __tablename__ = "cp_otp_account_leases"
    __table_args__ = (
        Index("ix_cp_otp_lease_account_expiry", "email_account_id", "expires_at"),
        Index("ix_cp_otp_lease_order", "order_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_account_id: Mapped[int] = mapped_column(
        ForeignKey("cp_email_accounts.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), index=True
    )
    holder_user_id: Mapped[int] = mapped_column(
        ForeignKey("cp_users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TemporaryLogoutProof(Base):
    __tablename__ = "cp_temporary_logout_proofs"
    __table_args__ = (
        UniqueConstraint("temporary_session_id", name="uq_cp_logout_proof_session"),
        Index("ix_cp_logout_proof_provider_status", "provider_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    temporary_session_id: Mapped[int] = mapped_column(
        ForeignKey("cp_temporary_access_sessions.id", ondelete="CASCADE"), unique=True, index=True
    )
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("cp_orders.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id"), index=True)
    evidence_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_evidence_assets.id"), nullable=True
    )
    telegram_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), default=LogoutProofStatus.PENDING.value, index=True
    )
    student_note: Mapped[str] = mapped_column(Text, default="")
    provider_note: Mapped[str] = mapped_column(Text, default="")
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class StudentOperationalRestriction(Base):
    __tablename__ = "cp_student_operational_restrictions"
    __table_args__ = (
        Index("ix_cp_student_restriction_active", "user_id", "status", "restriction_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("cp_users.id", ondelete="CASCADE"), index=True
    )
    provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_providers.id"), nullable=True, index=True
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_orders.id"), nullable=True, index=True
    )
    restriction_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(
        String(20), default=StudentRestrictionStatus.ACTIVE.value, index=True
    )
    reason: Mapped[str] = mapped_column(Text, default="")
    imposed_by: Mapped[str] = mapped_column(String(30), default="system")
    imposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    review_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lifted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )


# ---------------------------------------------------------------------------
# CampusPass IQ V11.3 — friends-only group purchases, escrow and warranty.
# ---------------------------------------------------------------------------


class FriendGroupStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    DELIVERING = "delivering"
    DELIVERED = "delivered"


class FriendMemberStatus(StrEnum):
    AWAITING_PAYMENT = "awaiting_payment"
    PAYMENT_REVIEW = "payment_review"
    PAID = "paid"
    REFUNDED = "refunded"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class FriendEscrowEntryType(StrEnum):
    DEPOSIT = "deposit"
    RELEASE_PROVIDER = "release_provider"
    RELEASE_OWNER = "release_owner"
    REFUND = "refund"


class WarrantyClaimStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    WAITING_STUDENT_ACTION = "waiting_student_action"
    REPLACEMENT_PENDING = "replacement_pending"
    WAITING_STUDENT_CONFIRMATION = "waiting_student_confirmation"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class WarrantyResolutionType(StrEnum):
    NEW_OTP_ALLOWED = "new_otp_allowed"
    REPLACEMENT_ACCOUNT = "replacement_account"
    TEXT_RESPONSE = "text_response"
    REJECTED = "rejected"


class FriendPackageConfig(Base):
    __tablename__ = "cp_friend_package_configs"
    __table_args__ = (
        UniqueConstraint("offer_id", name="uq_cp_friend_package_offer"),
        Index("ix_cp_friend_package_provider_enabled", "provider_id", "is_enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    offer_id: Mapped[int] = mapped_column(
        ForeignKey("cp_offers.id", ondelete="CASCADE"), unique=True, index=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    required_members: Mapped[int] = mapped_column(Integer, default=2)
    join_window_hours: Mapped[int] = mapped_column(Integer, default=24)
    full_bot_fee_per_member: Mapped[bool] = mapped_column(Boolean, default=True)
    terms_version: Mapped[str] = mapped_column(String(30), default="v1")
    accepted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class FriendGroup(Base):
    __tablename__ = "cp_friend_groups"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_cp_friend_group_public"),
        UniqueConstraint("join_token_hash", name="uq_cp_friend_group_token"),
        Index("ix_cp_friend_group_expiry", "status", "expires_at"),
        Index("ix_cp_friend_group_offer_status", "offer_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    join_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    config_id: Mapped[int] = mapped_column(
        ForeignKey("cp_friend_package_configs.id", ondelete="CASCADE"), index=True
    )
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("cp_offers.id"), index=True)
    creator_user_id: Mapped[int] = mapped_column(
        ForeignKey("cp_users.id", ondelete="CASCADE"), index=True
    )
    inventory_item_id: Mapped[int] = mapped_column(
        ForeignKey("cp_inventory_items.id"), index=True
    )
    reservation_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_orders.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(24), default=FriendGroupStatus.OPEN.value, index=True
    )
    required_members: Mapped[int] = mapped_column(Integer)
    paid_members: Mapped[int] = mapped_column(Integer, default=0)
    service_total_iqd: Mapped[int] = mapped_column(Integer)
    bot_fee_per_member_iqd: Mapped[int] = mapped_column(Integer)
    escrow_service_iqd: Mapped[int] = mapped_column(Integer, default=0)
    escrow_bot_fee_iqd: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class FriendGroupMember(Base):
    __tablename__ = "cp_friend_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_cp_friend_group_user"),
        UniqueConstraint("order_id", name="uq_cp_friend_member_order"),
        Index("ix_cp_friend_member_group_status", "group_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("cp_friend_groups.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("cp_users.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="CASCADE"), unique=True, index=True
    )
    member_index: Mapped[int] = mapped_column(Integer)
    is_creator: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(
        String(24), default=FriendMemberStatus.AWAITING_PAYMENT.value, index=True
    )
    service_share_iqd: Mapped[int] = mapped_column(Integer)
    bot_fee_iqd: Mapped[int] = mapped_column(Integer)
    wallet_fee_deduction_iqd: Mapped[int] = mapped_column(Integer, default=0)
    cash_due_iqd: Mapped[int] = mapped_column(Integer)
    paid_amount_iqd: Mapped[int] = mapped_column(Integer, default=0)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class FriendEscrowEntry(Base):
    __tablename__ = "cp_friend_escrow_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_cp_friend_escrow_key"),
        Index("ix_cp_friend_escrow_group_created", "group_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("cp_friend_groups.id", ondelete="CASCADE"), index=True
    )
    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_friend_group_members.id", ondelete="SET NULL"), nullable=True, index=True
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entry_type: Mapped[str] = mapped_column(String(32), index=True)
    service_amount_iqd: Mapped[int] = mapped_column(Integer, default=0)
    bot_fee_iqd: Mapped[int] = mapped_column(Integer, default=0)
    total_iqd: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WarrantyPolicy(Base):
    __tablename__ = "cp_warranty_policies"
    __table_args__ = (
        UniqueConstraint("offer_id", name="uq_cp_warranty_policy_offer"),
        Index("ix_cp_warranty_provider_enabled", "provider_id", "is_enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    offer_id: Mapped[int] = mapped_column(
        ForeignKey("cp_offers.id", ondelete="CASCADE"), unique=True, index=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    coverage_mode: Mapped[str] = mapped_column(String(32), default="subscription_period")
    response_sla_minutes: Mapped[int] = mapped_column(Integer, default=60)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WarrantyClaim(Base):
    __tablename__ = "cp_warranty_claims"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_cp_warranty_claim_public"),
        UniqueConstraint("idempotency_key", name="uq_cp_warranty_claim_key"),
        Index("ix_cp_warranty_claim_provider_status", "provider_id", "status", "created_at"),
        Index("ix_cp_warranty_claim_subscription", "subscription_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("cp_warranty_policies.id"), index=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("cp_student_subscriptions.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[int] = mapped_column(ForeignKey("cp_orders.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id"), index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("cp_users.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(
        String(40), default=WarrantyClaimStatus.OPEN.value, index=True
    )
    screenshot_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    student_note: Mapped[str] = mapped_column(Text, default="")
    provider_note: Mapped[str] = mapped_column(Text, default="")
    resolution_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    student_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WarrantyClaimEvent(Base):
    __tablename__ = "cp_warranty_claim_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_cp_warranty_event_key"),
        Index("ix_cp_warranty_event_claim", "claim_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(
        ForeignKey("cp_warranty_claims.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WarrantyReplacement(Base):
    __tablename__ = "cp_warranty_replacements"
    __table_args__ = (
        UniqueConstraint("claim_id", name="uq_cp_warranty_replacement_claim"),
        UniqueConstraint("new_inventory_item_id", name="uq_cp_warranty_replacement_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(
        ForeignKey("cp_warranty_claims.id", ondelete="CASCADE"), unique=True, index=True
    )
    old_inventory_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_inventory_items.id"), nullable=True
    )
    new_inventory_item_id: Mapped[int] = mapped_column(
        ForeignKey("cp_inventory_items.id"), index=True
    )
    delivery_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_delivery_jobs.id"), nullable=True, unique=True
    )
    replaced_by_user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

# ---------------------------------------------------------------------------
# CampusPass IQ V11.4 — Owner commerce control plane.
# Provider billing, central inbox, targeted campaigns, hybrid bundles and
# reward tasks are additive and keep V11.3 financial history immutable.
# ---------------------------------------------------------------------------


class OwnerInboxKind(StrEnum):
    APPEAL = "appeal"
    MISSING_SERVICE = "missing_service"
    BOT_ISSUE = "bot_issue"
    CUSTOM_QUESTION = "custom_question"
    BILLING_PROOF = "billing_proof"
    AD_REQUEST = "ad_request"


class OwnerInboxStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    AWAITING_PAYMENT = "awaiting_payment"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    ACTIVE = "active"
    FINISHED = "finished"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class HybridBundleStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class HybridPurchaseStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    ALLOCATED = "allocated"
    FULFILLING = "fulfilling"
    COMPLETED = "completed"
    REFUNDED = "refunded"
    FAILED = "failed"


class RewardTaskStatus(StrEnum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    REJECTED = "rejected"


class FinancialProofRegistry(Base):
    __tablename__ = "cp_financial_proof_registry"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_cp_financial_proof_fingerprint"),
        Index("ix_cp_financial_proof_source", "source_type", "source_id"),
        Index("ix_cp_financial_proof_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source_type: Mapped[str] = mapped_column(String(40), index=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    submitted_by_user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id"), index=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("cp_providers.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderBillingPolicy(Base):
    __tablename__ = "cp_provider_billing_policies"
    __table_args__ = (
        UniqueConstraint("provider_id", name="uq_cp_provider_billing_policy_provider"),
        Index("ix_cp_provider_billing_next", "is_active", "next_invoice_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), unique=True, index=True
    )
    cycle_days: Mapped[int] = mapped_column(Integer, default=30)
    due_hours: Mapped[int] = mapped_column(Integer, default=48)
    fixed_service_fee_iqd: Mapped[int] = mapped_column(Integer, default=0)
    ad_hourly_rate_iqd: Mapped[int] = mapped_column(Integer, default=1000)
    auto_suspend: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    next_invoice_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class BusinessInvoiceProof(Base):
    __tablename__ = "cp_business_invoice_proofs"
    __table_args__ = (
        UniqueConstraint("file_fingerprint", name="uq_cp_business_invoice_proof_fingerprint"),
        Index("ix_cp_business_invoice_proof_status", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("cp_business_invoices.id", ondelete="CASCADE"), index=True
    )
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id"), index=True)
    submitted_by_user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id"), index=True)
    file_id: Mapped[str] = mapped_column(Text)
    file_type: Mapped[str] = mapped_column(String(24), default="photo")
    file_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    claimed_amount_iqd: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OwnerInboxItem(Base):
    __tablename__ = "cp_owner_inbox_items"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_cp_owner_inbox_source"),
        Index("ix_cp_owner_inbox_status_kind", "status", "kind", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(24), default=OwnerInboxStatus.NEW.value, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    source_type: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[int] = mapped_column(Integer)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("cp_providers.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("cp_orders.id"), nullable=True, index=True)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    summary: Mapped[str] = mapped_column(String(500), default="")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AdCampaign(Base):
    __tablename__ = "cp_ad_campaigns"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_cp_ad_campaign_public"),
        UniqueConstraint("idempotency_key", name="uq_cp_ad_campaign_key"),
        Index("ix_cp_ad_campaign_status_schedule", "status", "starts_at", "ends_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("cp_providers.id"), nullable=True, index=True)
    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id"), index=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    campaign_type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(220))
    body: Mapped[str] = mapped_column(Text)
    offer_id: Mapped[int | None] = mapped_column(ForeignKey("cp_offers.id"), nullable=True, index=True)
    audience_rule_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duration_hours: Mapped[int] = mapped_column(Integer, default=24)
    hourly_rate_iqd: Mapped[int] = mapped_column(Integer, default=1000)
    total_iqd: Mapped[int] = mapped_column(Integer, default=0)
    proof_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    proof_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    announcement_id: Mapped[int | None] = mapped_column(ForeignKey("cp_announcements.id"), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(24), default=CampaignStatus.DRAFT.value, index=True)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AdCampaignRecipient(Base):
    __tablename__ = "cp_ad_campaign_recipients"
    __table_args__ = (
        UniqueConstraint("campaign_id", "user_id", name="uq_cp_ad_campaign_recipient"),
        Index("ix_cp_ad_recipient_status", "campaign_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("cp_ad_campaigns.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CouponCampaign(Base):
    __tablename__ = "cp_coupon_campaigns"
    __table_args__ = (
        UniqueConstraint("coupon_id", name="uq_cp_coupon_campaign_coupon"),
        Index("ix_cp_coupon_campaign_status", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    coupon_id: Mapped[int] = mapped_column(ForeignKey("cp_order_coupons.id", ondelete="CASCADE"), unique=True, index=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("cp_providers.id"), nullable=True, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id"))
    audience_rule_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    assigned_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CouponAssignment(Base):
    __tablename__ = "cp_coupon_assignments"
    __table_args__ = (
        UniqueConstraint("campaign_id", "user_id", name="uq_cp_coupon_assignment_user"),
        Index("ix_cp_coupon_assignment_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("cp_coupon_campaigns.id", ondelete="CASCADE"), index=True)
    coupon_id: Mapped[int] = mapped_column(ForeignKey("cp_order_coupons.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="available", index=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HybridBundle(Base):
    __tablename__ = "cp_hybrid_bundles"
    __table_args__ = (UniqueConstraint("public_id", name="uq_cp_hybrid_bundle_public"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str] = mapped_column(Text, default="")
    price_iqd: Mapped[int] = mapped_column(Integer)
    bot_fee_iqd: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default=HybridBundleStatus.DRAFT.value, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class HybridBundleComponent(Base):
    __tablename__ = "cp_hybrid_bundle_components"
    __table_args__ = (
        UniqueConstraint("bundle_id", "offer_id", name="uq_cp_hybrid_bundle_offer"),
        Index("ix_cp_hybrid_component_provider", "provider_id", "bundle_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("cp_hybrid_bundles.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("cp_offers.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id"), index=True)
    provider_share_iqd: Mapped[int] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class HybridBundlePurchase(Base):
    __tablename__ = "cp_hybrid_bundle_purchases"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_cp_hybrid_purchase_public"),
        UniqueConstraint("idempotency_key", name="uq_cp_hybrid_purchase_key"),
        Index("ix_cp_hybrid_purchase_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("cp_hybrid_bundles.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default=HybridPurchaseStatus.PENDING.value, index=True)
    total_iqd: Mapped[int] = mapped_column(Integer)
    bot_fee_iqd: Mapped[int] = mapped_column(Integer)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HybridInventoryHold(Base):
    __tablename__ = "cp_hybrid_inventory_holds"
    __table_args__ = (
        UniqueConstraint("purchase_id", "component_id", name="uq_cp_hybrid_hold_component"),
        Index("ix_cp_hybrid_hold_status_expiry", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_id: Mapped[int] = mapped_column(
        ForeignKey("cp_hybrid_bundle_purchases.id", ondelete="CASCADE"), index=True
    )
    component_id: Mapped[int] = mapped_column(
        ForeignKey("cp_hybrid_bundle_components.id", ondelete="CASCADE"), index=True
    )
    inventory_item_id: Mapped[int] = mapped_column(
        ForeignKey("cp_inventory_items.id"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="held", index=True)
    consumed_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_orders.id"), nullable=True, unique=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HybridPurchaseProof(Base):
    __tablename__ = "cp_hybrid_purchase_proofs"
    __table_args__ = (
        UniqueConstraint("file_fingerprint", name="uq_cp_hybrid_purchase_proof_fingerprint"),
        Index("ix_cp_hybrid_purchase_proof_status", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_id: Mapped[int] = mapped_column(
        ForeignKey("cp_hybrid_bundle_purchases.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id"), index=True)
    file_id: Mapped[str] = mapped_column(Text)
    file_type: Mapped[str] = mapped_column(String(24), default="photo")
    file_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    claimed_amount_iqd: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HybridRevenueAllocation(Base):
    __tablename__ = "cp_hybrid_revenue_allocations"
    __table_args__ = (
        UniqueConstraint("purchase_id", "component_id", name="uq_cp_hybrid_allocation_component"),
        UniqueConstraint("idempotency_key", name="uq_cp_hybrid_allocation_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("cp_hybrid_bundle_purchases.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("cp_hybrid_bundle_components.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_orders.id"), nullable=True, unique=True, index=True
    )
    amount_iqd: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RewardTaskCampaign(Base):
    __tablename__ = "cp_reward_task_campaigns"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_cp_reward_task_public"),
        UniqueConstraint("idempotency_key", name="uq_cp_reward_task_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("cp_providers.id"), index=True)
    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id"))
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("cp_users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(220))
    channel_chat_id: Mapped[int] = mapped_column(BigInteger)
    channel_url: Mapped[str] = mapped_column(Text)
    reward_iqd: Mapped[int] = mapped_column(Integer)
    requested_count: Mapped[int] = mapped_column(Integer)
    capacity_count: Mapped[int] = mapped_column(Integer)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    budget_iqd: Mapped[int] = mapped_column(Integer)
    spent_iqd: Mapped[int] = mapped_column(Integer, default=0)
    proof_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    proof_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(24), default=RewardTaskStatus.DRAFT.value, index=True)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RewardTaskCompletion(Base):
    __tablename__ = "cp_reward_task_completions"
    __table_args__ = (
        UniqueConstraint("campaign_id", "user_id", name="uq_cp_reward_completion_user"),
        UniqueConstraint("idempotency_key", name="uq_cp_reward_completion_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("cp_reward_task_campaigns.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    wallet_entry_id: Mapped[int | None] = mapped_column(ForeignKey("cp_wallet_entries.id"), nullable=True, unique=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

# ---------------------------------------------------------------------------
# CampusPass IQ V11.5 - branded reports, menu revisions and health history.
# ---------------------------------------------------------------------------


class ReportArtifactStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"


class ReportArtifact(Base):
    __tablename__ = "cp_report_artifacts"
    __table_args__ = (
        UniqueConstraint("report_id", "format", name="uq_cp_report_artifact_format"),
        Index("ix_cp_report_artifact_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("cp_reports.id", ondelete="CASCADE"), index=True
    )
    format: Mapped[str] = mapped_column(String(12), index=True)
    status: Mapped[str] = mapped_column(
        String(20), default=ReportArtifactStatus.PENDING.value, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), default="")
    media_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class DailyProviderMetric(Base):
    __tablename__ = "cp_daily_provider_metrics"
    __table_args__ = (
        UniqueConstraint("provider_id", "metric_date", name="uq_cp_provider_metric_day"),
        Index("ix_cp_provider_metric_date", "metric_date", "provider_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("cp_providers.id", ondelete="CASCADE"), index=True
    )
    metric_date: Mapped[date] = mapped_column(Date, index=True)
    orders_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_or_problem_count: Mapped[int] = mapped_column(Integer, default=0)
    active_subscriptions_count: Mapped[int] = mapped_column(Integer, default=0)
    sales_iqd: Mapped[int] = mapped_column(Integer, default=0)
    bot_fees_iqd: Mapped[int] = mapped_column(Integer, default=0)
    provider_net_iqd: Mapped[int] = mapped_column(Integer, default=0)
    average_confirmation_seconds: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MenuRevision(Base):
    __tablename__ = "cp_menu_revisions"
    __table_args__ = (
        UniqueConstraint("revision", name="uq_cp_menu_revision_number"),
        Index("ix_cp_menu_revision_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    label: Mapped[str] = mapped_column(String(160), default="")
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("cp_users.id"), nullable=True
    )
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SystemHealthSnapshot(Base):
    __tablename__ = "cp_system_health_snapshots"
    __table_args__ = (
        Index("ix_cp_system_health_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    release_id: Mapped[str] = mapped_column(String(100), default="")
    runtime_mode: Mapped[str] = mapped_column(String(30), default="")
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checks_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TelegramUpdateInbox(Base):
    __tablename__ = "cp_telegram_update_inbox"
    __table_args__ = (
        UniqueConstraint("update_id", name="uq_cp_telegram_update_id"),
        Index("ix_cp_telegram_update_claim", "status", "available_at", "update_id"),
        Index("ix_cp_telegram_update_lease", "lease_expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    update_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=8)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    release_id: Mapped[str] = mapped_column(String(160), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeploymentGateRun(Base):
    __tablename__ = "cp_deployment_gate_runs"
    __table_args__ = (
        Index("ix_cp_deployment_gate_release_started", "release_id", "started_at"),
        Index("ix_cp_deployment_gate_status_started", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    release_id: Mapped[str] = mapped_column(String(160), index=True)
    environment: Mapped[str] = mapped_column(String(30), default="")
    runtime_mode: Mapped[str] = mapped_column(String(30), default="")
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    checks_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RuntimeConfigGeneration(Base):
    __tablename__ = "cp_runtime_config_generations"
    __table_args__ = (
        UniqueConstraint("namespace", name="uq_cp_runtime_config_namespace"),
        Index("ix_cp_runtime_config_updated", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    namespace: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ReleaseCompatibility(Base):
    __tablename__ = "cp_release_compatibility"
    __table_args__ = (
        UniqueConstraint("release_id", name="uq_cp_release_compatibility_release"),
        Index("ix_cp_release_compatibility_status_checked", "status", "checked_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    version: Mapped[str] = mapped_column(String(100), default="")
    schema_head: Mapped[str] = mapped_column(String(160), default="")
    minimum_release_version: Mapped[str] = mapped_column(String(100), default="")
    minimum_schema_head: Mapped[str] = mapped_column(String(160), default="")
    callback_schema_version: Mapped[int] = mapped_column(Integer, default=1)
    event_schema_version: Mapped[int] = mapped_column(Integer, default=1)
    rollout_percent: Mapped[float] = mapped_column(Float, default=100.0)
    status: Mapped[str] = mapped_column(String(20), default="starting", index=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
