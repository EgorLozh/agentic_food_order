from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol

import structlog

from food_order.adapters.cafes_config import load_cafes
from food_order.domain.models import PickupPoint

logger = structlog.get_logger(__name__)

# Columns present in FeedMer/testing `cafes` (no addr/city/region in this schema).
CAFES_QUERY = """
SELECT "cafeId", "cafeName"
FROM cafes
ORDER BY "cafeId"
"""


class CafeRow(Protocol):
    def __getitem__(self, key: str) -> Any: ...


def _strip_city_prefix(address: str, city: str) -> str:
    addr = address.strip()
    if not city:
        return addr
    prefix = f"{city} "
    if addr.startswith(prefix):
        return addr[len(prefix) :].strip()
    return addr


def _build_aliases(
    *,
    name: str,
    address: str,
    display_address: str,
    city: str,
    extra: list[str] | None = None,
) -> list[str]:
    aliases: list[str] = []
    for value in (name, address, display_address, city, *(extra or [])):
        cleaned = (value or "").strip()
        if cleaned and cleaned not in aliases:
            aliases.append(cleaned)
    return aliases


def cafe_row_to_pickup_point(row: dict[str, Any]) -> PickupPoint:
    cafe_id = row.get("cafeId")
    name = str(row.get("cafeName") or "").strip()
    # Optional fields if present in some environments / yaml merge
    address_raw = str(row.get("addrOfCafe") or "").strip()
    formal_raw = str(row.get("formalAddrOfCafe") or "").strip()
    city = str(row.get("city") or "").strip()
    extra_aliases = [str(a) for a in (row.get("aliases") or []) if a]

    display_address = _strip_city_prefix(address_raw, city) if address_raw else ""
    if formal_raw:
        formal = formal_raw
    elif address_raw:
        formal = f"{city} {address_raw}".strip() if city else address_raw
    else:
        formal = ""

    return PickupPoint(
        point_id=str(cafe_id),
        name=name or str(cafe_id),
        aliases=_build_aliases(
            name=name,
            address=address_raw,
            display_address=display_address,
            city=city,
            extra=extra_aliases,
        ),
        active=True,
        address=display_address or address_raw or None,
        formal_address=formal or None,
        city=city or None,
    )


def _merge_yaml_overlay(row: dict[str, Any], overlay: dict[str, Any] | None) -> dict[str, Any]:
    if not overlay:
        return row
    merged = dict(row)
    for key in ("addrOfCafe", "formalAddrOfCafe", "city", "aliases"):
        if key in overlay and overlay[key]:
            merged[key] = overlay[key]
    return merged


def rows_to_pickup_points(
    rows: list[dict[str, Any]],
    *,
    cafe_ids: set[int] | None = None,
    yaml_by_id: dict[int, dict[str, Any]] | None = None,
) -> list[PickupPoint]:
    points: list[PickupPoint] = []
    for row in rows:
        cafe_id = row.get("cafeId")
        if cafe_ids is not None and cafe_id is not None:
            try:
                if int(cafe_id) not in cafe_ids:
                    continue
            except (TypeError, ValueError):
                continue
        if not row.get("cafeName") and cafe_id is None:
            continue
        overlay = None
        if yaml_by_id is not None and cafe_id is not None:
            try:
                overlay = yaml_by_id.get(int(cafe_id))
            except (TypeError, ValueError):
                overlay = None
        points.append(cafe_row_to_pickup_point(_merge_yaml_overlay(row, overlay)))
    return points


def load_yaml_overlay(path: Path | None) -> dict[int, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    overlay: dict[int, dict[str, Any]] = {}
    for cafe in load_cafes(path):
        overlay[cafe.cafe_id] = {
            "addrOfCafe": cafe.addr_of_cafe,
            "formalAddrOfCafe": cafe.formal_addr_of_cafe,
            "city": cafe.city,
            "aliases": cafe.aliases,
        }
    return overlay


class PostgresCafesPickupSource:
    """Pickup points from FeedMer PostgreSQL `cafes` table."""

    def __init__(
        self,
        database_url: str,
        *,
        cafe_ids: set[int] | None = None,
        cache_ttl_seconds: int = 900,
        cafes_config_path: Path | None = None,
    ) -> None:
        self.database_url = database_url
        self.cafe_ids = cafe_ids
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cafes_config_path = cafes_config_path
        self._pool = None
        self._cache: tuple[float, list[PickupPoint]] | None = None

    async def _get_pool(self):
        if self._pool is None:
            import asyncpg

            self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=4)
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def get_pickup_points(self) -> list[PickupPoint]:
        now = time.time()
        if self._cache is not None and (now - self._cache[0]) < self.cache_ttl_seconds:
            return self._cache[1]

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            records = await conn.fetch(CAFES_QUERY)
        rows = [dict(record) for record in records]
        yaml_by_id = load_yaml_overlay(self.cafes_config_path)
        points = rows_to_pickup_points(
            rows,
            cafe_ids=self.cafe_ids,
            yaml_by_id=yaml_by_id or None,
        )
        self._cache = (now, points)
        logger.info("cafes_loaded", count=len(points), source="postgres")
        return points
