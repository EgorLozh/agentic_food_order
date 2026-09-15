from __future__ import annotations

import json
import time
from pathlib import Path

from food_order.adapters.base import DataAdapter
from food_order.adapters.cafes_config import CafesConfigPickupSource
from food_order.adapters.menu_aliases import apply_menu_aliases, load_menu_aliases
from food_order.adapters.pickup import PickupSource
from food_order.adapters.sheets.general_catalog import parse_general_catalog
from food_order.adapters.sheets.pos_pricelist import enrich_with_pos_prices, parse_pos_rows
from food_order.domain.models import CreatedOrder, MenuItem, OrderState, PickupPoint


class JsonFixturesAdapter(DataAdapter):
    """Local fixtures mirroring FeedMer «Общий справочник» + cafes.yaml."""

    def __init__(
        self,
        fixtures_dir: Path,
        cafes_config_path: Path | None = None,
        menu_aliases_path: Path | None = None,
        *,
        pickup_source: PickupSource | None = None,
        pos_sync_enabled: bool = False,
    ) -> None:
        self.fixtures_dir = fixtures_dir
        self.cafes_config_path = cafes_config_path or Path("config/cafes.yaml")
        self.menu_aliases_path = menu_aliases_path or Path("config/menu_aliases.yaml")
        self.pos_sync_enabled = pos_sync_enabled
        self._pickup = pickup_source or CafesConfigPickupSource(self.cafes_config_path)
        self._orders: list[dict] = []
        self._order_counter = 1
        self._menu_cache: list[MenuItem] | None = None

    def _load_catalog_rows(self) -> list[list[str]]:
        path = self.fixtures_dir / "general_catalog_rows.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        # Legacy fallback
        legacy = self.fixtures_dir / "menu.json"
        if legacy.exists():
            items = json.loads(legacy.read_text(encoding="utf-8"))
            rows = [["Наименование", "Описание", "Вес", "Цена"]]
            for item in items:
                rows.append(
                    [
                        item["name"],
                        item.get("description", ""),
                        item.get("weight", ""),
                        str(int(item["price"])),
                    ]
                )
            return rows
        return []

    def _build_menu(self) -> list[MenuItem]:
        rows = self._load_catalog_rows()
        parsed = parse_general_catalog(rows)
        items = parsed.items

        if self.pos_sync_enabled and parsed.internal_system:
            pos_path = self.fixtures_dir / "pos_rkeeper_rows.json"
            if parsed.internal_system == "headline":
                pos_path = self.fixtures_dir / "pos_headline_rows.json"
            if pos_path.exists():
                pos_rows = json.loads(pos_path.read_text(encoding="utf-8"))
                lookup = parse_pos_rows(pos_rows, internal_system=parsed.internal_system)
                items = enrich_with_pos_prices(items, lookup)

        return apply_menu_aliases(items, load_menu_aliases(self.menu_aliases_path))

    async def get_menu(self) -> list[MenuItem]:
        if self._menu_cache is None:
            self._menu_cache = self._build_menu()
        return self._menu_cache

    async def get_pickup_points(self) -> list[PickupPoint]:
        return await self._pickup.get_pickup_points()

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
            "cafe_id": state.pickup_point_id,
            "items_json": [item.model_dump() for item in state.items],
            "pickup_time": state.pickup_time,
            "payment": state.payment_method.value if state.payment_method else None,
            "phone": state.phone,
            "total": total,
            "status": "new",
        }
        self._orders.append(payload)
        return CreatedOrder(order_id=order_id, total=total, payload=payload)
