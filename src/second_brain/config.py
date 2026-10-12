from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_path: str = "data/brain.db"
    embedding_model: str = "openai:text-embedding-3-small"
    reasoning_model: str = "openai:gpt-4o-mini"
    reasoning_base_url: str | None = None
    embedding_base_url: str | None = None
    embedding_dimensions: int = 1536
    test_mode: bool = False
    reasoning_foundry_url: str | None = None
    reasoning_auth: Literal["key", "aad"] = "key"
    embedding_foundry_url: str | None = None
    embedding_auth: Literal["key", "aad"] = "key"
    embedding_key: str | None = None
    reasoning_key: str | None = None
    dream_enabled: bool = True
    dream_idle_timeout_minutes: float = 10
    dream_delay_multiplier: float = 1.5
    dream_max_delay_minutes: float = 720
    dream_batch_size: int = 25
    # Jev fast-path routing (converse)
    jev_enabled: bool = True  # kill switch; live from day one (user decision)
    # Versioned id, pinned at implementation time (never `jev-latest` — thresholds
    # are tuned against a specific build).
    jev_model: str = "typesafe:jev-1.13.0"
    jev_key: str | None = None  # explicit override; else TYPESAFE_API_KEY
    # High bar: only confident fast paths skip the LLM router.
    jev_confidence_threshold: float = 0.9
    jev_history_turns: int = 3  # history turns included in the routing state

    model_config = {"env_prefix": "BRAIN_", "env_file": ".env"}


settings = Settings()
