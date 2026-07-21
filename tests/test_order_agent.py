from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from food_order.adapters.json_fixtures import JsonFixturesAdapter
from food_order.domain.models import OrderState, OrderStatus
from food_order.domain.schema_loader import load_order_schema
from food_order.llm.order_agent import MAX_TOOL_ROUNDS, OrderAgent
from food_order.tools.order_agent_tools import OrderAgentTools, is_explicit_confirmation
from food_order.tools.registry import ToolRegistry


@pytest.fixture
def schema():
    return load_order_schema(Path("config/order_schema.yaml"))


@pytest.fixture
def registry() -> ToolRegistry:
    adapter = JsonFixturesAdapter(Path("config/fixtures"), Path("config/cafes.yaml"))
    return ToolRegistry(menu_source=adapter, order_sink=adapter)


def _agent_tools(
    registry: ToolRegistry,
    schema,
    state: OrderState | None = None,
    user_text: str = "тест",
) -> OrderAgentTools:
    return OrderAgentTools(
        tools=registry,
        schema=schema,
        state=state or OrderState(),
        telegram_user_id=7,
        user_text=user_text,
    )


@pytest.mark.asyncio
async def test_set_items_requires_real_sku(registry: ToolRegistry, schema) -> None:
    toolset = _agent_tools(registry, schema)
    result = await toolset.dispatch(
        "set_items",
        {"items": [{"sku_id": "invented", "qty": 1}]},
    )
    assert result["ok"] is False
    assert not toolset.state.items


@pytest.mark.asyncio
async def test_get_menu_then_set_item_and_complete_summary(
    registry: ToolRegistry, schema
) -> None:
    toolset = _agent_tools(registry, schema)
    menu = await toolset.dispatch("get_menu", {})
    assert menu["ok"] is True
    shaurma = next(item for item in menu["items"] if item["name"] == "Шаурма")
    sku_id = shaurma["sku_id"]
    assert (await toolset.dispatch("set_items", {"items": [{"sku_id": sku_id, "qty": 2}]}))["ok"]
    assert (await toolset.dispatch("set_pickup_point", {"query": "Центр"}))["ok"]
    assert (await toolset.dispatch("set_pickup_time", {"time": "14:00"}))["ok"]
    assert (await toolset.dispatch("set_payment_method", {"payment_method": "cash"}))["ok"]
    summary = await toolset.dispatch("get_order_summary", {})
    assert summary["ok"] is True
    assert summary["summary"]["total"] > 0
    assert toolset.state.status == OrderStatus.AWAITING_CONFIRMATION


@pytest.mark.asyncio
async def test_invalid_slot_values_are_rejected(registry: ToolRegistry, schema) -> None:
    toolset = _agent_tools(registry, schema)
    assert not (await toolset.dispatch("set_pickup_time", {"time": "25:70"}))["ok"]
    assert not (await toolset.dispatch("set_payment_method", {"payment_method": "crypto"}))["ok"]
    assert not (await toolset.dispatch("set_pickup_point", {"query": "Несуществующая точка"}))["ok"]


@pytest.mark.asyncio
async def test_submit_guard_requires_confirmation_and_clears_after_success(
    registry: ToolRegistry, schema
) -> None:
    toolset = _agent_tools(registry, schema, user_text="да")
    menu = await toolset.dispatch("get_menu", {})
    shaurma = next(item for item in menu["items"] if item["name"] == "Шаурма")
    await toolset.dispatch("set_items", {"items": [{"sku_id": shaurma["sku_id"], "qty": 1}]})
    await toolset.dispatch("set_pickup_point", {"query": "Центр"})
    await toolset.dispatch("set_pickup_time", {"time": "14:00"})
    await toolset.dispatch("set_payment_method", {"payment_method": "card"})

    blocked = await toolset.dispatch("submit_order", {})
    assert blocked["ok"] is False
    assert "summary" in blocked["error"]

    await toolset.dispatch("get_order_summary", {})
    created = await toolset.dispatch("submit_order", {})
    assert created["ok"] is True
    assert not toolset.state.items
    assert toolset.state.status == OrderStatus.COLLECTING
    assert not (await toolset.dispatch("submit_order", {}))["ok"]


@pytest.mark.asyncio
async def test_submit_guard_rejects_non_confirmation(
    registry: ToolRegistry, schema
) -> None:
    toolset = _agent_tools(registry, schema, user_text="а можно доставку")
    menu = await toolset.dispatch("get_menu", {})
    shaurma = next(item for item in menu["items"] if item["name"] == "Шаурма")
    await toolset.dispatch("set_items", {"items": [{"sku_id": shaurma["sku_id"], "qty": 1}]})
    await toolset.dispatch("set_pickup_point", {"query": "Центр"})
    await toolset.dispatch("set_pickup_time", {"time": "14:00"})
    await toolset.dispatch("set_payment_method", {"payment_method": "card"})
    await toolset.dispatch("get_order_summary", {})
    result = await toolset.dispatch("submit_order", {})
    assert result["ok"] is False
    assert "explicit confirmation" in result["error"]
    assert is_explicit_confirmation("всё верно")
    assert not is_explicit_confirmation("возможно")


class FakeLLM:
    def __init__(self, messages: list[SimpleNamespace]) -> None:
        self.messages = messages
        self.calls = 0

    async def complete_with_tools(self, **_: object) -> SimpleNamespace:
        message = self.messages[self.calls]
        self.calls += 1
        return message


def _tool_call(name: str, arguments: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


@pytest.mark.asyncio
async def test_agent_loop_runs_tool_then_returns_final_reply(registry: ToolRegistry, schema) -> None:
    llm = FakeLLM(
        [
            SimpleNamespace(content=None, tool_calls=[_tool_call("get_order_draft", {})]),
            SimpleNamespace(content="Чем могу помочь с заказом?", tool_calls=[]),
        ]
    )
    agent = OrderAgent(llm=llm, schema=schema, tools=registry)  # type: ignore[arg-type]
    turn = await agent.respond(telegram_user_id=7, text="привет", state=OrderState())
    assert turn.reply_text == "Чем могу помочь с заказом?"
    assert turn.tool_rounds == 1


@pytest.mark.asyncio
async def test_agent_loop_stops_at_tool_round_limit(registry: ToolRegistry, schema) -> None:
    llm = FakeLLM(
        [
            SimpleNamespace(content=None, tool_calls=[_tool_call("get_order_draft", {})])
            for _ in range(MAX_TOOL_ROUNDS)
        ]
    )
    agent = OrderAgent(llm=llm, schema=schema, tools=registry)  # type: ignore[arg-type]
    turn = await agent.respond(telegram_user_id=7, text="привет", state=OrderState())
    assert turn.tool_rounds == MAX_TOOL_ROUNDS
    assert "Не удалось завершить" in turn.reply_text
