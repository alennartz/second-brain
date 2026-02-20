# Azure Foundry Multi-Provider Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Support Azure AI Foundry with DefaultAzureCredential for both OpenAI and Anthropic models, while keeping all existing PydanticAI string-based providers working unchanged.

**Architecture:** A factory module (`providers.py`) intercepts model strings when `BRAIN_FOUNDRY_URL` is set, constructing Foundry-authenticated clients with `DefaultAzureCredential`. When unset, strings pass through to PydanticAI as-is. Embedding code migrates from raw httpx to PydanticAI `Embedder`, sharing the same provider logic.

**Tech Stack:** PydanticAI (models + embeddings), azure-identity (DefaultAzureCredential), anthropic SDK (AsyncAnthropicFoundry), openai SDK (AsyncAzureOpenAI)

**Design doc:** `docs/plans/2026-02-20-azure-foundry-design.md`

---

### Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add azure-identity and anthropic via uv**

Run:
```bash
uv add azure-identity anthropic
```

This resolves latest versions automatically and updates `pyproject.toml` + `uv.lock`.

**Step 2: Sync to verify**

Run: `uv sync --all-extras`
Expected: Clean install, no errors.

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add azure-identity and anthropic"
```

---

### Task 2: Add `foundry_url` to config

**Files:**
- Modify: `src/second_brain/config.py:4-9`
- Modify: `tests/test_config.py`

**Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_foundry_url_default_none():
    """foundry_url should default to None when BRAIN_FOUNDRY_URL is unset."""
    from second_brain.config import Settings

    s = Settings(
        _env_file=None,  # don't read .env
        db_path="data/brain.db",
    )
    assert s.foundry_url is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest -v tests/test_config.py::test_foundry_url_default_none`
Expected: FAIL — `Settings` has no field `foundry_url`.

**Step 3: Add the field**

In `src/second_brain/config.py`, add after line 9 (`test_mode: bool = False`):

```python
    foundry_url: str | None = None
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest -v tests/test_config.py::test_foundry_url_default_none`
Expected: PASS

**Step 5: Commit**

```bash
git add src/second_brain/config.py tests/test_config.py
git commit -m "feat: add BRAIN_FOUNDRY_URL config setting"
```

---

### Task 3: Create `providers.py` — `_parse_model_string` helper

**Files:**
- Create: `src/second_brain/providers.py`
- Create: `tests/test_providers.py`

**Step 1: Write the failing tests**

Create `tests/test_providers.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest -v tests/test_providers.py`
Expected: FAIL — module `second_brain.providers` does not exist.

**Step 3: Implement the helper**

Create `src/second_brain/providers.py`:

```python
from __future__ import annotations


def _parse_model_string(model_string: str) -> tuple[str, str]:
    """Split 'provider:model_name' into (provider, model_name)."""
    if ":" not in model_string:
        raise ValueError(
            f"Model string must be 'provider:model_name' format, got '{model_string}'"
        )
    provider, _, name = model_string.partition(":")
    return provider, name
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest -v tests/test_providers.py`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add src/second_brain/providers.py tests/test_providers.py
git commit -m "feat(providers): add model string parser"
```

---

### Task 4: Create `providers.py` — `create_model` (non-Foundry path)

**Files:**
- Modify: `src/second_brain/providers.py`
- Modify: `tests/test_providers.py`

**Step 1: Write the failing test**

Add to `tests/test_providers.py`:

```python
from second_brain.providers import create_model


def test_create_model_no_foundry_returns_string():
    """Without foundry_url, model string passes through unchanged."""
    result = create_model("openai:gpt-4o-mini", foundry_url=None)
    assert result == "openai:gpt-4o-mini"


def test_create_model_no_foundry_any_provider():
    """Any PydanticAI model string passes through."""
    result = create_model("groq:llama-3.3-70b-versatile", foundry_url=None)
    assert result == "groq:llama-3.3-70b-versatile"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest -v tests/test_providers.py::test_create_model_no_foundry_returns_string`
Expected: FAIL — `create_model` not found.

**Step 3: Implement non-Foundry path**

Add to `src/second_brain/providers.py`:

```python
from typing import Any


def create_model(model_string: str, foundry_url: str | None) -> Any:
    """Build a PydanticAI-compatible model from a model string.

    When foundry_url is None, returns the string as-is for PydanticAI to resolve.
    When foundry_url is set, constructs a Foundry-authenticated model object.
    """
    if foundry_url is None:
        return model_string

    raise NotImplementedError("Foundry path not yet implemented")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest -v tests/test_providers.py`
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add src/second_brain/providers.py tests/test_providers.py
git commit -m "feat(providers): create_model passthrough for non-Foundry"
```

