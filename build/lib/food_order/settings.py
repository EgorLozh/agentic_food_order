from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")

    spreadsheet_id: str | None = Field(default=None, alias="SPREADSHEET_ID")
    google_service_account_json: str | None = Field(
        default=None, alias="GOOGLE_SERVICE_ACCOUNT_JSON"
    )

    order_schema_path: Path = Field(
        default=Path("config/order_schema.yaml"), alias="ORDER_SCHEMA_PATH"
    )
    sqlite_path: Path = Field(default=Path("data/sessions.db"), alias="SQLITE_PATH")
    cache_ttl_seconds: int = Field(default=300, alias="CACHE_TTL_SECONDS")

    fixtures_dir: Path = Field(default=Path("config/fixtures"))

    llm_timeout_seconds: float = 30.0
    llm_max_tokens: int = 512


def get_settings() -> Settings:
    return Settings()
