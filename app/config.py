from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(default="", alias="BOT_TOKEN")
    telegram_proxy_url: str | None = Field(default=None, alias="TELEGRAM_PROXY_URL")
    openrouter_proxy_url: str | None = Field(default=None, alias="OPENROUTER_PROXY_URL")
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(default="openai/gpt-6-luna", alias="OPENROUTER_MODEL")
    vision_model: str = Field(default="qwen/qwen3-vl-30b-a3b-instruct", alias="VISION_MODEL")
    image_analysis_mode: str = Field(default="direct", alias="IMAGE_ANALYSIS_MODE")
    image_max_bytes: int = Field(default=8 * 1024 * 1024, alias="IMAGE_MAX_BYTES", ge=1, le=20 * 1024 * 1024)
    database_url: str = Field(default="sqlite+aiosqlite:///./tggoals.db", alias="DATABASE_URL")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1/chat/completions",
        alias="OPENROUTER_BASE_URL",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
