from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from food_order.bot.keyboards import build_choice_keyboard
from food_order.storage.sessions import SessionStore

router = Router()

START_TEXT = (
    "Привет! Я помогу оформить заказ на самовывоз.\n"
    "Нажмите «Начать заказ» или напишите заказ своими словами, например:\n"
    "«Две шаурмы и колу к 14:00»"
)
START_CHOICE = "Начать заказ"


@router.message(CommandStart())
async def cmd_start(message: Message, sessions: SessionStore) -> None:
    if message.from_user:
        await sessions.clear(message.from_user.id)
    await message.answer(
        START_TEXT,
        reply_markup=build_choice_keyboard([START_CHOICE]),
    )
