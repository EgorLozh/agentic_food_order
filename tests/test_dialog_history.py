from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from food_order.adapters.json_fixtures import JsonFixturesAdapter
from food_order.domain.models import OrderState
from food_order.domain.schema_loader import load_order_schema
from food_order.llm.order_agent import OrderAgent
from food_order.storage.sessions import DialogMessage, SessionData, SessionStore
from food_order.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_session_append_trims_to_limit() -> None:
    store = SessionStore(history_limit=2)
    session = SessionData()
    store.append_turn(session, user_text="u1", assistant_text="a1")
    store.append_turn(session, user_text="u2", assistant_text="a2")
    store.append_turn(session, user_text="u3", assistant_text="a3")
    assert [m.content for m in session.history] == ["u3", "a3"]
    await store.save(1, session)
    loaded = await store.get(1)
    assert [m.content for m in loaded.history] == ["u3", "a3"]


@pytest.mark.asyncio
async def test_session_limit_zero_disables_history() -> None:
    store = SessionStore(history_limit=0)
    session = SessionData()
    store.append_turn(session, user_text="u1", assistant_text="a1")
    assert session.history == []


@pytest.mark.asyncio
async def test_session_clear_resets_draft_and_history() -> None:
    store = SessionStore(history_limit=6)
    session = SessionData(state=OrderState(pickup_time="14:00"))
    store.append_turn(session, user_text="привет", assistant_text="здравствуйте")
    await store.save(7, session)
    await store.clear(7)
    cleared = await store.get(7)
    assert cleared.history == []
    assert cleared.state.pickup_time is None


class CapturingLLM:
    def __init__(self) -> None:
        self.last_messages: list[dict] = []

    async def complete_with_tools(self, *, messages: list[dict], tools: list) -> SimpleNamespace:
        self.last_messages = messages
        return SimpleNamespace(content="Ок, продолжим.", tool_calls=[])


@pytest.mark.asyncio
async def test_agent_receives_history_in_messages() -> None:
    schema = load_order_schema(Path("config/order_schema.yaml"))
    adapter = JsonFixturesAdapter(Path("config/fixtures"), Path("config/cafes.yaml"))
    registry = ToolRegistry(menu_source=adapter, order_sink=adapter)
    llm = CapturingLLM()
    agent = OrderAgent(llm=llm, schema=schema, tools=registry)  # type: ignore[arg-type]
    history = [
        DialogMessage(role="user", content="хочу шаурму"),
        DialogMessage(role="assistant", content="Какую именно?"),
    ]
    turn = await agent.respond(
        telegram_user_id=1,
        text="мини",
        state=OrderState(),
        history=history,
    )
    assert turn.reply_text == "Ок, продолжим."
    roles = [m["role"] for m in llm.last_messages]
    assert roles[:4] == ["system", "user", "assistant", "user"]
    assert llm.last_messages[1]["content"] == "хочу шаурму"
    assert llm.last_messages[2]["content"] == "Какую именно?"
    payload = json.loads(llm.last_messages[3]["content"])
    assert payload["user_message"] == "мини"
    assert "phone" in payload["required_fields"]
    assert payload["fulfillment"] == "самовывоз, доставки нет"


@pytest.mark.asyncio
async def test_agent_limit_zero_history_not_injected() -> None:
    schema = load_order_schema(Path("config/order_schema.yaml"))
    adapter = JsonFixturesAdapter(Path("config/fixtures"), Path("config/cafes.yaml"))
    registry = ToolRegistry(menu_source=adapter, order_sink=adapter)
    llm = CapturingLLM()
    agent = OrderAgent(llm=llm, schema=schema, tools=registry)  # type: ignore[arg-type]
    await agent.respond(
        telegram_user_id=1,
        text="привет",
        state=OrderState(),
        history=[],
    )
    assert [m["role"] for m in llm.last_messages] == ["system", "user"]
