from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog

from food_order.domain.merge import merge_extracted_data, merge_resolved_items, order_total
from food_order.domain.models import OrderSchema, OrderState, OrderStatus, UserIntent
from food_order.llm.extractor import SlotExtractor
from food_order.llm.phraser import ResponsePhraser
from food_order.orchestration.actions import Action
from food_order.orchestration.planner import ActionPlanner
from food_order.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)


@dataclass
class TurnResult:
    reply_text: str
    state: OrderState
    action: Action


class OrderOrchestrator:
    def __init__(
        self,
        *,
        schema: OrderSchema,
        extractor: SlotExtractor,
        phraser: ResponsePhraser,
        tools: ToolRegistry,
    ) -> None:
        self.schema = schema
        self.extractor = extractor
        self.phraser = phraser
        self.tools = tools
        self.planner = ActionPlanner(schema)

    async def handle_message(
        self,
        *,
        telegram_user_id: int,
        text: str,
        state: OrderState,
    ) -> TurnResult:
        try:
            extract = await self.extractor.extract(text, state)
            logger.info(
                "extract",
                user_id=telegram_user_id,
                intent=extract.intent.value,
                data=extract.extracted_data.model_dump(mode="json"),
            )

            await self._apply_extract(state, extract)

            action = self.planner.next_action(
                state,
                intent=extract.intent,
                user_confirmed=extract.user_confirmed,
            )
            logger.info("action", user_id=telegram_user_id, action=action.value)

            payload = await self._build_payload(action, state, telegram_user_id)
            reply = await self.phraser.phrase(action, payload)
            return TurnResult(reply_text=reply, state=state, action=action)
        except Exception as exc:  # noqa: BLE001
            logger.exception("orchestrator_error", user_id=telegram_user_id, error=str(exc))
            return TurnResult(
                reply_text="Сейчас не получилось обработать запрос. Попробуйте ещё раз.",
                state=state,
                action=Action.ERROR,
            )

    async def _apply_extract(self, state: OrderState, extract) -> None:
        data = extract.extracted_data

        if data.items:
            raw_items = [(item.name, item.qty) for item in data.items]
            resolved, clarifications = await self.tools.resolve_extracted_items(raw_items)
            if clarifications:
                state.pending_clarifications = clarifications
            if resolved:
                merge_resolved_items(state, resolved)
                state.pending_clarifications = [
                    c for c in state.pending_clarifications if c.raw_name not in {i.name for i in resolved}
                ]

        merge_extracted_data(state, data)

        if data.pickup_point:
            point = await self.tools.resolve_point(data.pickup_point)
            if point:
                state.pickup_point_id = point.point_id
                state.pickup_point_name = point.name

    async def _build_payload(
        self,
        action: Action,
        state: OrderState,
        telegram_user_id: int,
    ) -> dict:
        if action == Action.CANCELLED:
            state.reset_for_new_order()
            return {"message": "Заказ отменён. Можете начать новый."}

        if action == Action.CLARIFY_ITEMS:
            pending = state.pending_clarifications[0]
            menu = await self.tools.get_menu()
            names = [item.name for item in menu if item.available]
            return {
                "unknown_item": pending.raw_name,
                "candidates": pending.candidates or names[:5],
            }

        if action == Action.ASK_ITEMS:
            menu = await self.tools.get_menu()
            return {"menu_preview": [item.name for item in menu[:8] if item.available]}

        if action == Action.ASK_PICKUP_POINT:
            points = await self.tools.get_pickup_points()
            return {"pickup_points": [p.name for p in points]}

        if action == Action.ASK_PICKUP_TIME:
            return {"hint": "Укажите время самовывоза, например 14:00"}

        if action == Action.ASK_PAYMENT_METHOD:
            return {"payment_methods": self.schema.payment_methods}

        if action in {Action.SHOW_SUMMARY, Action.CREATE_ORDER}:
            total = self.tools.calculate_order(state)
            summary = {
                "items": [
                    {"name": item.name, "qty": item.qty, "price": item.unit_price}
                    for item in state.items
                ],
                "pickup_point": state.pickup_point_name,
                "pickup_time": state.pickup_time,
                "payment_method": state.payment_method.value if state.payment_method else None,
                "total": total,
            }
            if action == Action.SHOW_SUMMARY:
                return {"summary": summary, "ask_confirm": True}

            if state.status == OrderStatus.CREATED and state.last_order_id:
                return {"summary": summary, "order_id": state.last_order_id, "already_created": True}

            if not state.idempotency_key:
                state.idempotency_key = str(uuid.uuid4())

            created = await self.tools.create_order(
                telegram_user_id=telegram_user_id,
                state=state,
            )
            state.status = OrderStatus.CREATED
            state.last_order_id = created.order_id
            return {"summary": summary, "order_id": created.order_id}

        if action == Action.ORDER_CREATED:
            return {"order_id": state.last_order_id}

        return {"user_text_hint": "Можете написать заказ свободным текстом."}
