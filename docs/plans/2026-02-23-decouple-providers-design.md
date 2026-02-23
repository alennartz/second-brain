# Decouple Provider Config: Separate Foundry URLs and Auth Modes

## Problem

The current single `BRAIN_FOUNDRY_URL` couples reasoning and embedding to the same Azure Foundry resource, and forces `DefaultAzureCredential` for all Foundry-routed models. In practice:

1. Embeddings and reasoning may live on different Foundry resources (or one may not be on Foundry at all).
2. Some models behind Foundry require API key auth instead of AAD tokens.

## Design

### Approach: Separate Foundry URLs + per-concern auth flag

Replace `BRAIN_FOUNDRY_URL` with 4 independent env vars:

```
BRAIN_REASONING_FOUNDRY_URL=https://...   # optional
BRAIN_REASONING_AUTH=aad                   # "aad" | "key" (default: "key")
BRAIN_EMBEDDING_FOUNDRY_URL=https://...   # optional
BRAIN_EMBEDDING_AUTH=key                   # "aad" | "key" (default: "key")
```

Resolution per concern:
- `*_FOUNDRY_URL` unset: PydanticAI passthrough (uses `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` natively).
- `*_FOUNDRY_URL` set + `*_AUTH=aad`: Foundry client with `DefaultAzureCredential` token provider.
- `*_FOUNDRY_URL` set + `*_AUTH=key`: Foundry client with API key from env (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`).

### Config changes (`config.py`)

Remove `foundry_url: str | None`. Add:

```python
reasoning_foundry_url: str | None = None
reasoning_auth: str = "key"
embedding_foundry_url: str | None = None
embedding_auth: str = "key"
```

### Provider changes (`providers.py`)

Public function signatures gain an `auth` parameter:

```python
def create_model(model_string: str, foundry_url: str | None, auth: str = "key") -> Any
def create_embed_fn(model_string: str, foundry_url: str | None, auth: str = "key") -> Callable[...]
```

Internal Foundry builders branch on `auth`:
- `auth="aad"`: `AsyncAzureOpenAI(azure_ad_token_provider=...)` / `AsyncAnthropicFoundry(azure_ad_token_provider=...)`
- `auth="key"`: `AsyncAzureOpenAI(api_key=os.environ["OPENAI_API_KEY"], ...)` / `AsyncAnthropicFoundry(api_key=os.environ["ANTHROPIC_API_KEY"], ...)`

### Wiring changes (`app.py`)

```python
_model = create_model(settings.reasoning_model, settings.reasoning_foundry_url, settings.reasoning_auth)
_embed = create_embed_fn(settings.embedding_model, settings.embedding_foundry_url, settings.embedding_auth)
```

### Documentation updates

- `.env.example`: Replace old Foundry section with per-concern vars.
- `CLAUDE.md`: Update environment section.

### Testing

Existing tests use `test_mode=True` (skip providers). Add unit tests for `create_model` and `create_embed_fn` passthrough path (no Foundry URL) to validate the signature change doesn't break anything.
