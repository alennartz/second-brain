from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_path: str = "data/brain.db"
    embedding_model: str = "openai:text-embedding-3-small"
    reasoning_model: str = "openai:gpt-4o-mini"
    embedding_dimensions: int = 1536
    test_mode: bool = False
    reasoning_foundry_url: str | None = None
    reasoning_auth: Literal["key", "aad"] = "key"
    embedding_foundry_url: str | None = None
    embedding_auth: Literal["key", "aad"] = "key"

    model_config = {"env_prefix": "BRAIN_", "env_file": ".env"}


settings = Settings()
