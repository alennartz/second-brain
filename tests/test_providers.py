from unittest.mock import patch

import pytest

from second_brain.providers import _parse_model_string, create_embed_fn, create_model


def test_parse_openai_model():
    provider, name = _parse_model_string("openai:gpt-4o-mini")
    assert provider == "openai"
    assert name == "gpt-4o-mini"


def test_parse_anthropic_model():
    provider, name = _parse_model_string("anthropic:claude-sonnet-4-5")
    assert provider == "anthropic"
    assert name == "claude-sonnet-4-5"


def test_parse_no_colon_raises():
    with pytest.raises(ValueError, match="provider:model_name"):
        _parse_model_string("gpt-4o-mini")


def test_create_model_no_foundry_returns_string():
    result = create_model("openai:gpt-4o-mini", foundry_url=None)
    assert result == "openai:gpt-4o-mini"


def test_create_model_no_foundry_any_provider():
    result = create_model("groq:llama-3.3-70b-versatile", foundry_url=None)
    assert result == "groq:llama-3.3-70b-versatile"


def test_create_model_openai_compatible_base_url():
    from pydantic_ai.models.openai import OpenAIChatModel

    result = create_model(
        "openai:gemma4-26b-a4b",
        foundry_url=None,
        key="none",
        base_url="http://jetson.ordernet:8082/v1",
    )
    assert isinstance(result, OpenAIChatModel)
    assert str(result.provider.client.base_url) == "http://jetson.ordernet:8082/v1/"


def test_create_model_openai_compatible_effort_setting():
    result = create_model(
        "openai:gemma4-26b-a4b",
        foundry_url=None,
        base_url="http://jetson.ordernet:8082/v1",
        reasoning_effort="low",
    )
    assert result.settings["openai_reasoning_effort"] == "low"


def test_create_model_direct_effort_builds_openai_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from pydantic_ai.models.openai import OpenAIChatModel

    result = create_model(
        "openai:gpt-4o-mini", foundry_url=None, reasoning_effort="medium"
    )
    assert isinstance(result, OpenAIChatModel)
    assert result.settings["openai_reasoning_effort"] == "medium"


def test_create_model_effort_rejects_non_openai_provider():
    with pytest.raises(ValueError, match="requires an openai: model"):
        create_model(
            "anthropic:claude-sonnet-4-5",
            foundry_url=None,
            reasoning_effort="low",
        )


def test_create_model_rejects_unsupported_custom_provider():
    with pytest.raises(ValueError, match="requires an openai: model"):
        create_model("groq:model", foundry_url=None, base_url="http://llm.local/v1")


def test_create_model_rejects_two_endpoints():
    with pytest.raises(ValueError, match="cannot both be set"):
        create_model(
            "openai:model",
            foundry_url="https://foundry.local",
            base_url="http://llm.local/v1",
        )


@patch("second_brain.providers._get_token_provider")
def test_create_model_foundry_openai(mock_token):
    from pydantic_ai.models.openai import OpenAIChatModel

    mock_token.return_value = lambda: "fake-token"
    result = create_model(
        "openai:gpt-4o-mini", foundry_url="https://my.azure.com", auth="aad"
    )
    assert isinstance(result, OpenAIChatModel)


def test_create_model_foundry_openai_effort_setting():
    result = create_model(
        "openai:gpt-4o-mini",
        foundry_url="https://my.azure.com",
        key="test-key",
        reasoning_effort="high",
    )
    assert result.settings["openai_reasoning_effort"] == "high"


@patch("second_brain.providers._get_token_provider")
def test_create_model_foundry_anthropic(mock_token):
    from pydantic_ai.models.anthropic import AnthropicModel

    mock_token.return_value = lambda: "fake-token"
    result = create_model(
        "anthropic:claude-sonnet-4-5",
        foundry_url="https://my.azure.com",
        auth="aad",
    )
    assert isinstance(result, AnthropicModel)


def test_create_model_foundry_unsupported_prefix():
    with pytest.raises(ValueError, match=r"anthropic.*openai"):
        create_model("groq:llama-3.3-70b", foundry_url="https://my.azure.com")


