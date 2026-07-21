from __future__ import annotations

from food_order.domain.models import OrderState


class SessionStore:
    """In-process dialog state. Cleared on bot restart."""

    def __init__(self) -> None:
        self._states: dict[int, OrderState] = {}

    async def init(self) -> None:
        return None

    async def get(self, telegram_user_id: int) -> OrderState:
        state = self._states.get(telegram_user_id)
        if state is None:
            return OrderState()
        return state.model_copy(deep=True)

    async def save(self, telegram_user_id: int, state: OrderState) -> None:
        self._states[telegram_user_id] = state.model_copy(deep=True)

    async def delete(self, telegram_user_id: int) -> None:
        self._states.pop(telegram_user_id, None)
