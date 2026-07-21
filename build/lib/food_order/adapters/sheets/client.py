from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from food_order.adapters.base import DataAdapter
from food_order.domain.models import CreatedOrder, MenuItem, OrderState, PickupPoint

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class CachedSheetsAdapter(DataAdapter):
    SHEET_MENU = "Menu"
    SHEET_POINTS = "PickupPoints"
    SHEET_ORDERS = "Orders"

    def __init__(
        self,
        spreadsheet_id: str,
        service_account_path: Path,
        cache_ttl_seconds: int = 300,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.service_account_path = service_account_path
        self.cache_ttl_seconds = cache_ttl_seconds
        self._menu_cache: tuple[float, list[MenuItem]] | None = None
        self._points_cache: tuple[float, list[PickupPoint]] | None = None
        self._client: gspread.Client | None = None

    def _get_client(self) -> gspread.Client:
        if self._client is None:
            creds = Credentials.from_service_account_file(
                str(self.service_account_path),
                scopes=SCOPES,
            )
            self._client = gspread.authorize(creds)
        return self._client

    def _spreadsheet(self):
        return self._get_client().open_by_key(self.spreadsheet_id)

    def _is_fresh(self, cached_at: float) -> bool:
        return (time.time() - cached_at) < self.cache_ttl_seconds

    @staticmethod
    def _split_aliases(value: str | None) -> list[str]:
        if not value:
            return []
        return [part.strip() for part in value.split(",") if part.strip()]

    async def get_menu(self) -> list[MenuItem]:
        if self._menu_cache and self._is_fresh(self._menu_cache[0]):
            return self._menu_cache[1]

        sheet = self._spreadsheet().worksheet(self.SHEET_MENU)
        rows = sheet.get_all_records()
        menu = [
            MenuItem(
                sku_id=str(row["sku_id"]),
                category=str(row.get("category", "")),
                name=str(row["name"]),
                aliases=self._split_aliases(row.get("aliases")),
                price=float(row["price"]),
                available=str(row.get("available", "TRUE")).upper() in {"TRUE", "1", "YES"},
            )
            for row in rows
        ]
        self._menu_cache = (time.time(), menu)
        return menu

    async def get_pickup_points(self) -> list[PickupPoint]:
        if self._points_cache and self._is_fresh(self._points_cache[0]):
            return self._points_cache[1]

        sheet = self._spreadsheet().worksheet(self.SHEET_POINTS)
        rows = sheet.get_all_records()
        points = [
            PickupPoint(
                point_id=str(row["point_id"]),
                name=str(row["name"]),
                aliases=self._split_aliases(row.get("aliases")),
                active=str(row.get("active", "TRUE")).upper() in {"TRUE", "1", "YES"},
            )
            for row in rows
        ]
        active = [p for p in points if p.active]
        self._points_cache = (time.time(), active)
        return active

    async def create_order(
        self,
        *,
        telegram_user_id: int,
        state: OrderState,
        total: float,
    ) -> CreatedOrder:
        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        payload = {
            "order_id": order_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "telegram_user_id": telegram_user_id,
            "items_json": json.dumps([item.model_dump() for item in state.items], ensure_ascii=False),
            "point_id": state.pickup_point_id or "",
            "pickup_time": state.pickup_time or "",
            "payment": state.payment_method.value if state.payment_method else "",
            "total": total,
            "status": "new",
        }
        sheet = self._spreadsheet().worksheet(self.SHEET_ORDERS)
        sheet.append_row(list(payload.values()), value_input_option="USER_ENTERED")
        return CreatedOrder(order_id=order_id, total=total, payload=payload)
