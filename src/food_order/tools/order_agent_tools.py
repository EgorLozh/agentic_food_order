from __future__ import annotations

import re
import unicodedata
from typing import Any

import structlog

from food_order.domain.merge import merge_resolved_items
from food_order.domain.models import OrderItem, OrderSchema, OrderState, OrderStatus, PaymentMethod
from food_order.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)

ORDER_AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_order_draft",
            "description": "Получить текущий проверенный черновик заказа.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_menu",
            "description": "Получить всё доступное меню текущего кафе с реальными SKU, названиями, ценами, описаниями и весом. Перед set_items обязательно вызови этот tool.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_items",
            "description": "Добавить или заменить позиции черновика по SKU, полученному из get_menu.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sku_id": {"type": "string"},
                                "qty": {"type": "integer", "minimum": 1},
                            },
                            "required": ["sku_id", "qty"],
                            "additionalProperties": False,
                        },
                    },
                    "replace": {"type": "boolean", "default": False},
                },
                "required": ["items"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_pickup_points",
            "description": "Получить доступные реальные пункты самовывоза.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_pickup_point",
            "description": "Установить пункт самовывоза по названию или адресу; проверяет совпадение с доступными точками.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_pickup_time",
            "description": "Установить время самовывоза строго в формате HH:MM.",
            "parameters": {
                "type": "object",
                "properties": {"time": {"type": "string"}},
                "required": ["time"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_payment_method",
            "description": "Установить способ оплаты: cash или card.",
            "parameters": {
                "type": "object",
                "properties": {"payment_method": {"type": "string", "enum": ["cash", "card"]}},
                "required": ["payment_method"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_summary",
            "description": "Проверить полноту и получить итог заказа. Если все поля заполнены, заказ переводится в ожидание явного подтверждения клиента.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_order",
            "description": "Отменить и очистить текущий черновик заказа.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_order",
            "description": "Передать заказ администратору. Вызывай только после get_order_summary и лишь когда текущее сообщение пользователя является явным подтверждением.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]

_CONFIRMATIONS = {
    "да",
    "да все верно",
    "все верно",
    "всё верно",
    "подтверждаю",
    "подтверждаю заказ",
    "оформляй",
    "оформляйте",
    "оформить",
}
_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def is_explicit_confirmation(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text.lower()).strip()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized in _CONFIRMATIONS


class OrderAgentTools:
    def __init__(
        self,
        *,
        tools: ToolRegistry,
        schema: OrderSchema,
        state: OrderState,
        telegram_user_id: int,
        user_text: str,
    ) -> None:
        self.tools = tools
        self.schema = schema
        self.state = state
        self.telegram_user_id = telegram_user_id
        self.user_text = user_text
        self._submitted_order_id: str | None = None
        self._clear_history = False

    def should_clear_history(self) -> bool:
        return self._clear_history

    def _draft(self) -> dict[str, Any]:
        return self.state.model_dump(mode="json")

    def _missing_fields(self) -> list[str]:
        missing: list[str] = []
        if "items" in self.schema.required_fields and not self.state.items:
            missing.append("items")
        if "pickup_point_id" in self.schema.required_fields and not self.state.pickup_point_id:
            missing.append("pickup_point_id")
        if "pickup_time" in self.schema.required_fields and not self.state.pickup_time:
            missing.append("pickup_time")
        if "payment_method" in self.schema.required_fields and not self.state.payment_method:
            missing.append("payment_method")
        return missing

    def _mark_collecting(self) -> None:
        if self.state.status != OrderStatus.CREATED:
            self.state.status = OrderStatus.COLLECTING

    async def dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "get_order_draft": self.get_order_draft,
            "get_menu": self.get_menu,
            "set_items": self.set_items,
            "list_pickup_points": self.list_pickup_points,
            "set_pickup_point": self.set_pickup_point,
            "set_pickup_time": self.set_pickup_time,
            "set_payment_method": self.set_payment_method,
            "get_order_summary": self.get_order_summary,
            "cancel_order": self.cancel_order,
            "submit_order": self.submit_order,
        }
        handler = handlers.get(name)
        if handler is None:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        try:
            result = await handler(arguments)
            logger.info("agent_tool_result", tool=name, ok=result.get("ok", False))
            return result
        except Exception as exc:  # noqa: BLE001
            logger.exception("agent_tool_error", tool=name, error=str(exc))
            return {"ok": False, "error": "Tool temporarily unavailable. Do not assume it succeeded."}

    async def get_order_draft(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "draft": self._draft(), "missing_fields": self._missing_fields()}

    async def get_menu(self, _: dict[str, Any]) -> dict[str, Any]:
        menu = await self.tools.get_menu()
        return {
            "ok": True,
            "items": [
                {
                    "sku_id": item.sku_id,
                    "name": item.name,
                    "price": item.price,
                    "description": item.description,
                    "weight": item.weight,
                }
                for item in menu
                if item.available
            ],
        }

    async def set_items(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_items = arguments.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            return {"ok": False, "error": "items must be a non-empty list"}
        menu = await self.tools.get_menu()
        by_sku = {item.sku_id: item for item in menu if item.available}
        order_items = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                return {"ok": False, "error": "Each item must be an object"}
            sku_id = str(raw.get("sku_id") or "")
            qty = raw.get("qty")
            if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
                return {"ok": False, "error": f"Invalid quantity for SKU {sku_id}"}
            menu_item = by_sku.get(sku_id)
            if menu_item is None:
                return {"ok": False, "error": f"Unknown or unavailable SKU {sku_id}"}
            order_items.append(
                OrderItem(
                    sku_id=menu_item.sku_id,
                    name=menu_item.name,
                    qty=qty,
                    unit_price=menu_item.price,
                )
            )
        merge_resolved_items(self.state, order_items, replace=bool(arguments.get("replace")))
        self._mark_collecting()
        return {"ok": True, "items": [item.model_dump(mode="json") for item in self.state.items]}

    async def list_pickup_points(self, _: dict[str, Any]) -> dict[str, Any]:
        points = await self.tools.get_pickup_points()
        return {
            "ok": True,
            "pickup_points": [
                {"point_id": point.point_id, "name": point.name, "address": point.address}
                for point in points
                if point.active
            ],
        }

    async def set_pickup_point(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        point = await self.tools.resolve_point(query)
        if point is None:
            return {"ok": False, "error": "Pickup point not found. Call list_pickup_points."}
        self.state.pickup_point_id = point.point_id
        self.state.pickup_point_name = point.name
        self.state.pickup_point_address = point.address
        self._mark_collecting()
        return {"ok": True, "pickup_point": {"name": point.name, "address": point.address}}

    async def set_pickup_time(self, arguments: dict[str, Any]) -> dict[str, Any]:
        pickup_time = str(arguments.get("time") or "").strip()
        if not _TIME_PATTERN.fullmatch(pickup_time):
            return {"ok": False, "error": "Time must use HH:MM in 24-hour format"}
        self.state.pickup_time = pickup_time
        self._mark_collecting()
        return {"ok": True, "pickup_time": pickup_time}

    async def set_payment_method(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = str(arguments.get("payment_method") or "").lower()
        if value not in self.schema.payment_methods:
            return {"ok": False, "error": f"Payment method must be one of {self.schema.payment_methods}"}
        self.state.payment_method = PaymentMethod(value)
        self._mark_collecting()
        return {"ok": True, "payment_method": value}

    async def get_order_summary(self, _: dict[str, Any]) -> dict[str, Any]:
        missing = self._missing_fields()
        if missing:
            return {"ok": False, "missing_fields": missing, "error": "Order is incomplete"}
        self.state.status = OrderStatus.AWAITING_CONFIRMATION
        return {
            "ok": True,
            "summary": {
                "items": [item.model_dump(mode="json") for item in self.state.items],
                "pickup_point": self.state.pickup_point_name,
                "pickup_address": self.state.pickup_point_address,
                "pickup_time": self.state.pickup_time,
                "payment_method": self.state.payment_method.value if self.state.payment_method else None,
                "total": self.tools.calculate_order(self.state),
            },
            "requires_explicit_confirmation": True,
        }

    async def cancel_order(self, _: dict[str, Any]) -> dict[str, Any]:
        self.state.reset_for_new_order()
        self._clear_history = True
        return {"ok": True, "message": "Order draft cleared"}

    async def submit_order(self, _: dict[str, Any]) -> dict[str, Any]:
        if self._submitted_order_id is not None:
            return {"ok": False, "error": "Order already submitted in this message"}
        missing = self._missing_fields()
        if missing:
            return {"ok": False, "error": "Order is incomplete", "missing_fields": missing}
        if self.state.status != OrderStatus.AWAITING_CONFIRMATION:
            return {"ok": False, "error": "Call get_order_summary and wait for customer confirmation first"}
        if not is_explicit_confirmation(self.user_text):
            return {"ok": False, "error": "Current user message is not an explicit confirmation"}

        created = await self.tools.create_order(
            telegram_user_id=self.telegram_user_id,
            state=self.state,
        )
        self._submitted_order_id = created.order_id
        self.state.reset_for_new_order()
        self._clear_history = True
        return {"ok": True, "order_id": created.order_id, "total": created.total}
