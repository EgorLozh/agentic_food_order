from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from food_order.domain.models import MenuItem

SHEET_TITLE = "Общий справочник"
InternalSystem = Literal["rkeeper", "headline"]


@dataclass(frozen=True)
class CatalogParseResult:
    items: list[MenuItem]
    internal_system: InternalSystem | None


def _cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    value = row[index]
    return "" if value is None else str(value)


def _slug(name: str) -> str:
    text = unicodedata.normalize("NFKD", name.lower())
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text or "item"


def detect_internal_system(header_row: list[str]) -> InternalSystem | None:
    headers = [str(h).strip() for h in header_row]
    if "Наименование в RKeeper" in headers:
        return "rkeeper"
    if "Наименование в Headline" in headers:
        return "headline"
    return None


def parse_price(raw: str) -> int:
    cleaned = str(raw).strip().replace(" ", "").replace(",", ".")
    if not cleaned:
        return 0
    try:
        return int(float(cleaned))
    except ValueError:
        return 0


def is_valid_catalog_row(row: list[str]) -> bool:
    if len(row) < 4:
        return False
    name = _cell(row, 0).strip()
    price = _cell(row, 3).strip()
    if not name or name.lower() == "наименование":
        return False
    return price != ""


def row_to_menu_item(
    row: list[str],
    *,
    internal_system: InternalSystem | None,
) -> MenuItem:
    name = _cell(row, 0).strip()
    description = _cell(row, 1)
    weight = _cell(row, 2)
    price = parse_price(_cell(row, 3))
    headline_name = _cell(row, 4).strip()
    rkeeper_name = _cell(row, 6).strip()

    if internal_system == "rkeeper":
        internal_name = rkeeper_name or headline_name
    elif internal_system == "headline":
        internal_name = headline_name
    else:
        internal_name = headline_name or rkeeper_name or None

    return MenuItem(
        sku_id=_slug(name),
        name=name,
        description=description,
        weight=weight,
        price=float(price),
        available=True,
        internal_system=internal_system,
        internal_name=internal_name or None,
        internal_id=None,
    )


def parse_general_catalog(rows: list[list[str]]) -> CatalogParseResult:
    """Parse FeedMer «Общий справочник» raw values (including header row)."""
    if not rows:
        return CatalogParseResult(items=[], internal_system=None)

    header = rows[0]
    internal_system = detect_internal_system(header)

    items: list[MenuItem] = []
    for row in rows[1:]:
        if not is_valid_catalog_row(row):
            continue
        items.append(row_to_menu_item(row, internal_system=internal_system))

    # Fallback: detect from data-key style if header missed
    if internal_system is None and items:
        # Already None; FeedMer also checks Object.keys of first row with headers
        pass

    return CatalogParseResult(items=items, internal_system=internal_system)
