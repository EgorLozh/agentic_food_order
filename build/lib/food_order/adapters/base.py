from __future__ import annotations

from abc import ABC, abstractmethod

from food_order.domain.models import CreatedOrder, MenuItem, OrderState, PickupPoint


class MenuSource(ABC):
    @abstractmethod
    async def get_menu(self) -> list[MenuItem]: ...

    @abstractmethod
    async def get_pickup_points(self) -> list[PickupPoint]: ...


class OrderSink(ABC):
    @abstractmethod
    async def create_order(
        self,
        *,
        telegram_user_id: int,
        state: OrderState,
        total: float,
    ) -> CreatedOrder: ...


class DataAdapter(MenuSource, OrderSink, ABC):
    """Combined read/write adapter for menu, points, and orders."""
