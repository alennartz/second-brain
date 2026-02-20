import pytest

from second_brain.providers import _parse_model_string, create_model


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
