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
        session = await sessions.get(user_id)
        user_text = message.text.strip()
        result = await orchestrator.handle_message(
            telegram_user_id=user_id,
            text=user_text,
            state=session.state,
            history=session.history,
        )
        session.state = result.state
        if result.clear_history:
            session.history = []
        else:
            sessions.append_turn(
                session,
                user_text=user_text,
                assistant_text=result.reply_text,
            )
        await sessions.save(user_id, session)
        await message.answer(result.reply_text)
    finally:
        _user_locks.discard(user_id)
