from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from food_order.adapters.sheets.general_catalog import parse_price
from food_order.domain.models import MenuItem

InternalSystem = Literal["rkeeper", "headline"]


@dataclass(frozen=True)
class PosPriceRow:
    match_name: str
    ident: str
    price: int


def sheet_title_for_pos(internal_system: InternalSystem, cafe_id: int) -> str:
    if internal_system == "rkeeper":
        return f"RKeeper прайс-лист {cafe_id} кафе"
    return f"Headline прайс-лист {cafe_id} кафе"


def _cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    value = row[index]
    return "" if value is None else str(value)


def parse_pos_rows(
    rows: list[list[str]],
    *,
    internal_system: InternalSystem,
) -> dict[str, PosPriceRow]:
    """
    Build lookup by Match name.
    RKeeper: match on col 0, Ident typically nearby; FeedMer uses Ident + Price fields.
    We accept: [0]=name, Ident in col with header or fallback col 1, Price in later col.

    Per FeedMer docs for matching:
    - RKeeper: name === row._rawData[0].trim(), take Ident + Price
    - Headline: name === row._rawData[1].trim()

    For raw values without dict access we use:
    - RKeeper: name=col0, ident=col1 (or Ident column), price=last numeric / known Price col
    - Headline: name=col1, ident=col0 or Ident, price=Price
    """
    if not rows:
        return {}

    header = [str(h).strip() for h in rows[0]]
    ident_idx = _find_col(header, ("Ident", "ident", "ID", "Id"))
    price_idx = _find_col(header, ("Price", "price", "Цена", "цена"))

    # FeedMer-style defaults when headers missing
    if ident_idx is None:
        ident_idx = 1 if internal_system == "rkeeper" else 0
    if price_idx is None:
        price_idx = 2

    lookup: dict[str, PosPriceRow] = {}
    for row in rows[1:]:
        if internal_system == "rkeeper":
            match_name = _cell(row, 0).strip()
        else:
            match_name = _cell(row, 1).strip()
        if not match_name:
            continue
        ident = _cell(row, ident_idx).strip()
        price = parse_price(_cell(row, price_idx))
        if not ident and price <= 0:
            continue
        lookup[match_name] = PosPriceRow(
            match_name=match_name,
            ident=ident or match_name,
            price=price,
        )
    return lookup


def _find_col(header: list[str], names: tuple[str, ...]) -> int | None:
    for idx, col in enumerate(header):
        if col in names:
            return idx
    return None


def enrich_with_pos_prices(
    items: list[MenuItem],
    pos_lookup: dict[str, PosPriceRow],
) -> list[MenuItem]:
    enriched: list[MenuItem] = []
    for item in items:
        key = (item.internal_name or "").strip()
        if not key or key not in pos_lookup:
            enriched.append(item)
            continue
        pos = pos_lookup[key]
        enriched.append(
            item.model_copy(
                update={
                    "internal_id": pos.ident,
                    "sku_id": pos.ident or item.sku_id,
                    "price": float(pos.price) if pos.price > 0 else item.price,
                }
            )
        )
    return enriched
