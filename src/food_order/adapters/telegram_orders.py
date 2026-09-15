from __future__ import annotations

import time
import uuid

import structlog
from aiogram import Bot

from food_order.adapters.base import OrderSink
from food_order.domain.models import CreatedOrder, OrderState, PaymentMethod

logger = structlog.get_logger(__name__)

_PAYMENT_LABELS = {
    PaymentMethod.CASH: "наличными",
    PaymentMethod.CARD: "картой",
}


def format_admin_order_message(
    *,
    order_id: str,
    telegram_user_id: int,
    state: OrderState,
    total: float,
) -> str:
    lines = [
        f"Новый заказ {order_id}",
        f"Клиент Telegram ID: {telegram_user_id}",
        "",
        "Позиции:",
    ]
    for item in state.items:
        lines.append(f"• {item.qty}× {item.name} — {item.unit_price:.0f} ₽")

    pickup = state.pickup_point_name or "—"
    if state.pickup_point_address:
        pickup = f"{pickup} ({state.pickup_point_address})"
    payment = (
        _PAYMENT_LABELS.get(state.payment_method, state.payment_method.value)
        if state.payment_method
        else "—"
    )
    lines.extend(
        [
            "",
            f"Самовывоз: {pickup}",
            f"Время: {state.pickup_time or '—'}",
            f"Оплата: {payment}",
            f"Телефон: {state.phone or '—'}",
            f"Итого: {total:.0f} ₽",
        ]
    )
    return "\n".join(lines)


class TelegramAdminOrderSink(OrderSink):
    """Notify admin via Telegram instead of persisting the order."""

    def __init__(self, bot: Bot, admin_telegram_id: int) -> None:
        self.bot = bot
        self.admin_telegram_id = admin_telegram_id

    async def create_order(
        self,
        *,
        telegram_user_id: int,
        state: OrderState,
        total: float,
    ) -> CreatedOrder:
        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        text = format_admin_order_message(
            order_id=order_id,
            telegram_user_id=telegram_user_id,
            state=state,
            total=total,
        )
        payload = {
            "order_id": order_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "telegram_user_id": telegram_user_id,
            "cafe_id": state.pickup_point_id or "",
            "pickup_time": state.pickup_time or "",
            "payment": state.payment_method.value if state.payment_method else "",
            "phone": state.phone or "",
            "total": total,
            "status": "new",
            "admin_notified": True,
        }
        try:
            await self.bot.send_message(chat_id=self.admin_telegram_id, text=text)
        except Exception:
            logger.exception(
                "admin_notify_failed",
                admin_id=self.admin_telegram_id,
                order_id=order_id,
            )
            raise
        return CreatedOrder(order_id=order_id, total=total, payload=payload)
