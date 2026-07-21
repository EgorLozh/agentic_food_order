from __future__ import annotations

from dataclasses import dataclass

import structlog

from food_order.domain.models import OrderState
from food_order.llm.order_agent import OrderAgent
from food_order.storage.sessions import DialogMessage

logger = structlog.get_logger(__name__)


@dataclass
class TurnResult:
    reply_text: str
    state: OrderState
    clear_history: bool = False


class OrderOrchestrator:
    def __init__(self, *, agent: OrderAgent) -> None:
        self.agent = agent

    async def handle_message(
        self,
        *,
        telegram_user_id: int,
        text: str,
        state: OrderState,
        history: list[DialogMessage] | None = None,
    ) -> TurnResult:
        try:
            turn = await self.agent.respond(
                telegram_user_id=telegram_user_id,
                text=text,
                state=state,
                history=history,
            )
            logger.info(
                "agent_turn",
                user_id=telegram_user_id,
                tool_rounds=turn.tool_rounds,
                history_len=len(history or []),
            )
            return TurnResult(
                reply_text=turn.reply_text,
                state=state,
                clear_history=turn.clear_history,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("orchestrator_error", user_id=telegram_user_id, error=str(exc))
            return TurnResult(
                reply_text="Сейчас не получилось обработать запрос. Попробуйте ещё раз.",
                state=state,
            )
