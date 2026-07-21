from __future__ import annotations

from food_order.adapters.base import DataAdapter
from food_order.adapters.json_fixtures import JsonFixturesAdapter
from food_order.adapters.pickup import PickupSource, build_pickup_source
from food_order.adapters.sheets.client import FeedMerSheetsAdapter
from food_order.settings import Settings


def build_data_adapter(
    settings: Settings,
    *,
    pickup_source: PickupSource | None = None,
) -> DataAdapter:
    pickup = pickup_source or build_pickup_source(settings)
    if settings.has_sheets_credentials():
        return FeedMerSheetsAdapter(
            spreadsheet_id=settings.spreadsheet_id or "",
            api_sheets_google_key=settings.api_sheets_google_key,
            google_service_account_json=settings.google_service_account_json,
            pickup_source=pickup,
            menu_aliases_path=settings.menu_aliases_path,
            cache_ttl_seconds=settings.menu_cache_ttl_seconds or settings.cache_ttl_seconds,
            cafe_id=settings.cafe_id,
            ss_pricelist_id=settings.ss_pricelist_id,
            pos_sync_enabled=settings.pos_sync_enabled,
        )
    return JsonFixturesAdapter(
        fixtures_dir=settings.fixtures_dir,
        pickup_source=pickup,
        menu_aliases_path=settings.menu_aliases_path,
    )
