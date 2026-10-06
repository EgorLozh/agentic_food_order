from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from food_order.domain.models import OrderState
from food_order.orchestration.orchestrator import AGENT_ERROR_REPLY, OrderOrchestrator


class SlowAgent:
    async def respond(self, **_: object) -> SimpleNamespace:
        await asyncio.sleep(1.0)
        return SimpleNamespace(reply_text="ok", tool_rounds=1, clear_history=False)


class FastAgent:
    async def respond(self, **_: object) -> SimpleNamespace:
        return SimpleNamespace(reply_text="готово", tool_rounds=0, clear_history=False)


class ChoiceAgent:
    async def respond(self, **_: object) -> SimpleNamespace:
        return SimpleNamespace(
            reply_text="Какую точку?",
            tool_rounds=1,
            clear_history=False,
            choices=["Центр", "Север"],
        )


class BoomAgent:
    async def respond(self, **_: object) -> SimpleNamespace:
        raise RuntimeError("llm down")


@pytest.mark.asyncio
async def test_orchestrator_timeout_returns_apology() -> None:
    orch = OrderOrchestrator(agent=SlowAgent(), turn_timeout_seconds=0.05)  # type: ignore[arg-type]
    result = await orch.handle_message(
        telegram_user_id=1,
        text="привет",
        state=OrderState(),
    )
    assert result.reply_text == AGENT_ERROR_REPLY
    assert "ошибк" in result.reply_text.casefold()


@pytest.mark.asyncio
async def test_orchestrator_success_passes_reply() -> None:
    orch = OrderOrchestrator(agent=FastAgent(), turn_timeout_seconds=5.0)  # type: ignore[arg-type]
    result = await orch.handle_message(
        telegram_user_id=1,
        text="привет",
        state=OrderState(),
    )
    assert result.reply_text == "готово"
    assert result.choices == []


@pytest.mark.asyncio
async def test_orchestrator_passes_choices() -> None:
    orch = OrderOrchestrator(agent=ChoiceAgent(), turn_timeout_seconds=5.0)  # type: ignore[arg-type]
    result = await orch.handle_message(
        telegram_user_id=1,
        text="где забрать",
        state=OrderState(),
    )
    assert result.reply_text == "Какую точку?"
    assert result.choices == ["Центр", "Север"]


@pytest.mark.asyncio
async def test_orchestrator_exception_returns_apology() -> None:
    orch = OrderOrchestrator(agent=BoomAgent(), turn_timeout_seconds=5.0)  # type: ignore[arg-type]
    result = await orch.handle_message(
        telegram_user_id=1,
        text="привет",
        state=OrderState(),
    )
    assert result.reply_text == AGENT_ERROR_REPLY
