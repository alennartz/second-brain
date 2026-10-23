from __future__ import annotations

import logging
import warnings
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from second_brain.config import ReasoningEffort

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


def _openai_model_settings(
    reasoning_effort: ReasoningEffort | None,
    extra_body: dict[str, object] | None = None,
    temperature: float | None = None,
) -> Any:
    from pydantic_ai.models.openai import OpenAIChatModelSettings

    settings: dict[str, Any] = {}
    if reasoning_effort is not None:
        settings["openai_reasoning_effort"] = reasoning_effort
    if temperature is not None:
        settings["temperature"] = temperature
    if extra_body is not None:
        settings["extra_body"] = extra_body
    return OpenAIChatModelSettings(**settings) if settings else None


def _create_openai_foundry_model(
    model_name: str,
    foundry_url: str,
    auth: Literal["key", "aad"],
    key: str | None = None,
    reasoning_effort: ReasoningEffort | None = None,
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
    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(openai_client=client),
        settings=_openai_model_settings(reasoning_effort),
    )


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
    base_url: str | None = None,
    reasoning_effort: ReasoningEffort | None = None,
    chat_template_kwargs: dict[str, object] | None = None,
    temperature: float | None = None,
) -> Any:
    """Create a pydantic-ai model from a provider:model_name string.

    When *base_url* is set, an OpenAI-compatible client uses that endpoint and
    *key* (or the placeholder ``"none"``). This mode supports ``openai:`` model
    strings only and cannot be combined with *foundry_url*. With both URLs
    unset, a missing *reasoning_effort* leaves provider resolution to PydanticAI.
    If effort is set, this function builds an OpenAI model with that default.
    A Foundry URL constructs an authenticated Azure client.

    *auth* selects the authentication strategy when talking to Foundry:
    ``"aad"`` uses ``DefaultAzureCredential``; ``"key"`` (default) uses
    *key* when provided, otherwise the SDK reads its own default env var
    (``AZURE_OPENAI_API_KEY`` for OpenAI, ``ANTHROPIC_API_KEY`` for
    Anthropic). *reasoning_effort* sets the OpenAI ``reasoning_effort`` request
    parameter and is valid only for OpenAI models. *chat_template_kwargs* is
    sent as request ``extra_body`` for self-hosted servers (SGLang) and is
    ignored elsewhere.
    """
    if base_url is not None:
        if foundry_url is not None:
            raise ValueError("base_url and foundry_url cannot both be set")
        provider_prefix, model_name = _parse_model_string(model_string)
        if provider_prefix != "openai":
            raise ValueError("OpenAI-compatible base_url requires an openai: model")
        from openai import AsyncOpenAI
        from openai.types.chat import ChatCompletion
        from pydantic_ai.models.openai import OpenAIChatModel, _ChatCompletion
        from pydantic_ai.providers.openai import OpenAIProvider

        class TolerantOpenAIChatModel(OpenAIChatModel):
            """Tolerates non-standard metadata from self-hosted servers.

            SGLang reports ``metadata.weight_versions`` as a list, while the
            OpenAI types declare ``metadata: dict[str, str]``. Malformed
            metadata is dropped before validation.
            """

            def _validate_completion(self, response: ChatCompletion) -> Any:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    dump = response.model_dump()
                metadata = dump.get("metadata")
                if metadata is not None and not (
                    isinstance(metadata, dict)
                    and all(isinstance(v, str) for v in metadata.values())
                ):
                    dump["metadata"] = None
                return _ChatCompletion.model_validate(dump)

        client = AsyncOpenAI(base_url=base_url, api_key=key or "none")
        return TolerantOpenAIChatModel(
            model_name,
            provider=OpenAIProvider(openai_client=client),
            settings=_openai_model_settings(
                reasoning_effort,
                extra_body=(
                    {"chat_template_kwargs": chat_template_kwargs}
                    if chat_template_kwargs is not None
                    else None
                ),
                temperature=temperature,
            ),
        )

    if foundry_url is None:
        if reasoning_effort is None:
            return model_string
        provider_prefix, model_name = _parse_model_string(model_string)
        if provider_prefix != "openai":
            raise ValueError("reasoning_effort requires an openai: model")
        from pydantic_ai.models.openai import OpenAIChatModel

        return OpenAIChatModel(
            model_name, settings=_openai_model_settings(reasoning_effort)
        )

    provider_prefix, model_name = _parse_model_string(model_string)
    builder = _FOUNDRY_BUILDERS.get(provider_prefix)
    if builder is None:
        supported = ", ".join(sorted(_FOUNDRY_BUILDERS))
        raise ValueError(
            f"Unsupported Foundry provider '{provider_prefix}'. Supported: {supported}"
        )
    if reasoning_effort is not None:
        if provider_prefix != "openai":
            raise ValueError("reasoning_effort requires an openai: model")
        return _create_openai_foundry_model(
            model_name, foundry_url, auth, key, reasoning_effort
        )
    return builder(model_name, foundry_url, auth, key)


def create_embed_fn(
    model_string: str,
    foundry_url: str | None,
    auth: Literal["key", "aad"] = "key",
    key: str | None = None,
    dimensions: int | None = None,
    base_url: str | None = None,
) -> Callable[[str], Awaitable[list[float]]]:
    """Create an async embedding function from a provider:model_name string.

    Returns an ``async def embed(text: str) -> list[float]`` callable.

    When *base_url* is set, an OpenAI-compatible client uses that endpoint and
    *key* (or the placeholder ``"none"``). This mode supports ``openai:`` model
    strings only and cannot be combined with *foundry_url*. When both URLs are
    ``None``, PydanticAI resolves the raw model string through its built-in
    provider registry.

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

    if base_url is not None and foundry_url is not None:
        raise ValueError("base_url and foundry_url cannot both be set")

    if base_url is not None:
        provider_prefix, model_name = _parse_model_string(model_string)
        if provider_prefix != "openai":
            raise ValueError("OpenAI-compatible base_url requires an openai: model")
        from openai import AsyncOpenAI
        from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
        from pydantic_ai.providers.openai import OpenAIProvider

        client = AsyncOpenAI(base_url=base_url, api_key=key or "none")
        embedding_model = OpenAIEmbeddingModel(
            model_name, provider=OpenAIProvider(openai_client=client)
        )
        embedder = Embedder(embedding_model, settings=embed_settings)
    elif foundry_url is None:
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
