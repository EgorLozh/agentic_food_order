from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import Message

from food_order.bot.keyboards import build_choice_keyboard, remove_choice_keyboard
from food_order.orchestration.orchestrator import OrderOrchestrator
from food_order.storage.sessions import SessionStore

router = Router()

_user_locks: set[int] = set()

_BUSY_TEXT = "Подождите, обрабатываю предыдущее сообщение..."


async def _process_user_turn(
    *,
    bot: Bot,
    chat_id: int,
    user_id: int,
    user_text: str,
    orchestrator: OrderOrchestrator,
    sessions: SessionStore,
) -> None:
    if user_id in _user_locks:
        await bot.send_message(chat_id, _BUSY_TEXT)
        return

    _user_locks.add(user_id)
    try:
        await bot.send_chat_action(chat_id=chat_id, action="typing")
        session = await sessions.get(user_id)
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
        await bot.send_message(
            chat_id,
            result.reply_text,
            reply_markup=(
                build_choice_keyboard(result.choices)
                if result.choices
                else remove_choice_keyboard()
            ),
        )
        await sessions.save(user_id, session)
    finally:
        _user_locks.discard(user_id)


@router.message(F.text)
async def handle_text(
    message: Message,
    orchestrator: OrderOrchestrator,
    sessions: SessionStore,
) -> None:
    if not message.from_user or not message.text or message.bot is None:
        return

    await _process_user_turn(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        user_text=message.text.strip(),
        orchestrator=orchestrator,
        sessions=sessions,
    )
