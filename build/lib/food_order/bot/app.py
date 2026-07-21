from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from food_order.bot.handlers import cancel, chat, start
from food_order.bot.middlewares import AppMiddleware
from food_order.orchestration.orchestrator import OrderOrchestrator
from food_order.settings import Settings
from food_order.storage.sessions import SessionStore


def create_dispatcher(
    settings: Settings,
    orchestrator: OrderOrchestrator,
    sessions: SessionStore,
) -> Dispatcher:
    dp = Dispatcher()
    dp.message.middleware(AppMiddleware(orchestrator, sessions))
    dp.include_router(start.router)
    dp.include_router(cancel.router)
    dp.include_router(chat.router)

    @dp.errors()
    async def on_error(event, exception):  # type: ignore[no-untyped-def]
        logging.exception("bot_error", exc_info=exception)
        return True

    return dp


def create_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
