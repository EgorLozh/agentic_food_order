from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(alias="BOT_TOKEN")

    llm_provider: Literal["openai", "ollama"] = Field(
        default="openai", alias="LLM_PROVIDER"
    )
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")

    ollama_base_url: str = Field(
        default="http://localhost:11434/v1", alias="OLLAMA_BASE_URL"
    )
    ollama_model: str = Field(default="gemma4:31b", alias="OLLAMA_MODEL")
    ollama_api_key: str = Field(default="ollama", alias="OLLAMA_API_KEY")

    admin_telegram_id: int | None = Field(default=None, alias="ADMIN_TELEGRAM_ID")
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    cafe_ids: str | None = Field(default=None, alias="CAFE_IDS")

    spreadsheet_id: str | None = Field(default=None, alias="SPREADSHEET_ID")
    api_sheets_google_key: str | None = Field(
        default=None, alias="API_SHEETS_GOOGLE_KEY"
    )
    google_service_account_json: str | None = Field(
        default=None, alias="GOOGLE_SERVICE_ACCOUNT_JSON"
    )

    cafe_id: int | None = Field(default=None, alias="CAFE_ID")
    ss_pricelist_id: str | None = Field(default=None, alias="SS_PRICELIST_ID")
    pos_sync_enabled: bool = Field(default=False, alias="POS_SYNC_ENABLED")

    order_schema_path: Path = Field(
        default=Path("config/order_schema.yaml"), alias="ORDER_SCHEMA_PATH"
    )
    cafes_config_path: Path = Field(
        default=Path("config/cafes.yaml"), alias="CAFES_CONFIG_PATH"
    )
    menu_aliases_path: Path = Field(
        default=Path("config/menu_aliases.yaml"), alias="MENU_ALIASES_PATH"
    )
    menu_cache_ttl_seconds: int = Field(default=900, alias="MENU_CACHE_TTL_SECONDS")
    cache_ttl_seconds: int = Field(default=900, alias="CACHE_TTL_SECONDS")
    dialog_history_limit: int = Field(default=6, alias="DIALOG_HISTORY_LIMIT")

    fixtures_dir: Path = Field(default=Path("config/fixtures"))

    llm_timeout_seconds: float = Field(default=30.0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_tokens: int | None = Field(default=None, alias="LLM_MAX_TOKENS")

    @field_validator("pos_sync_enabled", mode="before")
    @classmethod
    def parse_bool(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @model_validator(mode="after")
    def require_openai_api_key(self) -> Settings:
        if self.llm_provider == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        return self

    def has_sheets_credentials(self) -> bool:
        return bool(
            self.spreadsheet_id
            and (self.api_sheets_google_key or self.google_service_account_json)
        )


def get_settings() -> Settings:
    return Settings()
