from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from food_order.domain.models import PickupPoint


class CafeConfig(BaseModel):
    cafe_id: int
    cafe_name: str
    addr_of_cafe: str = ""
    formal_addr_of_cafe: str = ""
    city: str = ""
    aliases: list[str] = Field(default_factory=list)
    active: bool = True


class CafesFile(BaseModel):
    cafes: list[CafeConfig] = Field(default_factory=list)


def load_cafes(path: Path) -> list[CafeConfig]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return CafesFile.model_validate(data).cafes


def cafes_to_pickup_points(cafes: list[CafeConfig]) -> list[PickupPoint]:
    points: list[PickupPoint] = []
    for cafe in cafes:
        if not cafe.active:
            continue
        aliases = list(cafe.aliases)
        if cafe.city and cafe.city not in aliases:
            aliases.append(cafe.city)
        if cafe.addr_of_cafe and cafe.addr_of_cafe not in aliases:
            aliases.append(cafe.addr_of_cafe)
        points.append(
            PickupPoint(
                point_id=str(cafe.cafe_id),
                name=cafe.cafe_name,
                aliases=aliases,
                active=True,
                address=cafe.addr_of_cafe or None,
                formal_address=cafe.formal_addr_of_cafe or None,
                city=cafe.city or None,
            )
        )
    return points


class CafesConfigPickupSource:
    """Pickup points from local YAML (fallback when DATABASE_URL is unset)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._cache: list[PickupPoint] | None = None

    async def get_pickup_points(self) -> list[PickupPoint]:
        if self._cache is None:
            self._cache = cafes_to_pickup_points(load_cafes(self.path))
        return self._cache
