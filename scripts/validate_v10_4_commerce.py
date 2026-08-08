from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

# This validator exercises database services without opening Telegram. Keep it
# runnable in minimal CI environments where Aiogram is installed only in the
# Docker build stage.
try:
    import aiogram  # noqa: F401
except ModuleNotFoundError:
    aiogram_stub = ModuleType("aiogram")
    aiogram_stub.Bot = type("Bot", (), {})
    sys.modules["aiogram"] = aiogram_stub

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    Category,
    Offer,
    OfferStatus,
    Order,
    OrderCoupon,
    OrderCouponType,
    OrderStatus,
    PaymentProof,
    PointsTransaction,
    Provider,
    User,
    UserBenefit,
    Wallet,
    WalletEntry,
    WalletEntryType,
    WalletOwnerType,
)
from app.services.finance import FinanceService
from app.services.order_coupons import OrderCouponService
from app.services.payments import PaymentService
from app.services.wallets import WalletService


class AsyncSessionAdapter:
    """Small async facade over a synchronous SQLite session for service checks."""

    def __init__(self, session: Session) -> None:
        self.sync = session
        self.info = session.info

    def add(self, value: object) -> None:
        self.sync.add(value)

    async def flush(self) -> None:
        self.sync.flush()

    async def scalar(self, statement):
        return self.sync.scalar(statement)

    async def scalars(self, statement):
        return self.sync.scalars(statement)

    async def get(self, model, key):
        return self.sync.get(model, key)

    async def execute(self, statement, params=None):
        return self.sync.execute(statement, params or {})


class FakeOrderService:
    async def change_status(
        self,
        session: AsyncSessionAdapter,
        order: Order,
        new_status: str,
        actor_user_id: int | None = None,
        note: str = "",
        metadata: dict | None = None,
    ) -> None:
        del actor_user_id, note, metadata
        order.status = new_status
        await session.flush()

    async def extend_reservation_for_review(
        self, session: AsyncSessionAdapter, order: Order, hours: int
    ) -> None:
        del order, hours
        await session.flush()


class FakeUserService:
    async def add_points(
        self,
        session: AsyncSessionAdapter,
        user: User,
        amount: int,
        reason: str,
        reference_type: str | None = None,
        reference_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> bool:
        if idempotency_key and await session.scalar(
            select(PointsTransaction.id).where(
                PointsTransaction.idempotency_key == idempotency_key
            )
        ):
            return False
        user.points += amount
        session.add(
            PointsTransaction(
                user_id=user.id,
                amount=amount,
                reason=reason,
                reference_type=reference_type,
                reference_id=reference_id,
                idempotency_key=idempotency_key,
            )
        )
        await session.flush()
        return True


class FakeNotificationService:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, str]] = []

    async def send_user(
        self,
        session: AsyncSessionAdapter,
        user: User,
        title: str,
        body: str,
        reply_markup=None,
        raise_on_error: bool = False,
        idempotency_key: str | None = None,
    ) -> bool:
        del session, reply_markup, raise_on_error, idempotency_key
        self.messages.append((user.id, title, body))
        return True


def callback_audit() -> tuple[int, int]:
    callback_count = 0
    longest_literal = 0
    failures: list[str] = []
    for path in sorted((ROOT / "app" / "bot" / "handlers").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            callback_arg = any(arg.arg == "callback" for arg in node.args.args)
            is_callback_handler = any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "callback_query"
                for decorator in node.decorator_list
            )
            if not (callback_arg and is_callback_handler):
                continue
            callback_count += 1
            body = list(node.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body = body[1:]
            first = body[0] if body else None
            valid_first = (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Await)
                and isinstance(first.value.value, ast.Call)
                and isinstance(first.value.value.func, ast.Attribute)
                and isinstance(first.value.value.func.value, ast.Name)
                and first.value.value.func.value.id == "callback"
                and first.value.value.func.attr == "answer"
            )
            if not valid_first:
                failures.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}")
            answers = 0
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == "callback"
                    and child.func.attr == "answer"
                ):
                    answers += 1
            if answers != 1:
                failures.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}:answers={answers}"
                )
        for child in ast.walk(tree):
            if not isinstance(child, ast.Call):
                continue
            for keyword in child.keywords:
                if keyword.arg == "callback_data" and isinstance(keyword.value, ast.Constant):
                    if isinstance(keyword.value.value, str):
                        longest_literal = max(
                            longest_literal, len(keyword.value.value.encode("utf-8"))
                        )
    if failures:
        raise AssertionError("Callback audit failed: " + ", ".join(failures[:20]))
    if longest_literal > 64:
        raise AssertionError(f"Static callback_data literal exceeds 64 bytes: {longest_literal}")
    return callback_count, longest_literal


