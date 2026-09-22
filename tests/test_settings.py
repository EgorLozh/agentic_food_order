import pytest
from pydantic import ValidationError

from food_order.settings import Settings


def _base_kwargs(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "BOT_TOKEN": "test-token",
        "LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "sk-test",
    }
    data.update(overrides)
    return data


def test_deepseek_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="DEEPSEEK_API_KEY"):
        Settings(**_base_kwargs(LLM_PROVIDER="deepseek", OPENAI_API_KEY=None))


def test_deepseek_accepts_api_key() -> None:
    settings = Settings(
        **_base_kwargs(
            LLM_PROVIDER="deepseek",
            OPENAI_API_KEY=None,
            DEEPSEEK_API_KEY="sk-deepseek",
        )
    )
    assert settings.llm_provider == "deepseek"
    assert settings.deepseek_api_key == "sk-deepseek"
    assert settings.deepseek_model == "deepseek-flash"
    assert settings.deepseek_base_url == "https://api.deepseek.com"
