from __future__ import annotations

"""Central Arabic presentation labels for database statuses.

Database values remain stable English identifiers. User-facing handlers must use
these helpers instead of exposing raw enum values, which keeps wording consistent
and lets future migrations change presentation without rewriting historical rows.
"""

ORDER_STATUS_AR = {
    "draft": "مسودة",
    "waiting_payment": "بانتظار الدفع",
    "payment_proof_received": "تم استلام إثبات الدفع",
    "payment_review": "قيد مراجعة الدفع",
    "payment_rejected": "إثبات الدفع مرفوض",
    "paid": "تم تأكيد الدفع",
    "waiting_fulfillment": "بانتظار تجهيز الخدمة",
    "email_reserved": "تم حجز البريد",
    "waiting_code": "بانتظار الرمز",
    "code_found": "تم العثور على الرمز",
    "delivered": "تم تسليم البيانات",
    "processing": "قيد التنفيذ",
    "completed": "مكتمل",
    "needs_support": "يحتاج دعماً",
    "cancelled": "ملغي",
    "refunded": "مسترجع",
    "disputed": "قيد النزاع",
}

SUBSCRIPTION_STATUS_AR = {
    "pending": "قيد الإنشاء",
    "waiting_activation": "بانتظار التفعيل",
    "active": "فعال",
    "expiring": "ينتهي قريباً",
    "expired": "منتهي",
    "paused": "موقوف مؤقتاً",
    "needs_support": "يحتاج دعماً",
    "cancelled": "ملغي",
    "refunded": "مسترجع",
}

TICKET_STATUS_AR = {
    "open": "مفتوحة",
    "waiting_user": "بانتظار رد المستخدم",
    "waiting_provider": "بانتظار رد المنصة",
    "in_progress": "قيد المعالجة",
    "resolved": "تم الحل",
    "closed": "مغلقة",
}

PROVIDER_STATUS_AR = {
    "pending": "بانتظار المراجعة",
    "active": "فعالة",
    "paused": "متوقفة مؤقتاً",
    "suspended": "موقوفة",
    "rejected": "مرفوضة",
}

DISPUTE_STATUS_AR = {
    "open": "مفتوح",
    "under_review": "قيد المراجعة",
    "waiting_user": "بانتظار المستخدم",
    "waiting_provider": "بانتظار المنصة",
    "resolved": "تم الحل",
    "rejected": "مرفوض",
    "cancelled": "ملغي",
    "closed": "مغلق",
}

DISPUTE_RESOLUTION_AR = {
    "none": "لم يصدر قرار بعد",
    "full_refund": "استرجاع كامل",
    "partial_refund": "استرجاع جزئي",
    "subscription_extension": "تمديد الاشتراك",
    "replacement_required": "استبدال الخدمة",
    "rejected": "رفض النزاع",
}

SENDER_ROLE_AR = {
    "user": "المستخدم",
    "provider": "المنصة",
    "staff": "موظف المنصة",
    "admin": "إدارة البوت",
    "system": "النظام",
}

REFUND_STATUS_AR = {
    "requested": "مطلوب",
    "approved": "معتمد",
    "transfer_reported": "تم تسجيل التحويل",
    "completed": "مكتمل",
    "rejected": "مرفوض",
    "cancelled": "ملغي",
    "failed": "فشل",
}

PAYMENT_STATUS_AR = {
    "pending": "قيد المراجعة",
    "confirmed": "مؤكد",
    "failed": "فشل",
    "refunded": "مسترجع",
}


def status_label(value: str | None, mapping: dict[str, str]) -> str:
    normalized = str(value or "").strip().lower()
    return mapping.get(normalized, "غير معروف")


def order_status_label(value: str | None) -> str:
    return status_label(value, ORDER_STATUS_AR)


def subscription_status_label(value: str | None) -> str:
    return status_label(value, SUBSCRIPTION_STATUS_AR)


def ticket_status_label(value: str | None) -> str:
    return status_label(value, TICKET_STATUS_AR)


def payment_status_label(value: str | None) -> str:
    return status_label(value, PAYMENT_STATUS_AR)


def provider_status_label(value: str | None) -> str:
    return status_label(value, PROVIDER_STATUS_AR)


def dispute_status_label(value: str | None) -> str:
    return status_label(value, DISPUTE_STATUS_AR)


def refund_status_label(value: str | None) -> str:
    return status_label(value, REFUND_STATUS_AR)


def dispute_resolution_label(value: str | None) -> str:
    return status_label(value, DISPUTE_RESOLUTION_AR)


def sender_role_label(value: str | None) -> str:
    return status_label(value, SENDER_ROLE_AR)


def delivery_estimate_label(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    estimates = {
        "inventory_code": "عادة خلال دقائق بعد تأكيد الدفع",
        "inventory_account": "عادة خلال دقائق بعد تأكيد الدفع",
        "email_code": "بعد وصول رمز البريد، عادة خلال دقائق",
        "student_email_invite": "حسب وصول الدعوة، والهدف خلال ساعات",
        "manual": "مراجعة بشرية؛ الهدف خلال 24 ساعة",
        "file_service": "مراجعة وتجهيز؛ الهدف خلال 24 ساعة",
    }
    return estimates.get(normalized, "يُحدد حسب نوع الخدمة وحالة الطلب")
