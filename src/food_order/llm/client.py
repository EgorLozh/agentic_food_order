from __future__ import annotations

import json
from typing import Any, TypeVar

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessage
from pydantic import BaseModel

from food_order.settings import Settings

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        if settings.llm_provider == "ollama":
            kwargs: dict = {
                "api_key": settings.ollama_api_key,
                "base_url": settings.ollama_base_url,
            }
            self.model = settings.ollama_model
        else:
            kwargs = {"api_key": settings.openai_api_key}
            if settings.openai_base_url:
                kwargs["base_url"] = settings.openai_base_url
            self.model = settings.openai_model

        self.client = AsyncOpenAI(**kwargs)
        self.provider = settings.llm_provider
        self.timeout = settings.llm_timeout_seconds
        self.max_tokens = settings.llm_max_tokens

    def _token_limit_kwargs(self) -> dict[str, int]:
        if self.max_tokens is None:
            return {}
        if self.provider == "ollama":
            return {"max_tokens": self.max_tokens}
        return {"max_completion_tokens": self.max_tokens}

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
            timeout=self.timeout,
            **self._token_limit_kwargs(),
        )
        message = response.choices[0].message
        if message.parsed is not None:
            return message.parsed
        if message.content:
            return schema.model_validate(json.loads(message.content))
        raise RuntimeError("LLM returned empty structured response")

    async def complete_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ChatCompletionMessage:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            tools=tools,  # type: ignore[arg-type]
            tool_choice="auto",
            timeout=self.timeout,
            **self._token_limit_kwargs(),
        )
        if not response.choices:
            raise RuntimeError("LLM returned no completion choices")
        return response.choices[0].message
