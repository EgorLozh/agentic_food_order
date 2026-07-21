import json
from pathlib import Path

import pytest

from food_order.adapters.sheets.general_catalog import (
    detect_internal_system,
    is_valid_catalog_row,
    parse_general_catalog,
)
from food_order.adapters.sheets.pos_pricelist import enrich_with_pos_prices, parse_pos_rows
from food_order.domain.models import MenuItem


@pytest.fixture
def catalog_rows() -> list[list[str]]:
    path = Path("config/fixtures/general_catalog_rows.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_detect_internal_system_rkeeper(catalog_rows: list[list[str]]) -> None:
    assert detect_internal_system(catalog_rows[0]) == "rkeeper"


def test_parse_general_catalog_filters_invalid(catalog_rows: list[list[str]]) -> None:
    result = parse_general_catalog(catalog_rows)
    names = [item.name for item in result.items]
    assert "Шаурма" in names
    assert "Кола" in names
    assert "Салат Цезарь" not in names  # empty price
    assert "" not in names


def test_parse_general_catalog_prices(catalog_rows: list[list[str]]) -> None:
    result = parse_general_catalog(catalog_rows)
    shaurma = next(i for i in result.items if i.name == "Шаурма")
    assert shaurma.price == 250.0
    assert shaurma.internal_name == "Shawarma POS"
    assert shaurma.internal_system == "rkeeper"


def test_is_valid_catalog_row() -> None:
    assert is_valid_catalog_row(["Шаурма", "", "", "250"])
    assert not is_valid_catalog_row(["", "", "", "250"])
    assert not is_valid_catalog_row(["Шаурма", "", ""])
    assert not is_valid_catalog_row(["Наименование", "", "", "100"])


def test_pos_price_override() -> None:
    pos_rows = json.loads(
        Path("config/fixtures/pos_rkeeper_rows.json").read_text(encoding="utf-8")
    )
    lookup = parse_pos_rows(pos_rows, internal_system="rkeeper")
    items = [
        MenuItem(
            sku_id="shaurma",
            name="Шаурма",
            price=250,
            internal_name="Shawarma POS",
            internal_system="rkeeper",
        )
    ]
    enriched = enrich_with_pos_prices(items, lookup)
    assert enriched[0].internal_id == "RK-001"
    assert enriched[0].sku_id == "RK-001"
    assert enriched[0].price == 270.0
