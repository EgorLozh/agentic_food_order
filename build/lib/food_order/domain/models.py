from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class OrderStatus(StrEnum):
    COLLECTING = "collecting"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CREATED = "created"


class UserIntent(StrEnum):
    CREATE_ORDER = "create_order"
    UPDATE_ORDER = "update_order"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    OTHER = "other"


class PaymentMethod(StrEnum):
    CASH = "cash"
    CARD = "card"


class OrderItem(BaseModel):
    sku_id: str
    name: str
    qty: int = Field(ge=1)
    unit_price: float = Field(ge=0)


class MenuItem(BaseModel):
    sku_id: str
    category: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    price: float
    available: bool = True


class PickupPoint(BaseModel):
    point_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    active: bool = True


class PendingClarification(BaseModel):
    raw_name: str
    candidates: list[str] = Field(default_factory=list)


class OrderState(BaseModel):
    items: list[OrderItem] = Field(default_factory=list)
    pickup_point_id: str | None = None
    pickup_point_name: str | None = None
    pickup_time: str | None = None
    payment_method: PaymentMethod | None = None
    status: OrderStatus = OrderStatus.COLLECTING
    last_order_id: str | None = None
    pending_clarifications: list[PendingClarification] = Field(default_factory=list)
    idempotency_key: str | None = None

    def reset_for_new_order(self) -> None:
        self.items = []
        self.pickup_point_id = None
        self.pickup_point_name = None
        self.pickup_time = None
        self.payment_method = None
        self.status = OrderStatus.COLLECTING
        self.pending_clarifications = []
        self.idempotency_key = None


class ExtractedItem(BaseModel):
    name: str
    qty: int = Field(default=1, ge=1)


class ExtractedData(BaseModel):
    items: list[ExtractedItem] | None = None
    pickup_point: str | None = None
    pickup_time: str | None = None
    payment_method: PaymentMethod | None = None


class ExtractResult(BaseModel):
    intent: UserIntent = UserIntent.OTHER
    extracted_data: ExtractedData = Field(default_factory=ExtractedData)
    user_confirmed: bool | None = None


class PhraseResult(BaseModel):
    reply_text: str


class OrderSchema(BaseModel):
    required_fields: list[str]
    payment_methods: list[str]
    fulfillment: str = "pickup_only"


class CreatedOrder(BaseModel):
    order_id: str
    total: float
    payload: dict[str, Any]
