from __future__ import annotations

from enum import StrEnum


class Action(StrEnum):
    ASK_ITEMS = "ask_items"
    CLARIFY_ITEMS = "clarify_items"
    ASK_PICKUP_POINT = "ask_pickup_point"
    ASK_PICKUP_TIME = "ask_pickup_time"
    ASK_PAYMENT_METHOD = "ask_payment_method"
    SHOW_SUMMARY = "show_summary"
    CREATE_ORDER = "create_order"
    ORDER_CREATED = "order_created"
    CANCELLED = "cancelled"
    GREET = "greet"
    ERROR = "error"
    FREE_REPLY = "free_reply"
