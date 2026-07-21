from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from food_order.domain.models import OrderState

DialogRole = Literal["user", "assistant"]


@dataclass
class DialogMessage:
    role: DialogRole
    content: str


@dataclass
class SessionData:
    state: OrderState = field(default_factory=OrderState)
    history: list[DialogMessage] = field(default_factory=list)


class SessionStore:
    """In-process dialog state + short transcript. Cleared on bot restart."""

    def __init__(self, *, history_limit: int = 6) -> None:
        self.history_limit = max(0, history_limit)
        self._sessions: dict[int, SessionData] = {}

    async def init(self) -> None:
        return None

    async def get(self, telegram_user_id: int) -> SessionData:
        session = self._sessions.get(telegram_user_id)
        if session is None:
            return SessionData()
        return SessionData(
            state=session.state.model_copy(deep=True),
            history=[DialogMessage(role=m.role, content=m.content) for m in session.history],
        )

    async def save(self, telegram_user_id: int, session: SessionData) -> None:
        self._sessions[telegram_user_id] = SessionData(
            state=session.state.model_copy(deep=True),
            history=[DialogMessage(role=m.role, content=m.content) for m in session.history],
        )

    def append_turn(
        self,
        session: SessionData,
        *,
        user_text: str,
        assistant_text: str,
    ) -> SessionData:
        if self.history_limit <= 0:
            session.history = []
            return session
        session.history.append(DialogMessage(role="user", content=user_text))
        session.history.append(DialogMessage(role="assistant", content=assistant_text))
        session.history = session.history[-self.history_limit :]
        return session

    async def clear(self, telegram_user_id: int) -> None:
        self._sessions[telegram_user_id] = SessionData()

    async def delete(self, telegram_user_id: int) -> None:
        self._sessions.pop(telegram_user_id, None)
