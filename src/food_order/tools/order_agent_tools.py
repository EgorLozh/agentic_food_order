from __future__ import annotations

import re
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
            "description": (
                "Черновик уже есть в current_draft. Вызывай только чтобы сверить состояние "
                "после tool calls в этом ходе."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_menu",
            "description": (
                "Получить доступное меню с реальными SKU, названиями, ценами, описаниями и весом. "
                "Вызови перед set_items, если SKU ещё нет в результатах tools этого хода. "
                "Не выдумывай SKU и не бери их из истории диалога."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_items",
            "description": (
                "Добавить или заменить позиции по SKU из get_menu. "
                "По умолчанию позиции мержатся: qty того же SKU суммируется. "
                "Передай replace=true, если клиент заново перечислил весь состав заказа "
                "или хочет заменить позиции, а не добавить."
            ),
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
            "description": "Получить доступные пункты самовывоза (название и адрес). Не выдумывай точки.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_pickup_point",
            "description": (
                "Установить пункт самовывоза по названию или адресу из list_pickup_points. "
                "Если tool вернул candidates — перечисли их клиенту и спроси, какую выбрать; "
                "не выбирай первую молча."
            ),
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
            "description": (
                "Установить время самовывоза строго HH:MM, 24 часа. "
                "Не вызывай, если клиент сказал только «вечером» / «утром» / «через час» "
                "без конкретного HH:MM — сначала уточни время."
            ),
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
            "description": (
                "Установить оплату: внутренние значения cash или card. "
                "Клиенту говори «наличные» / «карта»."
            ),
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
            "name": "set_phone",
            "description": (
                "Сохранить телефон клиента для заказа. Передай номер, как сказал клиент; "
                "tool нормализует в +7XXXXXXXXXX. Не выдумывай номер и не подставляй Telegram ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {"phone": {"type": "string"}},
                "required": ["phone"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_summary",
            "description": (
                "Проверить полноту (позиции, точка, время, оплата, телефон) и получить итог. "
                "Если всё заполнено, статус станет awaiting_confirmation — после этого можно "
                "просить согласие и при согласии в текущем сообщении вызывать submit_order."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_order",
            "description": "Отменить и очистить текущий черновик, если клиент отменяет заказ целиком.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_order",
            "description": (
                "Передать заказ администратору. Вызывай только после успешного get_order_summary "
                "и только если текущее сообщение клиента — согласие со сводкой. "
                "Не вызывай при вопросах, правках или неуверенности."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]

_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

_MISSING_FIELD_LABELS = {
    "items": "позиции",
    "pickup_point_id": "точку самовывоза",
    "pickup_time": "время (HH:MM)",
    "payment_method": "способ оплаты",
    "phone": "телефон",
}


def normalize_ru_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] in "78":
        return f"+7{digits[1:]}"
    if len(digits) == 10:
        return f"+7{digits}"
    return None


class OrderAgentTools:
    def __init__(
        self,
        *,
        tools: ToolRegistry,
        schema: OrderSchema,
        state: OrderState,
        telegram_user_id: int,
    ) -> None:
        self.tools = tools
        self.schema = schema
        self.state = state
        self.telegram_user_id = telegram_user_id
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
        if "phone" in self.schema.required_fields and not self.state.phone:
            missing.append("phone")
        return missing

    def _has_draft_progress(self) -> bool:
        return bool(
            self.state.items
            or self.state.pickup_point_id
            or self.state.pickup_time
            or self.state.payment_method
            or self.state.phone
        )

    def reply_on_tool_limit(self) -> str:
        missing = self._missing_fields()
        if not self._has_draft_progress() or not missing:
            return (
                "Не удалось завершить обработку запроса за один шаг. "
                "Пожалуйста, уточните заказ или попробуйте ещё раз."
            )
        labels = [_MISSING_FIELD_LABELS[m] for m in missing if m in _MISSING_FIELD_LABELS]
        if not labels:
            return (
                "Не удалось завершить обработку запроса за один шаг. "
                "Пожалуйста, уточните заказ или попробуйте ещё раз."
            )
        return f"Уточните, пожалуйста: {', '.join(labels)}."

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
            "set_phone": self.set_phone,
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
        point, candidates = await self.tools.resolve_point(query)
        if candidates:
            return {
                "ok": False,
                "error": "Ambiguous pickup point. Ask the customer which one.",
                "candidates": [
                    {"name": c.name, "address": c.address} for c in candidates
                ],
            }
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

    async def set_phone(self, arguments: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_ru_phone(str(arguments.get("phone") or ""))
        if normalized is None:
            return {
                "ok": False,
                "error": "Phone must be a Russian number: +7XXXXXXXXXX or 8XXXXXXXXXX",
            }
        self.state.phone = normalized
        self._mark_collecting()
        return {"ok": True, "phone": normalized}

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
                "phone": self.state.phone,
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

        created = await self.tools.create_order(
            telegram_user_id=self.telegram_user_id,
            state=self.state,
        )
        self._submitted_order_id = created.order_id
        self.state.reset_for_new_order()
        self._clear_history = True
        return {"ok": True, "order_id": created.order_id, "total": created.total}
