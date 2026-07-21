from __future__ import annotations

import json
from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel

from food_order.settings import Settings

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        kwargs: dict = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        self.client = AsyncOpenAI(**kwargs)
        self.model = settings.openai_model
        self.timeout = settings.llm_timeout_seconds
        self.max_tokens = settings.llm_max_tokens

    async def parse(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
    ) -> T:
        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=schema,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )
        message = response.choices[0].message
        if message.parsed is not None:
            return message.parsed
        if message.content:
            return schema.model_validate(json.loads(message.content))
        raise RuntimeError("LLM returned empty structured response")
