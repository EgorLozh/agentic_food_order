from __future__ import annotations

import json

from food_order.domain.models import PhraseResult
from food_order.llm.client import LLMClient
from food_order.orchestration.actions import Action

PHRASE_SYSTEM = """\
Ты — вежливый ассистент ресторана. Сформулируй короткий ответ клиенту на русском.
Используй только факты из payload. Не выдумывай позиции, точки, цены и время.
Не используй markdown. 1-3 предложения, естественный тон.
"""


class ResponsePhraser:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def phrase(self, action: Action, payload: dict) -> str:
        if action == Action.ERROR:
            return "Сейчас не получилось обработать запрос. Попробуйте ещё раз через минуту."

        user_payload = {"action": action.value, **payload}
        result = await self.llm.parse(
            system=PHRASE_SYSTEM,
            user=json.dumps(user_payload, ensure_ascii=False),
            schema=PhraseResult,
        )
        return result.reply_text.strip()