---

### Task 5: Create `providers.py` — `create_model` (Foundry path)

**Files:**
- Modify: `src/second_brain/providers.py`
- Modify: `tests/test_providers.py`

**Step 1: Write the failing tests**

Add to `tests/test_providers.py`:

```python
from unittest.mock import MagicMock, patch

from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel


@patch("second_brain.providers._get_token_provider")
def test_create_model_foundry_openai(mock_token):
    mock_token.return_value = lambda: "fake-token"
    result = create_model("openai:gpt-4o-mini", foundry_url="https://my.azure.com")
    assert isinstance(result, OpenAIChatModel)


@patch("second_brain.providers._get_token_provider")
def test_create_model_foundry_anthropic(mock_token):
    mock_token.return_value = lambda: "fake-token"
    result = create_model(
        "anthropic:claude-sonnet-4-5", foundry_url="https://my.azure.com"
    )
    assert isinstance(result, AnthropicModel)


def test_create_model_foundry_unsupported_prefix():
    with pytest.raises(ValueError, match="openai.*anthropic"):
        create_model("groq:llama-3.3-70b", foundry_url="https://my.azure.com")
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest -v tests/test_providers.py::test_create_model_foundry_openai`
Expected: FAIL — `NotImplementedError` or `_get_token_provider` not found.

**Step 3: Implement Foundry path**

Replace the full `src/second_brain/providers.py` with:

```python
from __future__ import annotations

from typing import Any

_token_provider: Any = None


def _get_token_provider() -> Any:
    """Lazy singleton: build DefaultAzureCredential + token provider on first call."""
    global _token_provider
    if _token_provider is None:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        credential = DefaultAzureCredential()
        _token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
    return _token_provider


def _parse_model_string(model_string: str) -> tuple[str, str]:
    """Split 'provider:model_name' into (provider, model_name)."""
    if ":" not in model_string:
        raise ValueError(
            f"Model string must be 'provider:model_name' format, got '{model_string}'"
        )
    provider, _, name = model_string.partition(":")
    return provider, name


def _create_openai_foundry_model(model_name: str, foundry_url: str) -> Any:
    """Build an OpenAIChatModel backed by AsyncAzureOpenAI with Foundry auth."""
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
    """Build an AnthropicModel backed by AsyncAnthropicFoundry with Foundry auth."""
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


_FOUNDRY_BUILDERS: dict[str, Any] = {
    "openai": _create_openai_foundry_model,
    "anthropic": _create_anthropic_foundry_model,
}


def create_model(model_string: str, foundry_url: str | None) -> Any:
    """Build a PydanticAI-compatible model from a model string.

    When foundry_url is None, returns the string as-is for PydanticAI to resolve.
    When foundry_url is set, constructs a Foundry-authenticated model object.
    """
    if foundry_url is None:
        return model_string

    provider, name = _parse_model_string(model_string)
    builder = _FOUNDRY_BUILDERS.get(provider)
    if builder is None:
        supported = ", ".join(sorted(_FOUNDRY_BUILDERS.keys()))
        raise ValueError(
            f"Foundry mode supports '{supported}' prefixes, got '{provider}:'"
        )
    return builder(name, foundry_url)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest -v tests/test_providers.py`
Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add src/second_brain/providers.py tests/test_providers.py
git commit -m "feat(providers): create_model with Foundry auth support"
```

---

### Task 6: Create `providers.py` — `create_embed_fn`

**Files:**
- Modify: `src/second_brain/providers.py`
- Modify: `tests/test_providers.py`

**Step 1: Write the failing tests**

Add to `tests/test_providers.py`:

```python
import asyncio

from second_brain.providers import create_embed_fn


@patch("second_brain.providers._get_token_provider")
def test_create_embed_fn_no_foundry(mock_token):
    """Non-Foundry path returns a callable."""
    fn = create_embed_fn("openai:text-embedding-3-small", foundry_url=None)
    assert callable(fn)


@patch("second_brain.providers._get_token_provider")
def test_create_embed_fn_foundry(mock_token):
    """Foundry path returns a callable."""
    mock_token.return_value = lambda: "fake-token"
    fn = create_embed_fn(
        "openai:text-embedding-3-small", foundry_url="https://my.azure.com"
    )
    assert callable(fn)


def test_create_embed_fn_anthropic_raises():
    """Anthropic doesn't have embeddings — should raise."""
    with pytest.raises(ValueError, match="[Ee]mbedding"):
        create_embed_fn(
            "anthropic:claude-sonnet-4-5", foundry_url="https://my.azure.com"
        )
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest -v tests/test_providers.py::test_create_embed_fn_no_foundry`
Expected: FAIL — `create_embed_fn` not found.

**Step 3: Implement `create_embed_fn`**

Add to `src/second_brain/providers.py`:

```python
from collections.abc import Awaitable, Callable


