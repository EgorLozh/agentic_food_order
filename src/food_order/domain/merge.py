from __future__ import annotations

from food_order.domain.models import (
    OrderItem,
    OrderState,
)


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


def order_total(state: OrderState) -> float:
    return sum(item.unit_price * item.qty for item in state.items)
