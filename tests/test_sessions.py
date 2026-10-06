import pytest

from food_order.domain.models import OrderItem, OrderState
from food_order.storage.sessions import SessionData, SessionStore


@pytest.mark.asyncio
async def test_inmemory_session_roundtrip() -> None:
    store = SessionStore()
    await store.init()
    session = SessionData(
        state=OrderState(
            items=[OrderItem(sku_id="1", name="Шаурма", qty=1, unit_price=250)],
        )
    )
    session.pending_choices = ["Центр", "Север"]
    session.choices_message_id = 15
    await store.save(42, session)
    loaded = await store.get(42)
    assert loaded.state.items[0].name == "Шаурма"
    assert loaded.pending_choices == ["Центр", "Север"]
    assert loaded.choices_message_id == 15
    loaded.pending_choices.append("Юг")
    loaded.state.items[0].qty = 99
    again = await store.get(42)
    assert again.state.items[0].qty == 1  # deep copy isolation
    assert again.pending_choices == ["Центр", "Север"]
    await store.delete(42)
    empty = await store.get(42)
    assert empty.state.items == []
    assert empty.history == []
