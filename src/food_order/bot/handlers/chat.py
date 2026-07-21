from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from food_order.orchestration.orchestrator import OrderOrchestrator
from food_order.storage.sessions import SessionStore

router = Router()

_user_locks: set[int] = set()


@router.message(F.text)
async def handle_text(
    message: Message,
    orchestrator: OrderOrchestrator,
    sessions: SessionStore,
) -> None:
    if not message.from_user or not message.text:
        return

    user_id = message.from_user.id
    if user_id in _user_locks:
        await message.answer("Подождите, обрабатываю предыдущее сообщение...")
        return

    _user_locks.add(user_id)
    try:
        await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
        state = await sessions.get(user_id)
        result = await orchestrator.handle_message(
            telegram_user_id=user_id,
            text=message.text.strip(),
            state=state,
        )
        await sessions.save(user_id, result.state)
        await message.answer(result.reply_text)
    finally:
        _user_locks.discard(user_id)
