import pytest

from food_order.adapters.json_fixtures import JsonFixturesAdapter
from food_order.adapters.sheets.client import FeedMerSheetsAdapter
from food_order.domain.models import MenuItem, PickupPoint
from food_order.tools.menu import MenuMatcher, resolve_pickup_point
from pathlib import Path


@pytest.fixture
def adapter() -> JsonFixturesAdapter:
    return JsonFixturesAdapter(
        Path("config/fixtures"),
        Path("config/cafes.yaml"),
        pos_sync_enabled=True,
    )


@pytest.mark.asyncio
async def test_menu_matcher_exact_match(adapter: JsonFixturesAdapter) -> None:
    menu = await adapter.get_menu()
    matcher = MenuMatcher(menu)
    item, candidates = matcher.resolve_item("Шаурма", 2)
    assert item is not None
    assert item.name == "Шаурма"
    assert item.qty == 2
    assert not candidates


@pytest.mark.asyncio
async def test_menu_matcher_exact_is_case_sensitive(adapter: JsonFixturesAdapter) -> None:
    menu = await adapter.get_menu()
    matcher = MenuMatcher(menu)
    # lowercase is not exact FeedMer match; fuzzy/aliases still resolve
    item, _ = matcher.resolve_item("шаурма", 1)
    assert item is not None
    assert item.name == "Шаурма"


@pytest.mark.asyncio
async def test_menu_matcher_fuzzy_slang(adapter: JsonFixturesAdapter) -> None:
    menu = await adapter.get_menu()
    matcher = MenuMatcher(menu)
    item, candidates = matcher.resolve_item("шаверму", 2)
    assert item is not None
    assert item.name == "Шаурма"
    assert item.qty == 2
    assert not candidates


@pytest.mark.asyncio
async def test_pos_sync_in_fixtures(adapter: JsonFixturesAdapter) -> None:
    menu = await adapter.get_menu()
    shaurma = next(i for i in menu if i.name == "Шаурма")
    assert shaurma.price == 270.0
    assert shaurma.internal_id == "RK-001"


@pytest.mark.asyncio
async def test_resolve_pickup_from_cafes_yaml(adapter: JsonFixturesAdapter) -> None:
    points = await adapter.get_pickup_points()
    point, candidates = resolve_pickup_point("на центре", points)
    assert point is not None
    assert candidates == []
    assert point.point_id == "67"
    assert point.address == "ул. Ленина, 10"


def test_resolve_pickup_ambiguous_shared_alias() -> None:
    points = [
        PickupPoint(
            point_id="1",
            name="Raketa на Молодежной",
            aliases=["ракета", "на ракете"],
            address="ул. Гагарина, 5",
        ),
        PickupPoint(
            point_id="2",
            name="Raketa на Петрова",
            aliases=["ракета", "на ракете"],
            address="ул. Петрова, 10",
        ),
    ]
    point, candidates = resolve_pickup_point("на Ракете", points)
    assert point is None
    assert {c.point_id for c in candidates} == {"1", "2"}


def test_resolve_pickup_clear_winner() -> None:
    points = [
        PickupPoint(
            point_id="1",
            name="Raketa на Молодежной",
            aliases=["молодежная", "на молодежной"],
            address="ул. Гагарина, 5",
        ),
        PickupPoint(
            point_id="2",
            name="Raketa на Петрова",
            aliases=["петрова", "на петрова"],
            address="ул. Петрова, 10",
        ),
    ]
    point, candidates = resolve_pickup_point("Молодежной", points)
    assert point is not None
    assert point.point_id == "1"
    assert candidates == []


def test_feedmer_cache_guard_rejects_too_few() -> None:
    adapter = FeedMerSheetsAdapter(
        spreadsheet_id="fake",
        api_sheets_google_key='{"type":"service_account"}',
        google_service_account_json=None,
        cafes_config_path=Path("config/cafes.yaml"),
    )
    few = [MenuItem(sku_id="1", name="A", price=1) for _ in range(5)]
    assert adapter._apply_cache_guards(few) is None


def test_feedmer_cache_guard_rollback_soft_min() -> None:
    adapter = FeedMerSheetsAdapter(
        spreadsheet_id="fake",
        api_sheets_google_key='{"type":"service_account"}',
        google_service_account_json=None,
        cafes_config_path=Path("config/cafes.yaml"),
    )
    adapter._menu_cache = (0, [MenuItem(sku_id="old", name="Old", price=100)])
    medium = [MenuItem(sku_id=str(i), name=f"I{i}", price=10) for i in range(15)]
    assert adapter._apply_cache_guards(medium) is None


def test_feedmer_cache_guard_accepts_enough() -> None:
    adapter = FeedMerSheetsAdapter(
        spreadsheet_id="fake",
        api_sheets_google_key='{"type":"service_account"}',
        google_service_account_json=None,
        cafes_config_path=Path("config/cafes.yaml"),
    )
    many = [MenuItem(sku_id=str(i), name=f"I{i}", price=10) for i in range(25)]
    accepted = adapter._apply_cache_guards(many)
    assert accepted is not None
    assert len(accepted) == 25
