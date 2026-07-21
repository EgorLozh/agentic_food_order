from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from food_order.orchestration.orchestrator import OrderOrchestrator
from food_order.storage.sessions import SessionStore


class AppMiddleware(BaseMiddleware):
    def __init__(
        self,
        orchestrator: OrderOrchestrator,
        sessions: SessionStore,
    ) -> None:
        self.orchestrator = orchestrator
        self.sessions = sessions
        self._locks: dict[int, bool] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["orchestrator"] = self.orchestrator
        data["sessions"] = self.sessions
        return await handler(event, data)
