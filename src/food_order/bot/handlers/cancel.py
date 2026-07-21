from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from food_order.storage.sessions import SessionStore

router = Router()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, sessions: SessionStore) -> None:
    if not message.from_user:
        return
    await sessions.clear(message.from_user.id)
    await message.answer("Заказ отменён. Можете начать новый.")
