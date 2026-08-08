from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    DeliveryType,
    Offer,
    OfferWorkflow,
    Order,
    OrderStatus,
    OrderWorkflowState,
)

WORKFLOW_VERSION = 3


COMMON_TRANSITIONS: dict[str, list[str]] = {
    OrderStatus.DRAFT.value: [OrderStatus.WAITING_PAYMENT.value],
    OrderStatus.WAITING_PAYMENT.value: [
        OrderStatus.PAYMENT_REVIEW.value,
        OrderStatus.PAID.value,
        OrderStatus.CANCELLED.value,
    ],
    OrderStatus.PAYMENT_PROOF_RECEIVED.value: [OrderStatus.PAYMENT_REVIEW.value],
    OrderStatus.PAYMENT_REVIEW.value: [
        OrderStatus.PAID.value,
        OrderStatus.PAYMENT_REJECTED.value,
        OrderStatus.CANCELLED.value,
    ],
    OrderStatus.PAYMENT_REJECTED.value: [
        OrderStatus.PAYMENT_REVIEW.value,
        OrderStatus.PAID.value,
        OrderStatus.CANCELLED.value,
    ],
    OrderStatus.PAID.value: [
        OrderStatus.WAITING_FULFILLMENT.value,
        OrderStatus.EMAIL_RESERVED.value,
        OrderStatus.WAITING_CODE.value,
        OrderStatus.PROCESSING.value,
        OrderStatus.NEEDS_SUPPORT.value,
    ],
    OrderStatus.WAITING_FULFILLMENT.value: [
        OrderStatus.DELIVERED.value,
        OrderStatus.PROCESSING.value,
        OrderStatus.NEEDS_SUPPORT.value,
    ],
    OrderStatus.EMAIL_RESERVED.value: [
        OrderStatus.WAITING_CODE.value,
        OrderStatus.CODE_FOUND.value,
        OrderStatus.NEEDS_SUPPORT.value,
    ],
    OrderStatus.WAITING_CODE.value: [
        OrderStatus.CODE_FOUND.value,
        OrderStatus.DELIVERED.value,
        OrderStatus.NEEDS_SUPPORT.value,
    ],
    OrderStatus.CODE_FOUND.value: [
        OrderStatus.DELIVERED.value,
        OrderStatus.NEEDS_SUPPORT.value,
    ],
    OrderStatus.PROCESSING.value: [
        OrderStatus.DELIVERED.value,
        OrderStatus.NEEDS_SUPPORT.value,
        OrderStatus.CANCELLED.value,
    ],
    OrderStatus.DELIVERED.value: [
        OrderStatus.WAITING_CODE.value,
        OrderStatus.COMPLETED.value,
        OrderStatus.NEEDS_SUPPORT.value,
        OrderStatus.DISPUTED.value,
    ],
    OrderStatus.NEEDS_SUPPORT.value: [
        OrderStatus.WAITING_CODE.value,
        OrderStatus.PROCESSING.value,
        OrderStatus.DELIVERED.value,
        OrderStatus.COMPLETED.value,
        OrderStatus.DISPUTED.value,
        OrderStatus.REFUNDED.value,
        OrderStatus.CANCELLED.value,
    ],
    OrderStatus.DISPUTED.value: [
        OrderStatus.PROCESSING.value,
        OrderStatus.DELIVERED.value,
        OrderStatus.NEEDS_SUPPORT.value,
        OrderStatus.COMPLETED.value,
        OrderStatus.REFUNDED.value,
    ],
    OrderStatus.COMPLETED.value: [
        OrderStatus.DISPUTED.value,
        OrderStatus.REFUNDED.value,
    ],
    OrderStatus.CANCELLED.value: [],
    OrderStatus.REFUNDED.value: [],
}


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    key: str
    steps: list[dict[str, str]]
    transitions: dict[str, list[str]]


def workflow_for_delivery(delivery_type: str) -> WorkflowDefinition:
    common = [
        {"key": "payment", "status": OrderStatus.WAITING_PAYMENT.value, "label": "بانتظار الدفع"},
        {"key": "review", "status": OrderStatus.PAYMENT_REVIEW.value, "label": "قيد تدقيق الدفع"},
        {"key": "paid", "status": OrderStatus.PAID.value, "label": "تم تأكيد الدفع"},
    ]
    if delivery_type in {
        DeliveryType.INVENTORY_CODE.value,
        DeliveryType.INVENTORY_ACCOUNT.value,
    }:
        key = "inventory_delivery"
        tail = [
            {
                "key": "fulfillment",
                "status": OrderStatus.WAITING_FULFILLMENT.value,
                "label": "جاري التجهيز",
            },
            {"key": "delivered", "status": OrderStatus.DELIVERED.value, "label": "تم التسليم"},
            {"key": "complete", "status": OrderStatus.COMPLETED.value, "label": "مكتمل"},
        ]
    elif delivery_type == DeliveryType.EMAIL_CODE.value:
        key = "email_code"
        tail = [
            {
                "key": "email_reserved",
                "status": OrderStatus.EMAIL_RESERVED.value,
                "label": "تم حجز البريد",
            },
            {
                "key": "waiting_code",
                "status": OrderStatus.WAITING_CODE.value,
                "label": "بانتظار الرمز",
            },
            {"key": "delivered", "status": OrderStatus.DELIVERED.value, "label": "تم تسليم الرمز"},
            {"key": "complete", "status": OrderStatus.COMPLETED.value, "label": "مكتمل"},
        ]
    else:
        key = "manual_delivery"
        tail = [
            {"key": "processing", "status": OrderStatus.PROCESSING.value, "label": "قيد التنفيذ"},
            {"key": "delivered", "status": OrderStatus.DELIVERED.value, "label": "تم التسليم"},
            {"key": "complete", "status": OrderStatus.COMPLETED.value, "label": "مكتمل"},
        ]
    return WorkflowDefinition(key=key, steps=common + tail, transitions=COMMON_TRANSITIONS)


