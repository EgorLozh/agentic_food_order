from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я помогу оформить заказ на самовывоз.\n"
        "Напишите заказ свободным текстом, например:\n"
        "«Две шаурмы и колу к 14:00 на Центр»"
    )
