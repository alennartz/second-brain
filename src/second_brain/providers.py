from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal

logger = logging.getLogger(__name__)


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
    model_name: str,
    foundry_url: str,
    auth: Literal["key", "aad"],
    key: str | None = None,
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
        kwargs: dict[str, Any] = {
            "azure_endpoint": foundry_url,
            "api_version": _AZURE_API_VERSION,
        }
        if key is not None:
            kwargs["api_key"] = key
        client = AsyncAzureOpenAI(**kwargs)
    return OpenAIChatModel(model_name, provider=OpenAIProvider(openai_client=client))


def _create_anthropic_foundry_model(
    model_name: str,
    foundry_url: str,
    auth: Literal["key", "aad"],
    key: str | None = None,
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
        kwargs: dict[str, Any] = {
            "base_url": f"{foundry_url.rstrip('/')}/anthropic/v1/",
        }
        if key is not None:
            kwargs["api_key"] = key
        client = AsyncAnthropicFoundry(**kwargs)
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
    model_string: str,
    foundry_url: str | None,
    auth: Literal["key", "aad"] = "key",
    key: str | None = None,
) -> Any:
    """Create a pydantic-ai model from a provider:model_name string.

    When *foundry_url* is ``None`` the raw string is returned (pydantic-ai
    resolves it via its built-in provider registry).  When a Foundry URL is
    supplied, an authenticated Azure client is constructed and wrapped in the
    appropriate pydantic-ai model class.

    *auth* selects the authentication strategy when talking to Foundry:
    ``"aad"`` uses ``DefaultAzureCredential``; ``"key"`` (default) uses
    *key* when provided, otherwise the SDK reads its own default env var
    (``AZURE_OPENAI_API_KEY`` for OpenAI, ``ANTHROPIC_API_KEY`` for
    Anthropic).
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
    return builder(model_name, foundry_url, auth, key)


def create_embed_fn(
    model_string: str,
    foundry_url: str | None,
    auth: Literal["key", "aad"] = "key",
    key: str | None = None,
    dimensions: int | None = None,
) -> Callable[[str], Awaitable[list[float]]]:
    """Create an async embedding function from a provider:model_name string.

    Returns an ``async def embed(text: str) -> list[float]`` callable.

    When *foundry_url* is ``None`` the raw model string is handed to
    :class:`pydantic_ai.Embedder` which resolves it via its built-in
    provider registry (openai, cohere, google-gla, voyageai, …).

    When a Foundry URL is supplied, any model string is accepted because
    Azure AI Services exposes an OpenAI-compatible API for all deployed
    models (including Cohere).  *auth* selects the authentication strategy:
    ``"aad"`` uses ``DefaultAzureCredential``; ``"key"`` (default) uses
    *key* when provided, otherwise the SDK reads ``AZURE_OPENAI_API_KEY``
    from the environment.

    *dimensions* requests a specific output dimensionality from models that
    support it (e.g. ``text-embedding-3-small``, Cohere ``embed-v4``).
    When ``None``, the model's default is used.
    """
    from pydantic_ai import Embedder
    from pydantic_ai.embeddings.settings import EmbeddingSettings

    embed_settings: EmbeddingSettings | None = None
    if dimensions is not None:
        embed_settings = EmbeddingSettings(dimensions=dimensions)

    if foundry_url is None:
        embedder = Embedder(model_string, settings=embed_settings)
    else:
        from openai import AsyncAzureOpenAI
        from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
        from pydantic_ai.providers.openai import OpenAIProvider

        _provider_prefix, model_name = _parse_model_string(model_string)

        if auth == "aad":
            client = AsyncAzureOpenAI(
                azure_endpoint=foundry_url,
                azure_ad_token_provider=_get_token_provider(),
                api_version=_AZURE_API_VERSION,
            )
        else:
            kwargs: dict[str, Any] = {
                "azure_endpoint": foundry_url,
                "api_version": _AZURE_API_VERSION,
            }
            if key is not None:
                kwargs["api_key"] = key
            client = AsyncAzureOpenAI(**kwargs)
        embedding_model = OpenAIEmbeddingModel(
            model_name, provider=OpenAIProvider(openai_client=client)
        )
        embedder = Embedder(embedding_model, settings=embed_settings)

    async def embed(text: str) -> list[float]:
        logger.info(
            "Embedding request (%d chars): '%.60s%s'",
            len(text),
            text,
            "…" if len(text) > 60 else "",
        )
        result = await embedder.embed_query(text)
        if not result or not result[0]:
            raise RuntimeError("Embedding API returned empty result")
        dims = len(result[0])
        logger.info("Embedding response: %d dimensions", dims)
        return list(result[0])

    async def embed_batch(texts: list[str]) -> list[list[float]]:
        """Embed multiple texts, chunked to avoid rate limits."""
        import asyncio

        if not texts:
            return []
        if len(texts) == 1:
            return [await embed(texts[0])]

        chunk_size = 5
        all_vecs: list[list[float]] = []
        for i in range(0, len(texts), chunk_size):
            chunk = texts[i : i + chunk_size]
            logger.info(
                "Embedding batch chunk %d-%d of %d", i + 1, i + len(chunk), len(texts)
            )
            result = await embedder.embed_documents(chunk)
            vecs = result.embeddings
            if len(vecs) != len(chunk):
                raise RuntimeError(
                    f"Embedding batch returned {len(vecs)} "
                    f"results for {len(chunk)} inputs"
                )
            all_vecs.extend(list(v) for v in vecs)
            if i + chunk_size < len(texts):
                await asyncio.sleep(1)  # brief pause between chunks
        logger.info(
            "Embedding batch complete: %d embeddings, %d dims",
            len(all_vecs),
            len(all_vecs[0]),
        )
        return all_vecs

    embed.embed_batch = embed_batch  # type: ignore[attr-defined]
    return embed
