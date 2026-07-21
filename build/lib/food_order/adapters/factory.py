from __future__ import annotations

from pathlib import Path

from food_order.adapters.base import DataAdapter
from food_order.adapters.json_fixtures import JsonFixturesAdapter
from food_order.adapters.sheets.client import CachedSheetsAdapter
from food_order.settings import Settings


def build_data_adapter(settings: Settings) -> DataAdapter:
    if settings.spreadsheet_id and settings.google_service_account_json:
        return CachedSheetsAdapter(
            spreadsheet_id=settings.spreadsheet_id,
            service_account_path=Path(settings.google_service_account_json),
            cache_ttl_seconds=settings.cache_ttl_seconds,
        )
    return JsonFixturesAdapter(settings.fixtures_dir)
