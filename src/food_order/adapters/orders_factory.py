from __future__ import annotations

import structlog
from aiogram import Bot

from food_order.adapters.base import OrderSink
from food_order.adapters.postgres_orders import PostgresOrderSink
from food_order.adapters.telegram_orders import TelegramAdminOrderSink
from food_order.domain.models import CreatedOrder, OrderState
from food_order.settings import Settings

logger = structlog.get_logger(__name__)

SINK_MODES = ("telegram", "postgres", "both")


class CompositeOrderSink(OrderSink):
    """Fan one order out to several sinks.

    The primary sink (the shared DB) must succeed — its failure fails the order
    for the customer. Notification sinks are best-effort: a failure is logged
    and the order stays persisted in the shared DB.
    """

    def __init__(self, primary: OrderSink, notifications: list[OrderSink] | None = None) -> None:
        self.primary = primary
        self.notifications = list(notifications or [])

    async def create_order(
        self,
        *,
        telegram_user_id: int,
        state: OrderState,
        total: float,
    ) -> CreatedOrder:
        created = await self.primary.create_order(
            telegram_user_id=telegram_user_id, state=state, total=total
        )
        for sink in self.notifications:
            try:
                await sink.create_order(
                    telegram_user_id=telegram_user_id, state=state, total=total
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "order_notification_failed",
                    sink=type(sink).__name__,
                    order_id=created.order_id,
                )
        return created

    async def close(self) -> None:
        for sink in (self.primary, *self.notifications):
            close = getattr(sink, "close", None)
            if close is not None:
                await close()


def build_order_sink(settings: Settings, *, bot: Bot | None = None) -> OrderSink:
    """Build the order sink(s) selected by ORDER_SINK (telegram|postgres|both)."""
    mode = (settings.order_sink or "telegram").strip().lower()
    if mode not in SINK_MODES:
        raise RuntimeError(f"ORDER_SINK must be one of {SINK_MODES}, got {mode!r}")

    telegram: OrderSink | None = None
    if mode in ("telegram", "both"):
        if bot is None or settings.admin_telegram_id is None:
            if mode == "telegram":
                raise RuntimeError(
                    "ORDER_SINK=telegram requires a bot instance and ADMIN_TELEGRAM_ID"
                )
            logger.warning("telegram_notify_skipped", reason="no ADMIN_TELEGRAM_ID or bot")
        else:
            telegram = TelegramAdminOrderSink(bot, settings.admin_telegram_id)

    if mode == "telegram":
        assert telegram is not None  # guaranteed by the branch above
        return telegram

    db_url = settings.orders_database_url or settings.database_url
    if not db_url:
        raise RuntimeError("ORDER_SINK=postgres requires ORDERS_DATABASE_URL or DATABASE_URL")

    postgres = PostgresOrderSink(
        db_url,
        default_cafe_id=settings.orders_default_cafe_id,
    )
    if mode == "postgres":
        return postgres
    return CompositeOrderSink(postgres, [telegram] if telegram is not None else [])
