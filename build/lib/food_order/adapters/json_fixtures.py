from __future__ import annotations

import json
import time
from pathlib import Path

from food_order.adapters.base import DataAdapter, MenuSource, OrderSink
from food_order.domain.models import CreatedOrder, MenuItem, OrderState, PickupPoint


class JsonFixturesAdapter(DataAdapter):
    """Local JSON fixtures for development without Google Sheets."""

    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir
        self._orders: list[dict] = []
        self._order_counter = 1

    async def get_menu(self) -> list[MenuItem]:
        path = self.fixtures_dir / "menu.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return [MenuItem.model_validate(item) for item in data]

    async def get_pickup_points(self) -> list[PickupPoint]:
        path = self.fixtures_dir / "pickup_points.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return [PickupPoint.model_validate(item) for item in data if item.get("active", True)]

    async def create_order(
        self,
        *,
        telegram_user_id: int,
        state: OrderState,
        total: float,
    ) -> CreatedOrder:
        order_id = f"ORD-{self._order_counter:05d}"
        self._order_counter += 1
        payload = {
            "order_id": order_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "telegram_user_id": telegram_user_id,
            "items_json": [item.model_dump() for item in state.items],
            "point_id": state.pickup_point_id,
            "pickup_time": state.pickup_time,
            "payment": state.payment_method.value if state.payment_method else None,
            "total": total,
            "status": "new",
        }
        self._orders.append(payload)
        return CreatedOrder(order_id=order_id, total=total, payload=payload)
