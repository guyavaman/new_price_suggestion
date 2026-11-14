from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""

    @field_validator("anthropic_api_key", "llm_model", mode="before")
    @classmethod
    def _strip(cls, v):  # a key pasted with a trailing newline or spaces still works
        return v.strip() if isinstance(v, str) else v
    llm_model: str = "claude-sonnet-5-5"

    @field_validator("llm_model")
    @classmethod
    def _default_model(cls, v: str) -> str:  # LLM_MODEL="" means "use the default"
        return v or "claude-sonnet-5-5"
    llm_max_tokens: int = 2048

    database_url: str = "postgresql+psycopg://quote:quote@localhost:5432/quote_agent"

    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dim: int = 384

    vat_rate: float = 0.18
    currency: str = "ILS"


@lru_cache
def get_settings() -> Settings:
    return Settings()