class WorkflowService:
    async def ensure_offer(self, session: AsyncSession, offer: Offer) -> OfferWorkflow:
        row = await session.scalar(select(OfferWorkflow).where(OfferWorkflow.offer_id == offer.id))
        definition = workflow_for_delivery(offer.delivery_type)
        if not row:
            row = OfferWorkflow(
                offer_id=offer.id,
                workflow_key=definition.key,
                version=WORKFLOW_VERSION,
                steps=definition.steps,
                allowed_transitions=definition.transitions,
            )
            session.add(row)
        elif row.version < WORKFLOW_VERSION or row.workflow_key != definition.key:
            # Built-in workflows are versioned. Updating the application refreshes
            # stale definitions without rewriting orders or deleting history.
            row.workflow_key = definition.key
            row.version = WORKFLOW_VERSION
            row.steps = definition.steps
            row.allowed_transitions = definition.transitions
        await session.flush()
        return row

    async def ensure_order(self, session: AsyncSession, order: Order) -> OrderWorkflowState:
        state = await session.scalar(
            select(OrderWorkflowState).where(OrderWorkflowState.order_id == order.id)
        )
        offer = await session.get(Offer, order.offer_id)
        if state:
            if offer:
                workflow = await self.ensure_offer(session, offer)
                if (
                    state.workflow_version != workflow.version
                    or state.workflow_key != workflow.workflow_key
                    or state.current_status != order.status
                ):
                    state.workflow_key = workflow.workflow_key
                    state.workflow_version = workflow.version
                    state.current_status = order.status
                    state.current_step_key = self.step_key(workflow.steps, order.status)
                    await session.flush()
            return state
        if not offer:
            raise ValueError("العرض المرتبط بالطلب غير موجود")
        workflow = await self.ensure_offer(session, offer)
        state = OrderWorkflowState(
            order_id=order.id,
            workflow_key=workflow.workflow_key,
            workflow_version=workflow.version,
            current_status=order.status,
            current_step_key=self.step_key(workflow.steps, order.status),
        )
        session.add(state)
        await session.flush()
        return state

    @staticmethod
    def step_key(steps: list[dict[str, str]], status: str) -> str:
        for step in steps:
            if step.get("status") == status:
                return step.get("key", "")
        return "exception"

    async def assert_transition(
        self,
        session: AsyncSession,
        order: Order,
        new_status: str,
        *,
        force: bool = False,
    ) -> None:
        if force or order.status == new_status:
            return
        offer = await session.get(Offer, order.offer_id)
        workflow = await self.ensure_offer(session, offer) if offer else None
        transitions = workflow.allowed_transitions if workflow else COMMON_TRANSITIONS
        allowed = transitions.get(order.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"انتقال حالة غير مسموح: {order.status} ← {new_status}. "
                "يجب اتباع خطوات الطلب بالترتيب."
            )

    async def record_transition(
        self,
        session: AsyncSession,
        order: Order,
        new_status: str,
    ) -> None:
        state = await self.ensure_order(session, order)
        offer = await session.get(Offer, order.offer_id)
        workflow = await self.ensure_offer(session, offer) if offer else None
        state.current_status = new_status
        state.current_step_key = self.step_key(workflow.steps, new_status) if workflow else ""
        await session.flush()

    async def timeline(self, session: AsyncSession, order: Order) -> list[dict[str, str | bool]]:
        offer = await session.get(Offer, order.offer_id)
        workflow = await self.ensure_offer(session, offer) if offer else None
        if not workflow:
            return []
        statuses = [step.get("status", "") for step in workflow.steps]
        current_index = statuses.index(order.status) if order.status in statuses else -1
        result: list[dict[str, str | bool]] = []
        for index, step in enumerate(workflow.steps):
            result.append(
                {
                    "key": step.get("key", ""),
                    "status": step.get("status", ""),
                    "label": step.get("label", step.get("status", "")),
                    "done": current_index >= 0 and index <= current_index,
                    "current": index == current_index,
                }
            )
        return result
