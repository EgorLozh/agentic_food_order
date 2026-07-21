from __future__ import annotations

from food_order.domain.models import (
    ExtractedData,
    OrderItem,
    OrderState,
    PaymentMethod,
)


def merge_extracted_data(state: OrderState, data: ExtractedData) -> OrderState:
    if data.pickup_point is not None:
        state.pickup_point_id = None
        state.pickup_point_name = data.pickup_point.strip()

    if data.pickup_time is not None:
        state.pickup_time = data.pickup_time.strip()

    if data.payment_method is not None:
        state.payment_method = data.payment_method

    return state


def merge_resolved_items(
    state: OrderState,
    resolved: list[OrderItem],
    *,
    replace: bool = False,
) -> OrderState:
    if replace:
        state.items = resolved
        return state

    by_sku = {item.sku_id: item for item in state.items}
    for item in resolved:
        if item.sku_id in by_sku:
            by_sku[item.sku_id].qty += item.qty
        else:
            by_sku[item.sku_id] = item.model_copy()
    state.items = list(by_sku.values())
    return state


def normalize_payment(value: str | None) -> PaymentMethod | None:
    if not value:
        return None
    lowered = value.lower()
    if any(word in lowered for word in ("налич", "cash", "нал")):
        return PaymentMethod.CASH
    if any(word in lowered for word in ("карт", "card", "безнал")):
        return PaymentMethod.CARD
    return None


def order_total(state: OrderState) -> float:
    return sum(item.unit_price * item.qty for item in state.items)
