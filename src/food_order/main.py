from __future__ import annotations

import asyncio
import logging
import sys

import structlog

from food_order.adapters.factory import build_data_adapter
from food_order.adapters.pickup import build_pickup_source
from food_order.adapters.telegram_orders import TelegramAdminOrderSink
from food_order.bot.app import create_bot, create_dispatcher
from food_order.domain.schema_loader import load_order_schema
from food_order.llm.client import LLMClient
from food_order.llm.order_agent import OrderAgent
from food_order.orchestration.orchestrator import OrderOrchestrator
from food_order.settings import get_settings
from food_order.storage.sessions import SessionStore
from food_order.tools.registry import ToolRegistry


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )


async def run() -> None:
    settings = get_settings()
    if settings.admin_telegram_id is None:
        raise RuntimeError("ADMIN_TELEGRAM_ID is required in .env")

    schema = load_order_schema(settings.order_schema_path)

    pickup = build_pickup_source(settings)
    adapter = build_data_adapter(settings, pickup_source=pickup)

    bot = create_bot(settings)
    order_sink = TelegramAdminOrderSink(bot, settings.admin_telegram_id)
    tools = ToolRegistry(menu_source=adapter, order_sink=order_sink)

    llm = LLMClient(settings)
    agent = OrderAgent(llm=llm, schema=schema, tools=tools)
    orchestrator = OrderOrchestrator(
        agent=agent,
    )

    sessions = SessionStore()
    await sessions.init()

    dp = create_dispatcher(settings, orchestrator, sessions)

    logging.info(
        "Starting bot polling (adapter=%s pickup=%s)",
        type(adapter).__name__,
        type(pickup).__name__,
    )
    try:
        await dp.start_polling(bot)
    finally:
        close = getattr(pickup, "close", None)
        if close is not None:
            await close()


def main() -> None:
    configure_logging()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run())


if __name__ == "__main__":
    main()
