from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

import gspread

from food_order.adapters.base import DataAdapter
from food_order.adapters.cafes_config import CafesConfigPickupSource
from food_order.adapters.menu_aliases import apply_menu_aliases, load_menu_aliases
from food_order.adapters.pickup import PickupSource
from food_order.adapters.sheets.credentials import build_credentials
from food_order.adapters.sheets.general_catalog import SHEET_TITLE, parse_general_catalog
from food_order.adapters.sheets.pos_pricelist import (
    enrich_with_pos_prices,
    parse_pos_rows,
    sheet_title_for_pos,
)
from food_order.domain.models import CreatedOrder, MenuItem, OrderState, PickupPoint

logger = logging.getLogger(__name__)

MIN_ITEMS_TO_ACCEPT = 10
MIN_ITEMS_SOFT = 20
ORDERS_SHEET = "Orders"


class FeedMerSheetsAdapter(DataAdapter):
    """
    FeedMer-compatible Sheets adapter:
    - Menu from «Общий справочник»
    - Pickup points from injected source (Postgres or cafes.yaml)
    - Optional POS price sync
    - create_order kept for DataAdapter compatibility (unused in production)
    """

    def __init__(
        self,
        *,
        spreadsheet_id: str,
        api_sheets_google_key: str | None,
        google_service_account_json: str | None,
        pickup_source: PickupSource | None = None,
        cafes_config_path: Path | None = None,
        menu_aliases_path: Path | None = None,
        cache_ttl_seconds: int = 900,
        cafe_id: int | None = None,
        ss_pricelist_id: str | None = None,
        pos_sync_enabled: bool = False,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.api_sheets_google_key = api_sheets_google_key
        self.google_service_account_json = google_service_account_json
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cafe_id = cafe_id
        self.ss_pricelist_id = ss_pricelist_id
        self.pos_sync_enabled = pos_sync_enabled
        self.menu_aliases_path = menu_aliases_path or Path("config/menu_aliases.yaml")
        if pickup_source is not None:
            self._pickup = pickup_source
        else:
            self._pickup = CafesConfigPickupSource(
                cafes_config_path or Path("config/cafes.yaml")
            )
        self._client: gspread.Client | None = None
        self._menu_cache: tuple[float, list[MenuItem]] | None = None

    def _get_client(self) -> gspread.Client:
        if self._client is None:
            creds = build_credentials(
                api_sheets_google_key=self.api_sheets_google_key,
                google_service_account_json=self.google_service_account_json,
            )
            self._client = gspread.authorize(creds)
        return self._client

    def _spreadsheet(self, spreadsheet_id: str | None = None):
        return self._get_client().open_by_key(spreadsheet_id or self.spreadsheet_id)

    def _is_fresh(self, cached_at: float) -> bool:
        return (time.time() - cached_at) < self.cache_ttl_seconds

    def _fetch_menu_from_sheets(self) -> list[MenuItem]:
        sheet = self._spreadsheet().worksheet(SHEET_TITLE)
        rows = sheet.get_all_values()
        parsed = parse_general_catalog(rows)
        items = parsed.items

        if (
            self.pos_sync_enabled
            and self.ss_pricelist_id
            and self.cafe_id is not None
            and parsed.internal_system
        ):
            try:
                title = sheet_title_for_pos(parsed.internal_system, self.cafe_id)
                pos_sheet = self._spreadsheet(self.ss_pricelist_id).worksheet(title)
                pos_rows = pos_sheet.get_all_values()
                lookup = parse_pos_rows(pos_rows, internal_system=parsed.internal_system)
                items = enrich_with_pos_prices(items, lookup)
            except Exception:  # noqa: BLE001
                logger.exception("pos_sync_failed; using catalog prices")

        return apply_menu_aliases(items, load_menu_aliases(self.menu_aliases_path))

    def _apply_cache_guards(
        self,
        new_items: list[MenuItem],
    ) -> list[MenuItem] | None:
        count = len(new_items)
        if count < MIN_ITEMS_TO_ACCEPT:
            logger.warning(
                "menu_refresh_rejected_too_few items=%s min=%s",
                count,
                MIN_ITEMS_TO_ACCEPT,
            )
            return None

        if count < MIN_ITEMS_SOFT and self._menu_cache is not None:
            logger.warning(
                "menu_refresh_rolled_back items=%s soft_min=%s",
                count,
                MIN_ITEMS_SOFT,
            )
            return None

        return new_items

    async def get_menu(self) -> list[MenuItem]:
        if self._menu_cache and self._is_fresh(self._menu_cache[0]):
            return self._menu_cache[1]

        try:
            fetched = self._fetch_menu_from_sheets()
        except Exception:  # noqa: BLE001
            logger.exception("menu_fetch_failed")
            if self._menu_cache:
                return self._menu_cache[1]
            raise

        accepted = self._apply_cache_guards(fetched)
        if accepted is None:
            if self._menu_cache:
                return self._menu_cache[1]
            # First load: accept even if below guards so local/dev isn't blocked
            accepted = fetched

        self._menu_cache = (time.time(), accepted)
        return accepted

    async def get_pickup_points(self) -> list[PickupPoint]:
        return await self._pickup.get_pickup_points()

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
            "cafe_id": state.pickup_point_id or "",
            "items_json": json.dumps(
                [item.model_dump() for item in state.items], ensure_ascii=False
            ),
            "pickup_time": state.pickup_time or "",
            "payment": state.payment_method.value if state.payment_method else "",
            "phone": state.phone or "",
            "total": total,
            "status": "new",
        }
        sheet = self._spreadsheet().worksheet(ORDERS_SHEET)
        sheet.append_row(
            [
                payload["order_id"],
                payload["created_at"],
                payload["telegram_user_id"],
                payload["cafe_id"],
                payload["items_json"],
                payload["pickup_time"],
                payload["payment"],
                payload["total"],
                payload["status"],
                payload["phone"],
            ],
            value_input_option="USER_ENTERED",
        )
        return CreatedOrder(order_id=order_id, total=total, payload=payload)


# Backwards-compatible alias
CachedSheetsAdapter = FeedMerSheetsAdapter
