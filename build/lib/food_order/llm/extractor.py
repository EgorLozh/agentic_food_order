from __future__ import annotations

import json

from food_order.domain.models import ExtractResult, OrderState, OrderSchema
from food_order.llm.client import LLMClient

EXTRACT_SYSTEM = """\
Ты — экстрактор слотов для заказа еды на самовывоз.
Верни только структурированный JSON по схеме.

Правила:
- intent=confirm если пользователь явно соглашается (да, подтверждаю, ок, верно).
- intent=cancel если отменяет заказ.
- intent=update_order если меняет уже известные данные или дополняет заказ.
- intent=create_order если описывает новый заказ или позиции.
- intent=other для приветствий и общих вопросов без данных заказа.
- Не выдумывай позиции, которых нет в сообщении.
- pickup_time в формате HH:MM если возможно.
- payment_method: cash или card если явно указано.
- user_confirmed=true только при явном подтверждении.
"""


class SlotExtractor:
    def __init__(self, llm: LLMClient, schema: OrderSchema) -> None:
        self.llm = llm
        self.schema = schema

    async def extract(self, text: str, state: OrderState) -> ExtractResult:
        user_payload = {
            "user_message": text,
            "current_state": state.model_dump(mode="json"),
            "payment_methods": self.schema.payment_methods,
            "fulfillment": self.schema.fulfillment,
        }
        return await self.llm.parse(
            system=EXTRACT_SYSTEM,
            user=json.dumps(user_payload, ensure_ascii=False),
            schema=ExtractResult,
        )
