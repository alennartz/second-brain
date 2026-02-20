# Azure Foundry Multi-Provider Support

## Problem

The app currently hardcodes OpenAI direct API access for both reasoning (via PydanticAI model strings) and embeddings (via raw httpx calls to api.openai.com). We need to support Azure AI Foundry with `DefaultAzureCredential` for both OpenAI and Anthropic models, while preserving the ability to use any PydanticAI-supported provider with zero custom code.

## Approach: String passthrough + Foundry escape hatch

`BRAIN_REASONING_MODEL` remains a PydanticAI model string (e.g. `openai:gpt-4o-mini`, `anthropic:claude-sonnet-4-5`). When no Foundry config is present, the string passes through directly to PydanticAI — all built-in providers work for free. When `BRAIN_FOUNDRY_URL` is set, a factory function intercepts the model string, parses the provider prefix, and constructs the appropriate Foundry client with `DefaultAzureCredential`.

## Configuration

Add one new setting to `config.py`:

```python
foundry_url: str | None = None  # env: BRAIN_FOUNDRY_URL
```

When `BRAIN_FOUNDRY_URL` is not set: model strings pass through to PydanticAI unchanged. All PydanticAI env vars work (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AZURE_OPENAI_API_KEY`, etc.).

When `BRAIN_FOUNDRY_URL` is set (e.g. `https://my-resource.services.ai.azure.com`): the factory parses model strings and constructs Foundry clients with `DefaultAzureCredential`. The URL is used as-is (supports proxies, private endpoints, custom domains).

## Provider factory (`providers.py`)

New file `src/second_brain/providers.py` with two functions:

### `create_model(model_string, foundry_url) -> str | Model`

- `foundry_url` is None: return string as-is (PydanticAI resolves it)
- `foundry_url` is set: parse `provider:name` from string, then:
  - `openai:*` -> `AsyncAzureOpenAI(azure_endpoint=foundry_url, azure_ad_token_provider=..., api_version="2024-07-01-preview")` wrapped in `OpenAIChatModel(name, provider=OpenAIProvider(openai_client=client))`
  - `anthropic:*` -> `AsyncAnthropicFoundry(base_url=f"{foundry_url}/anthropic/v1/messages", azure_ad_token_provider=...)` wrapped in `AnthropicModel(name, provider=AnthropicProvider(anthropic_client=client))`
  - Other prefix -> `ValueError` with clear message

### `create_embed_fn(model_string, foundry_url) -> Callable[[str], Awaitable[list[float]]]`

- `foundry_url` is None: use PydanticAI `Embedder` with `OpenAIEmbeddingModel` (relies on `OPENAI_API_KEY`)
- `foundry_url` is set: build `AsyncAzureOpenAI` with `DefaultAzureCredential`, use `OpenAIEmbeddingModel(name, provider=OpenAIProvider(openai_client=client))`
- `anthropic:` prefix on embeddings -> `ValueError` (Anthropic has no embedding models)

Both functions share a lazy singleton `DefaultAzureCredential` + token provider (created on first call, module-level).

## Integration (app.py)

The lifespan non-test branch changes from:

```python
_model = settings.reasoning_model
_embed = embed_text
```

To:

```python
from second_brain.providers import create_model, create_embed_fn

_model = create_model(settings.reasoning_model, settings.foundry_url)
_embed = create_embed_fn(settings.embedding_model, settings.foundry_url)
```

Everything else stays identical. `agent.run(model=_model)` accepts both strings and Model objects. `embed_fn` in deps is already typed as a callable.

## File changes

| File | Change |
|---|---|
| `config.py` | Add `foundry_url: str \| None = None` |
| `providers.py` | New: `create_model()`, `create_embed_fn()`, lazy credential singleton |
| `app.py` | Lifespan non-test branch calls factory. Remove `embed_text` import |
| `embedding.py` | Delete `_get_embedding`, `embed_text`, `_embed_fn`. Move `init_vector_indexes` to `db.py` |
| `db.py` | Absorb `init_vector_indexes` from `embedding.py` |
| `converse.py` | Type `model_setting` as `str \| Any` to accept Model objects |
| `pyproject.toml` | `uv add azure-identity anthropic` (resolve latest versions) |
| `.env.example` | Add commented `BRAIN_FOUNDRY_URL=` with documentation |
| `tests/test_providers.py` | New: unit tests for factory functions |
| `CLAUDE.md` | Update env vars documentation |

## Dependencies

- `azure-identity` — `DefaultAzureCredential`, `get_bearer_token_provider` (new)
- `anthropic` — `AsyncAnthropicFoundry` (already transitive via pydantic-ai, made explicit)

Added via `uv add` to resolve latest versions.

## Error handling

- Model string missing `:` separator -> `ValueError` with format hint
- Unsupported Foundry prefix (e.g. `groq:`) -> `ValueError` listing supported prefixes
- `anthropic:` prefix for embeddings -> `ValueError` explaining Anthropic has no embedding API
- `DefaultAzureCredential` failure -> Azure SDK's `CredentialUnavailableError` surfaces naturally at startup

## Testing

The test path (`settings.test_mode = True`) bypasses the factory entirely (uses `TestModel()` and dummy embed). New `tests/test_providers.py` covers:

- Non-foundry: string passthrough
- Foundry + `openai:` prefix: returns `OpenAIChatModel`
- Foundry + `anthropic:` prefix: returns `AnthropicModel`
- Foundry + unsupported prefix: raises `ValueError`
- Embed function returns callable in both paths
- `DefaultAzureCredential` and token provider mocked in all Foundry tests
