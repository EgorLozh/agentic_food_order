from __future__ import annotations

import asyncio
import logging
import sys

import structlog

from food_order.adapters.factory import build_data_adapter
from food_order.bot.app import create_bot, create_dispatcher
from food_order.domain.schema_loader import load_order_schema
from food_order.llm.client import LLMClient
from food_order.llm.extractor import SlotExtractor
from food_order.llm.phraser import ResponsePhraser
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
    schema = load_order_schema(settings.order_schema_path)

    adapter = build_data_adapter(settings)
    tools = ToolRegistry(menu_source=adapter, order_sink=adapter)

    llm = LLMClient(settings)
    extractor = SlotExtractor(llm, schema)
    phraser = ResponsePhraser(llm)
    orchestrator = OrderOrchestrator(
        schema=schema,
        extractor=extractor,
        phraser=phraser,
        tools=tools,
    )

    sessions = SessionStore(settings.sqlite_path)
    await sessions.init()

    bot = create_bot(settings)
    dp = create_dispatcher(settings, orchestrator, sessions)

    logging.info("Starting bot polling (adapter=%s)", type(adapter).__name__)
    await dp.start_polling(bot)


def main() -> None:
    configure_logging()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run())


if __name__ == "__main__":
    main()