def build_fixture(session: Session):
    provider = Provider(name_ar="منصة الاختبار", name_en="Test", slug="test-platform")
    category = Category(name="اشتراكات الاختبار")
    referrer = User(
        telegram_id=1001,
        telegram_username="referrer",
        telegram_name="Referrer",
        referral_code="REF1001",
        points=0,
    )
    invitee = User(
        telegram_id=1002,
        telegram_username="invitee",
        telegram_name="Invitee",
        referral_code="REF1002",
        points=0,
        referred_by_user_id=None,
    )
    session.add_all([provider, category, referrer, invitee])
    session.flush()
    invitee.referred_by_user_id = referrer.id
    offer = Offer(
        provider_id=provider.id,
        category_id=category.id,
        title="عرض تجريبي",
        price_iqd=10_000,
        service_fee_iqd=500,
        status=OfferStatus.ACTIVE.value,
        sold_today=0,
    )
    session.add(offer)
    session.flush()
    return provider, offer, referrer, invitee


async def service_checks() -> dict[str, int]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sync_session:
        provider, offer, referrer, invitee = build_fixture(sync_session)
        session = AsyncSessionAdapter(sync_session)
        wallets = WalletService()

        order = Order(
            public_id="CP-COUPON-1",
            user_id=invitee.id,
            provider_id=provider.id,
            offer_id=offer.id,
            status=OrderStatus.WAITING_PAYMENT.value,
            subtotal_iqd=10_000,
            service_fee_iqd=500,
            total_iqd=10_500,
            management_fee_iqd=500,
            provider_net_iqd=9_500,
            owner_net_iqd=1_000,
        )
        coupon = OrderCoupon(
            code="TARGET-FEE",
            coupon_type=OrderCouponType.FEE_WAIVER.value,
            provider_id=provider.id,
            target_user_id=invitee.id,
            value_int=0,
            max_uses=1,
            per_user_limit=1,
            used_count=0,
            is_active=True,
        )
        sync_session.add_all([order, coupon])
        sync_session.flush()
        applied, discount = await OrderCouponService(wallets).apply(
            session, order, invitee, "target-fee"
        )
        assert applied.id == coupon.id
        assert discount == 500
        assert order.service_fee_iqd == 0 and order.total_iqd == 10_000

        report_order = Order(
            public_id="CP-REPORT-1",
            user_id=invitee.id,
            provider_id=provider.id,
            offer_id=offer.id,
            status=OrderStatus.WAITING_PAYMENT.value,
            subtotal_iqd=10_000,
            service_fee_iqd=500,
            total_iqd=10_500,
            management_fee_iqd=500,
            provider_net_iqd=9_500,
            owner_net_iqd=1_000,
        )
        report_coupon = OrderCoupon(
            code="TARGET-REPORT",
            coupon_type=OrderCouponType.FREE_REPORT.value,
            provider_id=provider.id,
            target_user_id=invitee.id,
            value_int=0,
            max_uses=1,
            per_user_limit=1,
            used_count=0,
            is_active=True,
        )
        sync_session.add_all([report_order, report_coupon])
        sync_session.flush()
        await OrderCouponService(wallets).apply(
            session, report_order, invitee, "TARGET-REPORT"
        )
        benefits = int(
            sync_session.scalar(
                select(func.count(UserBenefit.id)).where(
                    UserBenefit.user_id == invitee.id,
                    UserBenefit.benefit_key == "free_report",
                )
            )
            or 0
        )
        assert benefits == 1

        first_order = Order(
            public_id="CP-REF-1",
            user_id=invitee.id,
            provider_id=provider.id,
            offer_id=offer.id,
            status=OrderStatus.PAID.value,
            subtotal_iqd=10_000,
            service_fee_iqd=500,
            total_iqd=10_500,
            management_fee_iqd=500,
            provider_net_iqd=9_500,
            owner_net_iqd=1_000,
        )
        sync_session.add(first_order)
        sync_session.flush()
        notifications = FakeNotificationService()
        finance = FinanceService(
            SimpleNamespace(
                feature_referrals=True,
                referral_invites_per_coupon=3,
            ),
            FakeOrderService(),
            FakeUserService(),
            OrderCouponService(wallets),
            notifications,
        )
        await finance.finalize_order(session, first_order)
        await finance.finalize_order(session, first_order)
        assert referrer.points == 0
        assert invitee.points == 5
        referral_entries = int(
            sync_session.scalar(
                select(func.count(WalletEntry.id)).where(
                    WalletEntry.entry_type == WalletEntryType.REFERRAL.value
                )
            )
            or 0
        )
        assert referral_entries == 0

        # A second purchase by the same invitee must not increment the referral counter.
        second_order = Order(
            public_id="CP-REF-2",
            user_id=invitee.id,
            provider_id=provider.id,
            offer_id=offer.id,
            status=OrderStatus.PAID.value,
            subtotal_iqd=10_000,
            service_fee_iqd=500,
            total_iqd=10_500,
            management_fee_iqd=500,
            provider_net_iqd=9_500,
            owner_net_iqd=1_000,
        )
        sync_session.add(second_order)
        sync_session.flush()
        await finance.finalize_order(session, second_order)

        # Two additional students complete their first subscription. The third
        # successful invite issues exactly one targeted, one-use fee-waiver code.
        for index in (3, 4):
            extra = User(
                telegram_id=1000 + index,
                telegram_username=f"invitee{index}",
                telegram_name=f"Invitee {index}",
                referral_code=f"REF100{index}",
                referred_by_user_id=referrer.id,
                points=0,
            )
            sync_session.add(extra)
            sync_session.flush()
            extra_order = Order(
                public_id=f"CP-REF-{index}",
                user_id=extra.id,
                provider_id=provider.id,
                offer_id=offer.id,
                status=OrderStatus.PAID.value,
                subtotal_iqd=10_000,
                service_fee_iqd=500,
                total_iqd=10_500,
                management_fee_iqd=500,
                provider_net_iqd=9_500,
                owner_net_iqd=1_000,
            )
            sync_session.add(extra_order)
            sync_session.flush()
            await finance.finalize_order(session, extra_order)

        referral_coupons = list(
            sync_session.scalars(
                select(OrderCoupon).where(
                    OrderCoupon.target_user_id == referrer.id,
                    OrderCoupon.coupon_type == OrderCouponType.FEE_WAIVER.value,
                    OrderCoupon.code.like("CPR-%"),
                )
            ).all()
        )
        assert len(referral_coupons) == 1
        assert referral_coupons[0].max_uses == 1
        assert referral_coupons[0].per_user_limit == 1
        assert len(notifications.messages) == 1

        proof_order = Order(
            public_id="CP-PROOF-1",
            user_id=invitee.id,
            provider_id=provider.id,
            offer_id=offer.id,
            status=OrderStatus.WAITING_PAYMENT.value,
            subtotal_iqd=10_000,
            service_fee_iqd=500,
            total_iqd=10_500,
            management_fee_iqd=500,
            provider_net_iqd=9_500,
            owner_net_iqd=1_000,
        )
        sync_session.add(proof_order)
        sync_session.flush()
        payments = PaymentService(
            SimpleNamespace(
                max_open_payment_reviews_per_user=5,
                payment_review_reservation_hours=24,
            ),
            FakeOrderService(),
            wallets,
        )
        proof = await payments.submit_proof(
            session,
            proof_order,
            "telegram-photo-file-id",
            None,
            "07700000000",
            10_500,
            None,
        )
        assert proof.status == "pending"
        assert proof_order.status == OrderStatus.PAYMENT_REVIEW.value
        assert sync_session.scalar(
            select(func.count(PaymentProof.id)).where(PaymentProof.order_id == proof_order.id)
        ) == 1

        return {
            "tables": len(Base.metadata.tables),
            "benefits": benefits,
            "referral_entries": referral_entries,
            "referral_coupons": len(referral_coupons),
        }


