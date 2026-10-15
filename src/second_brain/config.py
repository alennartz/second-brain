from typing import Literal

from pydantic_settings import BaseSettings

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    db_path: str = "data/brain.db"
    embedding_model: str = "openai:text-embedding-3-small"
    reasoning_model: str = "openai:gpt-4o-mini"
    reasoning_effort: ReasoningEffort | None = None
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
    # Intake staging and worker-pipeline limits.
    intake_max_request_chars: int = 100_000
    intake_chunk_chars: int = 4_000
    intake_processing_batch_chars: int = 12_000
    intake_worker_concurrency: int = 1
    intake_lease_seconds: float = 300
    intake_poll_interval_seconds: float = 1
    intake_retry_base_delay_seconds: float = 5
    intake_retry_max_delay_seconds: float = 3_600

    model_config = {"env_prefix": "BRAIN_", "env_file": ".env"}


settings = Settings()
