from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any, Literal


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


def _create_openai_foundry_model(
    model_name: str, foundry_url: str, auth: Literal["key", "aad"]
) -> Any:
    from openai import AsyncAzureOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    if auth == "aad":
        client = AsyncAzureOpenAI(
            azure_endpoint=foundry_url,
            azure_ad_token_provider=_get_token_provider(),
            api_version=_AZURE_API_VERSION,
        )
    else:
        client = AsyncAzureOpenAI(
            azure_endpoint=foundry_url,
            api_key=os.environ["OPENAI_API_KEY"],
            api_version=_AZURE_API_VERSION,
        )
    return OpenAIChatModel(model_name, provider=OpenAIProvider(openai_client=client))


def _create_anthropic_foundry_model(
    model_name: str, foundry_url: str, auth: Literal["key", "aad"]
) -> Any:
    from anthropic import AsyncAnthropicFoundry
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    if auth == "aad":
        client = AsyncAnthropicFoundry(
            base_url=f"{foundry_url.rstrip('/')}/anthropic/v1/",
            azure_ad_token_provider=_get_token_provider(),
        )
    else:
        client = AsyncAnthropicFoundry(
            base_url=f"{foundry_url.rstrip('/')}/anthropic/v1/",
            api_key=os.environ["ANTHROPIC_API_KEY"],
        )
    return AnthropicModel(
        model_name, provider=AnthropicProvider(anthropic_client=client)
    )


_AZURE_API_VERSION = "2024-07-01-preview"

_FOUNDRY_BUILDERS: dict[str, Callable[..., Any]] = {
    "openai": _create_openai_foundry_model,
    "anthropic": _create_anthropic_foundry_model,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_model(
    model_string: str, foundry_url: str | None, auth: Literal["key", "aad"] = "key"
) -> Any:
    """Create a pydantic-ai model from a provider:model_name string.

    When *foundry_url* is ``None`` the raw string is returned (pydantic-ai
    resolves it via its built-in provider registry).  When a Foundry URL is
    supplied, an authenticated Azure client is constructed and wrapped in the
    appropriate pydantic-ai model class.

    *auth* selects the authentication strategy when talking to Foundry:
    ``"aad"`` uses ``DefaultAzureCredential``; ``"key"`` (default) reads the
    provider's API-key from the environment.
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
    return builder(model_name, foundry_url, auth)


def create_embed_fn(
    model_string: str, foundry_url: str | None, auth: Literal["key", "aad"] = "key"
) -> Callable[[str], Awaitable[list[float]]]:
    """Create an async embedding function from a provider:model_name string.

    Returns an ``async def embed(text: str) -> list[float]`` callable.

    When *foundry_url* is ``None`` the raw model string is handed to
    :class:`pydantic_ai.Embedder` which resolves it via its built-in
    provider registry (openai, cohere, google-gla, voyageai, …).

    When a Foundry URL is supplied only ``openai:`` models are accepted
    because Azure Foundry only exposes OpenAI embeddings via the unified
    endpoint.  *auth* selects the authentication strategy: ``"aad"`` uses
    ``DefaultAzureCredential``; ``"key"`` (default) reads ``OPENAI_API_KEY``
    from the environment.
    """
    from pydantic_ai import Embedder

    if foundry_url is None:
        embedder = Embedder(model_string)
    else:
        from openai import AsyncAzureOpenAI
        from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
        from pydantic_ai.providers.openai import OpenAIProvider

        provider_prefix, model_name = _parse_model_string(model_string)
        if provider_prefix != "openai":
            raise ValueError(
                f"Foundry embeddings only support 'openai:' prefix, got '{provider_prefix}:'."
            )

        if auth == "aad":
            client = AsyncAzureOpenAI(
                azure_endpoint=foundry_url,
                azure_ad_token_provider=_get_token_provider(),
                api_version=_AZURE_API_VERSION,
            )
        else:
            client = AsyncAzureOpenAI(
                azure_endpoint=foundry_url,
                api_key=os.environ["OPENAI_API_KEY"],
                api_version=_AZURE_API_VERSION,
            )
        embedding_model = OpenAIEmbeddingModel(
            model_name, provider=OpenAIProvider(openai_client=client)
        )
        embedder = Embedder(embedding_model)

    async def embed(text: str) -> list[float]:
        result = await embedder.embed_query(text)
        return list(result[0])

    return embed