def source_markers() -> None:
    checks = {
        "app/bot/handlers/catalog.py": [
            "هل لديك كود خصم؟",
            "coupon:apply:",
            "coupon:skip:",
        ],
        "app/bot/handlers/provider_coupons.py": [
            "إسقاط رسوم البوت",
            "تقرير مجاني",
            "target_user_id=target.id",
        ],
        "app/services/finance.py": [
            "referral:success:",
            "referral:coupon:",
            "OrderCouponType.FEE_WAIVER.value",
            "completed_count == 1",
        ],
        "app/bot/handlers/payments.py": [
            "payment_review_keyboard(order.id)",
            "payment_proof_max_bytes",
        ],
        "app/services/payments.py": [
            "يوجد وصل قيد المراجعة",
            "existing_for_order",
        ],
        "app/bot/keyboards/inline.py": [
            "✅ موافقة وفتح الطلب",
            "❌ رفض الوصل مع سبب",
        ],
        "app/bot/handlers/menu.py": [
            "missing:reply:",
            "MSR-",
            "referral_link",
        ],
    }
    for relative, needles in checks.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        for needle in needles:
            assert needle in text, f"Missing {needle!r} in {relative}"


def main() -> None:
    source_markers()
    callbacks, longest = callback_audit()
    result = asyncio.run(service_checks())
    print(
        "V10.4 validation passed — "
        f"callbacks={callbacks}, longest_literal={longest}, "
        f"tables={result['tables']}, referral_entries={result['referral_entries']}"
    )


if __name__ == "__main__":
    main()
