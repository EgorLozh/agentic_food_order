from __future__ import annotations

from pathlib import Path
from typing import Protocol

from food_order.adapters.cafes_config import CafesConfigPickupSource
from food_order.adapters.postgres_cafes import PostgresCafesPickupSource
from food_order.domain.models import PickupPoint
from food_order.settings import Settings


class PickupSource(Protocol):
    async def get_pickup_points(self) -> list[PickupPoint]: ...


def parse_cafe_ids(raw: str | None) -> set[int] | None:
    if not raw or not raw.strip():
        return None
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        ids.add(int(part))
    return ids or None


def build_pickup_source(settings: Settings) -> PickupSource:
    if settings.database_url:
        return PostgresCafesPickupSource(
            settings.database_url,
            cafe_ids=parse_cafe_ids(settings.cafe_ids),
            cache_ttl_seconds=settings.menu_cache_ttl_seconds or settings.cache_ttl_seconds,
            cafes_config_path=settings.cafes_config_path,
        )
    return CafesConfigPickupSource(settings.cafes_config_path)


def build_pickup_source_from_path(
    path: Path,
    *,
    database_url: str | None = None,
    cafe_ids: str | None = None,
    cache_ttl_seconds: int = 900,
) -> PickupSource:
    if database_url:
        return PostgresCafesPickupSource(
            database_url,
            cafe_ids=parse_cafe_ids(cafe_ids),
            cache_ttl_seconds=cache_ttl_seconds,
            cafes_config_path=path,
        )
    return CafesConfigPickupSource(path)
