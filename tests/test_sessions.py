import pytest

from food_order.domain.models import OrderItem, OrderState
from food_order.storage.sessions import SessionStore


@pytest.mark.asyncio
async def test_inmemory_session_roundtrip() -> None:
    store = SessionStore()
    await store.init()
    state = OrderState(
        items=[OrderItem(sku_id="1", name="Шаурма", qty=1, unit_price=250)],
    )
    await store.save(42, state)
    loaded = await store.get(42)
    assert loaded.items[0].name == "Шаурма"
    loaded.items[0].qty = 99
    again = await store.get(42)
    assert again.items[0].qty == 1  # deep copy isolation
    await store.delete(42)
    empty = await store.get(42)
    assert empty.items == []