def create_embed_fn(
    model_string: str, foundry_url: str | None
) -> Callable[[str], Awaitable[list[float]]]:
    """Build an async text->vector callable.

    Non-foundry: uses PydanticAI Embedder with provider inferred from string prefix.
    Foundry: uses AsyncAzureOpenAI with DefaultAzureCredential.
    """
    from pydantic_ai import Embedder
    from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel

    provider_prefix, model_name = _parse_model_string(model_string)

    if foundry_url is not None and provider_prefix != "openai":
        raise ValueError(
            f"Foundry embeddings only support 'openai:' prefix, got '{provider_prefix}:'. "
            "Anthropic does not offer an embeddings API."
        )

    if foundry_url is None:
        embedding_model = OpenAIEmbeddingModel(model_name, provider=provider_prefix)
    else:
        from openai import AsyncAzureOpenAI

        from pydantic_ai.providers.openai import OpenAIProvider

        client = AsyncAzureOpenAI(
            azure_endpoint=foundry_url,
            azure_ad_token_provider=_get_token_provider(),
            api_version="2024-07-01-preview",
        )
        embedding_model = OpenAIEmbeddingModel(
            model_name, provider=OpenAIProvider(openai_client=client)
        )

    embedder = Embedder(embedding_model)

    async def embed(text: str) -> list[float]:
        result = await embedder.embed(text)
        return result[0]

    return embed
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest -v tests/test_providers.py`
Expected: PASS (11 tests)

**Step 5: Commit**

```bash
git add src/second_brain/providers.py tests/test_providers.py
git commit -m "feat(providers): create_embed_fn with Foundry and passthrough support"
```

---

### Task 7: Move `init_vector_indexes` from `embedding.py` to `db.py`

**Files:**
- Modify: `src/second_brain/db.py:1-50`
- Modify: `src/second_brain/embedding.py` (delete entire file after move)
- Modify: `src/second_brain/app.py:16`
- Modify: `tests/test_embedding.py`
- Modify: `tests/test_recall_tools.py:4`

**Step 1: Move function into `db.py`**

Add to the end of `src/second_brain/db.py` (after `init_schema`):

```python
async def init_vector_indexes(db: AsyncSurreal, dimensions: int | None = None) -> None:  # pyright: ignore[reportGeneralTypeIssues]
    """Define HNSW vector indexes. Idempotent."""
    dim = dimensions or settings.embedding_dimensions
    await db.query(f"""
        DEFINE INDEX IF NOT EXISTS note_embedding_hnsw ON note
            FIELDS embedding HNSW DIMENSION {dim} DIST COSINE;
        DEFINE INDEX IF NOT EXISTS entity_embedding_hnsw ON entity
            FIELDS embedding HNSW DIMENSION {dim} DIST COSINE;
    """)
```

Note: `db.py` already imports `from second_brain.config import settings`.

**Step 2: Update all imports**

In `src/second_brain/app.py`, change line 16 from:
```python
from second_brain.embedding import embed_text, init_vector_indexes
```
to:
```python
from second_brain.db import init_vector_indexes
```

(The `embed_text` import is no longer needed — it will be replaced by the factory in the next task.)

In `tests/test_recall_tools.py`, change line 4 from:
```python
from second_brain.embedding import init_vector_indexes
```
to:
```python
from second_brain.db import init_vector_indexes
```

In `tests/test_embedding.py`, change line 3 from:
```python
from second_brain.embedding import embed_text, init_vector_indexes
```
to:
```python
from second_brain.db import init_vector_indexes
```

Also remove the `test_embed_text_returns_vector` test from `tests/test_embedding.py` since `embed_text` no longer exists. The embed logic is now in `providers.py` and tested in `test_providers.py`. The file should only contain `test_init_vector_indexes`:

```python
from second_brain.db import init_schema, init_vector_indexes


async def test_init_vector_indexes(db):
    await init_schema(db)
    await init_vector_indexes(db, dimensions=3)

    # Should not raise on second call
    await init_vector_indexes(db, dimensions=3)
