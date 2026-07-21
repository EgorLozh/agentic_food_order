from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from food_order.storage.sessions import SessionStore

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, sessions: SessionStore) -> None:
    if message.from_user:
        await sessions.clear(message.from_user.id)
    await message.answer(
        "Привет! Я помогу оформить заказ на самовывоз.\n"
        "Напишите заказ свободным текстом, например:\n"
        "«Две шаурмы и колу к 14:00 на Центр»"
    )
