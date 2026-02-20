from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _parse_model_string(model_string: str) -> tuple[str, str]:
    """Split 'provider:model_name' into (provider, model_name)."""
    if ":" not in model_string:
        raise ValueError(
            f"Model string must be 'provider:model_name' format, got '{model_string}'"
        )
    provider, _, name = model_string.partition(":")
    return provider, name


# ---------------------------------------------------------------------------
# Azure Foundry token provider (lazy singleton)
# ---------------------------------------------------------------------------

_token_provider: Callable[[], str] | None = None


def _get_token_provider() -> Callable[[], str]:
    """Return a cached bearer-token provider for Azure Foundry."""
    global _token_provider
    if _token_provider is None:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        credential = DefaultAzureCredential()
        _token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
    return _token_provider


# ---------------------------------------------------------------------------
# Foundry model builders
# ---------------------------------------------------------------------------


def _create_openai_foundry_model(model_name: str, foundry_url: str) -> Any:
    from openai import AsyncAzureOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    client = AsyncAzureOpenAI(
        azure_endpoint=foundry_url,
        azure_ad_token_provider=_get_token_provider(),
        api_version="2024-07-01-preview",
    )
    return OpenAIChatModel(model_name, provider=OpenAIProvider(openai_client=client))


def _create_anthropic_foundry_model(model_name: str, foundry_url: str) -> Any:
    from anthropic import AsyncAnthropicFoundry
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    client = AsyncAnthropicFoundry(
        base_url=f"{foundry_url.rstrip('/')}/anthropic/v1/",
        azure_ad_token_provider=_get_token_provider(),
    )
    return AnthropicModel(
        model_name, provider=AnthropicProvider(anthropic_client=client)
    )


_FOUNDRY_BUILDERS: dict[str, Callable[..., Any]] = {
    "openai": _create_openai_foundry_model,
    "anthropic": _create_anthropic_foundry_model,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_model(model_string: str, foundry_url: str | None) -> Any:
    """Create a pydantic-ai model from a provider:model_name string.

    When *foundry_url* is ``None`` the raw string is returned (pydantic-ai
    resolves it via its built-in provider registry).  When a Foundry URL is
    supplied, an authenticated Azure client is constructed and wrapped in the
    appropriate pydantic-ai model class.
    """
    if foundry_url is None:
        return model_string

    provider_prefix, model_name = _parse_model_string(model_string)
    builder = _FOUNDRY_BUILDERS.get(provider_prefix)
    if builder is None:
        supported = ", ".join(sorted(_FOUNDRY_BUILDERS))
        raise ValueError(
            f"Unsupported Foundry provider '{provider_prefix}'. Supported: {supported}"
        )
    return builder(model_name, foundry_url)