```

**Step 3: Delete `embedding.py`**

Delete `src/second_brain/embedding.py` entirely.

**Step 4: Run all tests to verify nothing broke**

Run: `uv run pytest -v`
Expected: All existing tests pass (the app tests mock `run_*_agent` so they don't touch embedding at all).

**Step 5: Commit**

```bash
git add src/second_brain/db.py src/second_brain/app.py tests/test_embedding.py tests/test_recall_tools.py
git rm src/second_brain/embedding.py
git commit -m "refactor: move init_vector_indexes to db.py, delete embedding.py"
```

---

### Task 8: Wire providers into `app.py` lifespan

**Files:**
- Modify: `src/second_brain/app.py:37-56`

**Step 1: Update the lifespan non-test branch**

In `src/second_brain/app.py`, replace lines 46-49:

```python
    else:
        _db = AsyncSurreal(f"surrealkv://{settings.db_path}")
        _model = settings.reasoning_model
        _embed = embed_text
```

With:

```python
    else:
        from second_brain.providers import create_embed_fn, create_model

        _db = AsyncSurreal(f"surrealkv://{settings.db_path}")
        _model = create_model(settings.reasoning_model, settings.foundry_url)
        _embed = create_embed_fn(settings.embedding_model, settings.foundry_url)
```

**Step 2: Run all tests**

Run: `uv run pytest -v`
Expected: All tests pass. The test path doesn't hit this branch.

**Step 3: Run lint and type check**

Run: `uv run ruff check src/ tests/ && uv run basedpyright src/`
Expected: Clean.

**Step 4: Commit**

```bash
git add src/second_brain/app.py
git commit -m "feat: wire provider factory into app lifespan"
```

---

### Task 9: Update `.env.example` and `CLAUDE.md`

**Files:**
- Modify: `.env.example`
- Modify: `CLAUDE.md`

**Step 1: Update `.env.example`**

Replace contents with:

```
BRAIN_DB_PATH=data/brain.db
BRAIN_REASONING_MODEL=openai:gpt-4o-mini
BRAIN_EMBEDDING_MODEL=openai:text-embedding-3-small
BRAIN_EMBEDDING_DIMENSIONS=1536

# Direct API (when BRAIN_FOUNDRY_URL is not set):
OPENAI_API_KEY=sk-...
# Or for Anthropic direct: ANTHROPIC_API_KEY=sk-ant-...

# Azure Foundry (optional — uncomment to use DefaultAzureCredential):
# BRAIN_FOUNDRY_URL=https://your-resource.services.ai.azure.com
# When set, OPENAI_API_KEY / ANTHROPIC_API_KEY are not needed.
# Auth uses DefaultAzureCredential (Azure CLI, managed identity, etc.)
# Supported model prefixes: openai:, anthropic:
```

**Step 2: Update `CLAUDE.md` Environment section**

In `CLAUDE.md`, replace the Environment section (lines 86-93) with:

```markdown
## Environment

Requires a `.env` file (copy from `.env.example`). Key variables use the `BRAIN_` prefix:
- `BRAIN_DB_PATH` — SurrealDB file path (default: `data/brain.db`)
- `BRAIN_REASONING_MODEL` — LLM for agents (default: `openai:gpt-4o-mini`). Any PydanticAI model string works (e.g. `anthropic:claude-sonnet-4-5`, `groq:llama-3.3-70b`)
- `BRAIN_EMBEDDING_MODEL` — embedding model (default: `openai:text-embedding-3-small`)
- `BRAIN_EMBEDDING_DIMENSIONS` — vector dimensions (default: `1536`)
- `BRAIN_TEST_MODE` — when `true`, uses `TestModel()` and in-memory SurrealDB (no API keys needed)
- `BRAIN_FOUNDRY_URL` — Azure AI Foundry endpoint (optional). When set, uses `DefaultAzureCredential` instead of API keys. Supports `openai:` and `anthropic:` model prefixes.
- `OPENAI_API_KEY` — required when using `openai:` models without Foundry
- `ANTHROPIC_API_KEY` — required when using `anthropic:` models without Foundry
```

Also update the `embedding.py` line in the Key modules section (line 112) to:

```markdown
- **`providers.py`** — Model and embedding factory. When `BRAIN_FOUNDRY_URL` is set, constructs Azure Foundry clients with `DefaultAzureCredential`. Otherwise, model strings pass through to PydanticAI for native resolution.
```

Remove the old `embedding.py` bullet.

**Step 3: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs: update env config for multi-provider Foundry support"
```

---

### Task 10: Final verification

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass.

**Step 2: Run all pre-commit checks**

Run: `uv run pre-commit run --all-files`
Expected: All hooks pass.

**Step 3: Verify non-Foundry startup**

Run: `BRAIN_TEST_MODE=true uv run uvicorn second_brain.app:app --host 0.0.0.0 --port 8000 &`
Then: `curl http://localhost:8000/health`
Expected: `{"status":"ok"}`
Kill the server after.

**Step 4: Commit any fixups if needed, then tag**

```bash
git log --oneline -10  # review commit history
```
