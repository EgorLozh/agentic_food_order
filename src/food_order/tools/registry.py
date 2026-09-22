from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from food_order.adapters.base import MenuSource, OrderSink
from food_order.domain.merge import order_total
from food_order.domain.models import CreatedOrder, MenuItem, OrderState, PickupPoint
from food_order.tools.menu import MenuMatcher, resolve_items_from_names, resolve_pickup_point


@dataclass
class ToolRegistry:
    menu_source: MenuSource
    order_sink: OrderSink
    last_error: str | None = field(default=None, init=False)

    async def get_menu(self) -> list[MenuItem]:
        try:
            return await self.menu_source.get_menu()
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            raise

    async def get_pickup_points(self) -> list[PickupPoint]:
        try:
            return await self.menu_source.get_pickup_points()
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            raise

    async def check_item_availability(
        self,
        raw_items: list[tuple[str, int]],
    ) -> dict[str, Any]:
        menu = await self.get_menu()
        matcher = MenuMatcher(menu)
        unknown: list[str] = []
        ambiguous: dict[str, list[str]] = {}
        resolved_count = 0

        for name, qty in raw_items:
            item, candidates = matcher.resolve_item(name, qty)
            if item:
                resolved_count += 1
            elif candidates:
                ambiguous[name] = candidates
            else:
                unknown.append(name)

        return {
            "resolved_count": resolved_count,
            "unknown": unknown,
            "ambiguous": ambiguous,
        }

    async def resolve_extracted_items(
        self,
        raw_items: list[tuple[str, int]],
    ) -> tuple[list, list]:
        return await resolve_items_from_names(self.menu_source, raw_items)

    async def resolve_point(
        self, query: str | None
    ) -> tuple[PickupPoint | None, list[PickupPoint]]:
        points = await self.get_pickup_points()
        return resolve_pickup_point(query, points)

    def calculate_order(self, state: OrderState) -> float:
        return order_total(state)

    async def create_order(
        self,
        *,
        telegram_user_id: int,
        state: OrderState,
    ) -> CreatedOrder:
        total = self.calculate_order(state)
        try:
            return await self.order_sink.create_order(
                telegram_user_id=telegram_user_id,
                state=state,
                total=total,
            )
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            raise
