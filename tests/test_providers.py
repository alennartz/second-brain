import pytest

from second_brain.providers import _parse_model_string


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
