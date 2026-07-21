from __future__ import annotations

from food_order.domain.models import OrderSchema, OrderState, OrderStatus, UserIntent
from food_order.orchestration.actions import Action


class ActionPlanner:
    def __init__(self, schema: OrderSchema) -> None:
        self.schema = schema

    def next_action(
        self,
        state: OrderState,
        *,
        intent: UserIntent,
        user_confirmed: bool | None,
    ) -> Action:
        if intent == UserIntent.CANCEL:
            return Action.CANCELLED

        if state.status == OrderStatus.CREATED and intent in {
            UserIntent.CREATE_ORDER,
            UserIntent.UPDATE_ORDER,
        }:
            state.reset_for_new_order()

        if state.pending_clarifications:
            return Action.CLARIFY_ITEMS

        if not state.items:
            return Action.ASK_ITEMS

        if "pickup_point_id" in self.schema.required_fields and not state.pickup_point_id:
            return Action.ASK_PICKUP_POINT

        if "pickup_time" in self.schema.required_fields and not state.pickup_time:
            return Action.ASK_PICKUP_TIME

        if "payment_method" in self.schema.required_fields and not state.payment_method:
            return Action.ASK_PAYMENT_METHOD

        if state.status == OrderStatus.AWAITING_CONFIRMATION:
            if intent == UserIntent.CONFIRM or user_confirmed is True:
                return Action.CREATE_ORDER
            if intent == UserIntent.UPDATE_ORDER:
                state.status = OrderStatus.COLLECTING
                return self.next_action(state, intent=intent, user_confirmed=user_confirmed)
            return Action.SHOW_SUMMARY

        state.status = OrderStatus.AWAITING_CONFIRMATION
        return Action.SHOW_SUMMARY
