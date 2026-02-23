# Decouple Provider Config Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Decouple embedding and reasoning Foundry URLs and auth modes so each can be independently configured as direct/Foundry+AAD/Foundry+key.

**Architecture:** Replace single `BRAIN_FOUNDRY_URL` with per-concern `BRAIN_{REASONING,EMBEDDING}_FOUNDRY_URL` and `BRAIN_{REASONING,EMBEDDING}_AUTH` env vars. Provider factory functions gain an `auth` parameter that selects AAD token or API key auth when constructing Foundry clients.

**Tech Stack:** Python, pydantic-settings, openai SDK, anthropic SDK, pytest

---

### Task 1: Update config.py — remove old field, add new fields

**Files:**
- Modify: `src/second_brain/config.py`

**Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_foundry_url_fields_default_none():
    s = Settings(_env_file=None, db_path="data/brain.db")  # pyright: ignore[reportCallIssue]
    assert s.reasoning_foundry_url is None
    assert s.embedding_foundry_url is None


def test_auth_fields_default_key():
    s = Settings(_env_file=None, db_path="data/brain.db")  # pyright: ignore[reportCallIssue]
    assert s.reasoning_auth == "key"
    assert s.embedding_auth == "key"


def test_foundry_url_from_env(monkeypatch):
    monkeypatch.setenv("BRAIN_REASONING_FOUNDRY_URL", "https://r.azure.com")
    monkeypatch.setenv("BRAIN_EMBEDDING_FOUNDRY_URL", "https://e.azure.com")
    s = Settings(_env_file=None, db_path="data/brain.db")  # pyright: ignore[reportCallIssue]
    assert s.reasoning_foundry_url == "https://r.azure.com"
    assert s.embedding_foundry_url == "https://e.azure.com"


def test_auth_from_env(monkeypatch):
    monkeypatch.setenv("BRAIN_REASONING_AUTH", "aad")
    monkeypatch.setenv("BRAIN_EMBEDDING_AUTH", "aad")
    s = Settings(_env_file=None, db_path="data/brain.db")  # pyright: ignore[reportCallIssue]
    assert s.reasoning_auth == "aad"
    assert s.embedding_auth == "aad"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `reasoning_foundry_url`, `embedding_foundry_url`, `reasoning_auth`, `embedding_auth` don't exist yet.

**Step 3: Update config.py**

In `src/second_brain/config.py`, replace `foundry_url: str | None = None` with:

```python
reasoning_foundry_url: str | None = None
reasoning_auth: str = "key"
embedding_foundry_url: str | None = None
embedding_auth: str = "key"
```

**Step 4: Fix the old test**

In `tests/test_config.py`, remove `test_foundry_url_default_none` (it references the deleted `foundry_url` field).

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: All PASS.

**Step 6: Commit**

```bash
git add src/second_brain/config.py tests/test_config.py
git commit -m "refactor(config): replace foundry_url with per-concern foundry+auth fields"
```

---

### Task 2: Update providers.py — add auth parameter to Foundry builders

**Files:**
- Modify: `src/second_brain/providers.py`
- Modify: `tests/test_providers.py`

**Step 1: Write the failing tests for key-auth Foundry paths**

Add to `tests/test_providers.py`:

```python
def test_create_model_foundry_openai_key_auth(monkeypatch):
    from pydantic_ai.models.openai import OpenAIChatModel

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    result = create_model(
        "openai:gpt-4o-mini", foundry_url="https://my.azure.com", auth="key"
    )
    assert isinstance(result, OpenAIChatModel)


def test_create_model_foundry_anthropic_key_auth(monkeypatch):
    from pydantic_ai.models.anthropic import AnthropicModel

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    result = create_model(
        "anthropic:claude-sonnet-4-5",
        foundry_url="https://my.azure.com",
        auth="key",
    )
    assert isinstance(result, AnthropicModel)


def test_create_embed_fn_foundry_key_auth(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fn = create_embed_fn(
        "openai:text-embedding-3-small",
        foundry_url="https://my.azure.com",
        auth="key",
    )
    assert callable(fn)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_providers.py -v`
Expected: FAIL — `create_model()` and `create_embed_fn()` don't accept `auth` parameter.

**Step 3: Update provider functions**

In `src/second_brain/providers.py`:

1. Change Foundry builder signatures to accept `auth: str`:

