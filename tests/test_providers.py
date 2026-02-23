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


@patch("second_brain.providers._get_token_provider")
def test_create_model_foundry_openai(mock_token):
    from pydantic_ai.models.openai import OpenAIChatModel

    mock_token.return_value = lambda: "fake-token"
    result = create_model("openai:gpt-4o-mini", foundry_url="https://my.azure.com")
    assert isinstance(result, OpenAIChatModel)


@patch("second_brain.providers._get_token_provider")
def test_create_model_foundry_anthropic(mock_token):
    from pydantic_ai.models.anthropic import AnthropicModel

    mock_token.return_value = lambda: "fake-token"
    result = create_model(
        "anthropic:claude-sonnet-4-5", foundry_url="https://my.azure.com"
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
        "openai:text-embedding-3-small", foundry_url="https://my.azure.com"
    )
    assert callable(fn)


def test_create_embed_fn_no_foundry_cohere(monkeypatch):
    monkeypatch.setenv("CO_API_KEY", "test-key")
    fn = create_embed_fn("cohere:embed-v4.0", foundry_url=None)
    assert callable(fn)


def test_create_embed_fn_anthropic_raises_foundry():
    with pytest.raises(ValueError, match=r"[Ff]oundry.*openai"):
        create_embed_fn(
            "anthropic:claude-sonnet-4-5", foundry_url="https://my.azure.com"
        )