def test_create_embed_fn_no_foundry(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fn = create_embed_fn("openai:text-embedding-3-small", foundry_url=None)
    assert callable(fn)


@patch("second_brain.providers._get_token_provider")
def test_create_embed_fn_foundry(mock_token):
    mock_token.return_value = lambda: "fake-token"
    fn = create_embed_fn(
        "openai:text-embedding-3-small",
        foundry_url="https://my.azure.com",
        auth="aad",
    )
    assert callable(fn)


def test_create_embed_fn_openai_compatible_base_url():
    fn = create_embed_fn(
        "openai:harrier-oss-v1-0.6b",
        foundry_url=None,
        key="none",
        dimensions=1024,
        base_url="http://jetson.ordernet:8084/v1",
    )
    assert callable(fn)


def test_create_embed_fn_rejects_two_endpoints():
    with pytest.raises(ValueError, match="cannot both be set"):
        create_embed_fn(
            "openai:embedding",
            foundry_url="https://foundry.local",
            base_url="http://embed.local/v1",
        )


def test_create_embed_fn_no_foundry_cohere(monkeypatch):
    monkeypatch.setenv("CO_API_KEY", "test-key")
    fn = create_embed_fn("cohere:embed-v4.0", foundry_url=None)
    assert callable(fn)


@patch("second_brain.providers._get_token_provider")
def test_create_embed_fn_cohere_foundry(mock_token):
    mock_token.return_value = lambda: "fake-token"
    fn = create_embed_fn(
        "cohere:embed-v4.0",
        foundry_url="https://my.cognitiveservices.azure.com",
        auth="aad",
    )
    assert callable(fn)


def test_create_embed_fn_foundry_key_explicit():
    fn = create_embed_fn(
        "cohere:embed-v4.0",
        foundry_url="https://my.cognitiveservices.azure.com",
        auth="key",
        key="my-explicit-key",
    )
    assert callable(fn)


def test_create_embed_fn_foundry_key_default_env(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-default-key")
    fn = create_embed_fn(
        "openai:text-embedding-3-small",
        foundry_url="https://my.azure.com",
        auth="key",
    )
    assert callable(fn)


def test_create_model_foundry_openai_key_auth():
    from pydantic_ai.models.openai import OpenAIChatModel

    result = create_model(
        "openai:gpt-4o-mini",
        foundry_url="https://my.azure.com",
        auth="key",
        key="test-key",
    )
    assert isinstance(result, OpenAIChatModel)


def test_create_model_foundry_openai_key_default_env(monkeypatch):
    from pydantic_ai.models.openai import OpenAIChatModel

    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-default-key")
    result = create_model(
        "openai:gpt-4o-mini",
        foundry_url="https://my.azure.com",
        auth="key",
    )
    assert isinstance(result, OpenAIChatModel)


def test_create_model_foundry_anthropic_key_auth():
    from pydantic_ai.models.anthropic import AnthropicModel

    result = create_model(
        "anthropic:claude-sonnet-4-5",
        foundry_url="https://my.azure.com",
        auth="key",
        key="test-key",
    )
    assert isinstance(result, AnthropicModel)


def test_create_embed_fn_foundry_key_auth():
    fn = create_embed_fn(
        "openai:text-embedding-3-small",
        foundry_url="https://my.azure.com",
        auth="key",
        key="test-key",
    )
    assert callable(fn)


def test_create_embed_fn_dimensions_passed_to_embedder(monkeypatch):
    """Dimensions parameter is forwarded to the Embedder settings."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fn = create_embed_fn(
        "openai:text-embedding-3-small",
        foundry_url=None,
        dimensions=1024,
    )
    assert callable(fn)


def test_create_embed_fn_dimensions_foundry():
    """Dimensions parameter works with Foundry embedder too."""
    fn = create_embed_fn(
        "cohere:embed-v4.0",
        foundry_url="https://my.cognitiveservices.azure.com",
        auth="key",
        key="test-key",
        dimensions=1024,
    )
    assert callable(fn)