```python
def _create_openai_foundry_model(model_name: str, foundry_url: str, auth: str) -> Any:
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
        import os

        client = AsyncAzureOpenAI(
            azure_endpoint=foundry_url,
            api_key=os.environ["OPENAI_API_KEY"],
            api_version=_AZURE_API_VERSION,
        )
    return OpenAIChatModel(model_name, provider=OpenAIProvider(openai_client=client))


def _create_anthropic_foundry_model(model_name: str, foundry_url: str, auth: str) -> Any:
    from anthropic import AsyncAnthropicFoundry
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    if auth == "aad":
        client = AsyncAnthropicFoundry(
            base_url=f"{foundry_url.rstrip('/')}/anthropic/v1/",
            azure_ad_token_provider=_get_token_provider(),
        )
    else:
        import os

        client = AsyncAnthropicFoundry(
            base_url=f"{foundry_url.rstrip('/')}/anthropic/v1/",
            api_key=os.environ["ANTHROPIC_API_KEY"],
        )
    return AnthropicModel(
        model_name, provider=AnthropicProvider(anthropic_client=client)
    )
```

2. Update `create_model` signature and pass `auth` through:

```python
def create_model(model_string: str, foundry_url: str | None, auth: str = "key") -> Any:
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
```

3. Update `create_embed_fn` signature and branch on `auth`:

```python
def create_embed_fn(
    model_string: str, foundry_url: str | None, auth: str = "key"
) -> Callable[[str], Awaitable[list[float]]]:
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
            import os

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
```

**Step 4: Update existing Foundry tests to pass auth="aad" explicitly**

The existing tests that mock `_get_token_provider` are testing AAD auth. Update them to pass `auth="aad"`:

In `tests/test_providers.py`:

- `test_create_model_foundry_openai`: add `auth="aad"` to `create_model(...)` call
- `test_create_model_foundry_anthropic`: add `auth="aad"` to `create_model(...)` call
- `test_create_embed_fn_foundry`: add `auth="aad"` to `create_embed_fn(...)` call
- `test_create_embed_fn_anthropic_raises_foundry`: add `auth="aad"` to `create_embed_fn(...)` call

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_providers.py -v`
Expected: All PASS.

**Step 6: Commit**

```bash
git add src/second_brain/providers.py tests/test_providers.py
git commit -m "feat(providers): add auth parameter to Foundry builders for key vs AAD auth"
```

---

### Task 3: Update app.py — wire per-concern config into provider calls

**Files:**
- Modify: `src/second_brain/app.py`

**Step 1: Update lifespan to use new config fields**

In `src/second_brain/app.py`, change lines 49-50 from:

```python
_model = create_model(settings.reasoning_model, settings.foundry_url)
_embed = create_embed_fn(settings.embedding_model, settings.foundry_url)
```

To:

```python
_model = create_model(settings.reasoning_model, settings.reasoning_foundry_url, settings.reasoning_auth)
_embed = create_embed_fn(settings.embedding_model, settings.embedding_foundry_url, settings.embedding_auth)
```

**Step 2: Run all tests to verify nothing broke**

Run: `uv run pytest -v`
Expected: All PASS. (App tests mock the agent runners so config fields aren't exercised directly.)

**Step 3: Commit**

```bash
git add src/second_brain/app.py
git commit -m "refactor(app): wire per-concern foundry URL and auth into provider calls"
```

---

### Task 4: Update .env.example and CLAUDE.md

**Files:**
- Modify: `.env.example`
- Modify: `CLAUDE.md`

**Step 1: Update .env.example**

Replace the old Foundry section with:

```
# Azure Foundry (optional — per-concern, independent):
# BRAIN_REASONING_FOUNDRY_URL=https://your-reasoning-resource.services.ai.azure.com
# BRAIN_REASONING_AUTH=aad          # "aad" (DefaultAzureCredential) or "key" (API key via env)
# BRAIN_EMBEDDING_FOUNDRY_URL=https://your-embedding-resource.services.ai.azure.com
# BRAIN_EMBEDDING_AUTH=key          # "aad" or "key"
#
# When *_FOUNDRY_URL is unset → PydanticAI passthrough (uses OPENAI_API_KEY etc. directly).
# When set + auth=key → routes through Foundry, authenticates with API key from env.
# When set + auth=aad → routes through Foundry, authenticates with DefaultAzureCredential.
```

**Step 2: Update CLAUDE.md environment section**

Replace `BRAIN_FOUNDRY_URL` references with the new vars:
- `BRAIN_REASONING_FOUNDRY_URL` — Azure Foundry endpoint for reasoning (optional)
- `BRAIN_REASONING_AUTH` — auth mode for reasoning: `aad` or `key` (default: `key`)
- `BRAIN_EMBEDDING_FOUNDRY_URL` — Azure Foundry endpoint for embeddings (optional)
- `BRAIN_EMBEDDING_AUTH` — auth mode for embeddings: `aad` or `key` (default: `key`)

**Step 3: Run lint to verify markdown/formatting is clean**

Run: `uv run pre-commit run --all-files`
Expected: All checks PASS.

**Step 4: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs: update env config for per-concern Foundry URL and auth"
```

---

### Task 5: Final verification

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS.

**Step 2: Run all checks**

Run: `make check`
Expected: lint, typecheck, tests all PASS.

**Step 3: Run Go client checks**

Run: `make check-all`
Expected: All PASS (Go code unaffected).
