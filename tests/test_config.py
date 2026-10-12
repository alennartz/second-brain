from second_brain.config import Settings


def test_test_mode_defaults_false():
    assert Settings.model_fields["test_mode"].default is False


def test_test_mode_from_env(monkeypatch):
    monkeypatch.setenv("BRAIN_TEST_MODE", "true")
    s = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert s.test_mode is True


def test_foundry_url_fields_default_none():
    s = Settings(_env_file=None, db_path="data/brain.db")  # pyright: ignore[reportCallIssue]
    assert s.reasoning_foundry_url is None
    assert s.embedding_foundry_url is None
    assert s.reasoning_base_url is None
    assert s.embedding_base_url is None


def test_auth_fields_default_key():
    s = Settings(_env_file=None, db_path="data/brain.db")  # pyright: ignore[reportCallIssue]
    assert s.reasoning_auth == "key"
    assert s.embedding_auth == "key"


def test_foundry_url_from_env(monkeypatch):
    monkeypatch.setenv("BRAIN_REASONING_FOUNDRY_URL", "https://r.azure.com")
    monkeypatch.setenv("BRAIN_EMBEDDING_FOUNDRY_URL", "https://e.azure.com")
    s = Settings(_env_file=None, db_path="data/brain.db")  # pyright: ignore[reportCallIssue]
    assert s.reasoning_foundry_url == "https://r.azure.com"
    assert s.embedding_foundry_url == "https://e.azure.com"


def test_openai_compatible_base_urls_from_env(monkeypatch):
    monkeypatch.setenv("BRAIN_REASONING_BASE_URL", "http://llm.local/v1")
    monkeypatch.setenv("BRAIN_EMBEDDING_BASE_URL", "http://embed.local/v1")
    s = Settings(_env_file=None, db_path="data/brain.db")  # pyright: ignore[reportCallIssue]
    assert s.reasoning_base_url == "http://llm.local/v1"
    assert s.embedding_base_url == "http://embed.local/v1"


def test_auth_from_env(monkeypatch):
    monkeypatch.setenv("BRAIN_REASONING_AUTH", "aad")
    monkeypatch.setenv("BRAIN_EMBEDDING_AUTH", "aad")
    s = Settings(_env_file=None, db_path="data/brain.db")  # pyright: ignore[reportCallIssue]
    assert s.reasoning_auth == "aad"
    assert s.embedding_auth == "aad"


def test_dream_defaults():
    """Dream settings have sensible defaults."""
    s = Settings(_env_file=None, db_path="data/brain.db")  # pyright: ignore[reportCallIssue]
    assert s.dream_enabled is True
    assert s.dream_idle_timeout_minutes == 10
    assert s.dream_batch_size == 25
