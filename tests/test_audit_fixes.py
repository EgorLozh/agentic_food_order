from unittest.mock import AsyncMock, MagicMock

import pytest

from food_order.adapters.postgres_cafes import cafe_row_to_pickup_point, rows_to_pickup_points
from food_order.adapters.telegram_orders import (
    TelegramAdminOrderSink,
    format_admin_order_message,
)
from food_order.domain.models import (
    MenuItem,
    OrderItem,
    OrderState,
    PaymentMethod,
)
from food_order.tools.menu import MenuMatcher


def test_cafe_row_to_pickup_point_strips_city() -> None:
    point = cafe_row_to_pickup_point(
        {
            "cafeId": 69,
            "cafeName": "Юг",
            "addrOfCafe": "Ижевск ул. Пушкинская, 20",
            "formalAddrOfCafe": "Ижевск, ул. Пушкинская, 20",
            "city": "Ижевск",
            "region": "Удмуртия",
        }
    )
    assert point.point_id == "69"
    assert point.name == "Юг"
    assert point.address == "ул. Пушкинская, 20"
    assert point.formal_address == "Ижевск, ул. Пушкинская, 20"


def test_cafe_row_formal_fallback() -> None:
    point = cafe_row_to_pickup_point(
        {
            "cafeId": 67,
            "cafeName": "Центр",
            "addrOfCafe": "ул. Ленина, 10",
            "formalAddrOfCafe": "",
            "city": "Ижевск",
        }
    )
    assert point.address == "ул. Ленина, 10"
    assert point.formal_address == "Ижевск ул. Ленина, 10"


def test_cafe_row_from_db_schema_name_only() -> None:
    point = cafe_row_to_pickup_point({"cafeId": 68, "cafeName": "Север"})
    assert point.point_id == "68"
    assert point.name == "Север"
    assert point.address is None


def test_rows_merge_yaml_overlay() -> None:
    rows = [{"cafeId": 67, "cafeName": "Центр"}]
    yaml_by_id = {
        67: {
            "addrOfCafe": "ул. Ленина, 10",
            "formalAddrOfCafe": "Ижевск, ул. Ленина, 10",
            "city": "Ижевск",
            "aliases": ["центр"],
        }
    }
    points = rows_to_pickup_points(rows, yaml_by_id=yaml_by_id)
    assert points[0].address == "ул. Ленина, 10"
    assert "центр" in points[0].aliases


def test_format_admin_order_message() -> None:
    state = OrderState(
        items=[OrderItem(sku_id="1", name="Куриная Мини 200г", qty=1, unit_price=250)],
        pickup_point_name="Юг",
        pickup_point_address="ул. Пушкинская, 20",
        pickup_time="16:30",
        payment_method=PaymentMethod.CARD,
        phone="+79001234567",
    )
    text = format_admin_order_message(
        order_id="ORD-TEST",
        telegram_user_id=1251838936,
        state=state,
        total=250,
    )
    assert "ORD-TEST" in text
    assert "1251838936" in text
    assert "Куриная Мини 200г" in text
    assert "16:30" in text
    assert "картой" in text
    assert "+79001234567" in text


@pytest.mark.asyncio
async def test_telegram_admin_order_sink_sends_message() -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock()
    sink = TelegramAdminOrderSink(bot, admin_telegram_id=42)
    state = OrderState(
        items=[OrderItem(sku_id="1", name="Шаурма", qty=2, unit_price=250)],
        pickup_point_id="67",
        pickup_point_name="Центр",
        pickup_time="14:00",
        payment_method=PaymentMethod.CASH,
        phone="89001234567",
    )
    created = await sink.create_order(telegram_user_id=7, state=state, total=500)
    assert created.order_id.startswith("ORD-")
    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 42
    assert "Шаурма" in kwargs["text"]
    assert "7" in kwargs["text"]


def test_matcher_chicken_shawarma_excludes_batter() -> None:
    menu = [
        MenuItem(sku_id="1", name="Кляр для шаурмы", price=50),
        MenuItem(sku_id="2", name="Куриная Мини 200г", price=250),
        MenuItem(sku_id="3", name="Куриная Стандарт 320г", price=320),
    ]
    matcher = MenuMatcher(menu)
    item, candidates = matcher.resolve_item("куриную шаурму", 1)
    assert item is None
    assert "Кляр для шаурмы" not in candidates
    assert any("Куриная" in c for c in candidates)


def test_matcher_mini_typo() -> None:
    menu = [
        MenuItem(sku_id="1", name="Кляр для шаурмы", price=50),
        MenuItem(sku_id="2", name="Куриная Мини 200г", price=250),
        MenuItem(sku_id="3", name="Куриная Стандарт 320г", price=320),
    ]
    matcher = MenuMatcher(menu)
    item, candidates = matcher.resolve_item("Куринная мини", 1)
    assert item is not None
    assert item.name == "Куриная Мини 200г"
    assert not candidates


def test_matcher_does_not_autobind_shaurmy_to_batter() -> None:
    menu = [
        MenuItem(sku_id="1", name="Кляр для шаурмы", price=50),
        MenuItem(sku_id="2", name="Шаурма", price=250, aliases=["шаурму", "шаверму"]),
    ]
    matcher = MenuMatcher(menu)
    item, candidates = matcher.resolve_item("шаурмы", 1)
    # Should not auto-accept batter via substring
    if item is not None:
        assert item.name != "Кляр для шаурмы"
    else:
        assert "Кляр для шаурмы" not in candidates or candidates[0] == "Шаурма"
