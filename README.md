# Second Brain

Personal knowledge engine that stores, connects, and retrieves your notes and ideas. It combines a graph database (SurrealDB), hybrid search (BM25 + vector), and LLM agents to ingest unstructured text, extract entities and relationships, and answer questions over your accumulated knowledge. For high level design principles, see [DESIGN.md](docs/DESIGN.md).

## Quickstart

**Prerequisites:** [uv](https://docs.astral.sh/uv/) (Python), [Go 1.22+](https://go.dev/dl/) (for the CLI client)

```bash
# Install dependencies and pre-commit hooks
make install

# Configure your environment
cp .env.example .env
# Edit .env — at minimum set OPENAI_API_KEY (see Configuration below)

# Start the server
make dev

# In another terminal — build and launch the TUI client
make build-client
./client/brain
```

## CLI client

The client is a Go terminal app with both a TUI mode and one-shot commands. It talks to the server over HTTP.

```bash
# Launch the interactive TUI (split-pane chat + graph view)
brain

# One-shot commands
brain ingest "Kubernetes pods are the smallest deployable units"
brain recall "what do I know about Kubernetes?"
brain graph "entity:abc123"

# Point at a different server
brain --server http://my-server:8000 recall "..."
# Or set BRAIN_SERVER_URL in your environment
```

### Commands

| Command | Description |
|---|---|
| `brain` | Launch the interactive TUI |
| `brain ingest [text]` | Store a piece of knowledge |
| `brain recall [question]` | Ask a question over your knowledge base |
| `brain graph [id]` | Show a node and its connections |

All commands accept `--server URL` (default: `http://localhost:8000`).

## Configuration

All settings live in a `.env` file (or environment variables). App-specific variables use the `BRAIN_` prefix.

### Core settings

| Variable | Default | Description |
|---|---|---|
| `BRAIN_DB_PATH` | `data/brain.db` | SurrealDB file path |
| `BRAIN_REASONING_MODEL` | `openai:gpt-4o-mini` | LLM for agents — any [PydanticAI model string](https://ai.pydantic.dev/models/) |
| `BRAIN_EMBEDDING_MODEL` | `openai:text-embedding-3-small` | Embedding model |
| `BRAIN_EMBEDDING_DIMENSIONS` | `1536` | Vector dimensions (must match your embedding model) |
| `BRAIN_TEST_MODE` | `false` | Use stub models and in-memory DB (no API keys needed) |

Model strings follow the `provider:model_name` format. Examples: `openai:gpt-4o`, `anthropic:claude-sonnet-4-5`, `groq:llama-3.3-70b`.

### LLM provider configuration

There are three ways to connect to LLM providers, from simplest to most advanced.

#### Option 1: Direct API keys (simplest)

Set the model string and the corresponding API key:

```bash
# OpenAI
BRAIN_REASONING_MODEL=openai:gpt-4o-mini
OPENAI_API_KEY=sk-...

# Anthropic
BRAIN_REASONING_MODEL=anthropic:claude-sonnet-4-5
ANTHROPIC_API_KEY=sk-ant-...

# Embeddings (OpenAI)
BRAIN_EMBEDDING_MODEL=openai:text-embedding-3-small
# Uses OPENAI_API_KEY from above
```

PydanticAI handles the routing — the provider prefix in the model string determines which SDK and which API key env var is used.

#### Option 2: Azure AI Foundry with API key

Route requests through an Azure AI Foundry endpoint using an API key. Reasoning and embedding can target different Foundry endpoints independently.

```bash
BRAIN_REASONING_MODEL=openai:gpt-4o-mini
BRAIN_REASONING_FOUNDRY_URL=https://your-resource.services.ai.azure.com
BRAIN_REASONING_AUTH=key
BRAIN_REASONING_KEY=your-foundry-api-key          # optional — see fallback below

BRAIN_EMBEDDING_MODEL=openai:text-embedding-3-small
BRAIN_EMBEDDING_FOUNDRY_URL=https://your-embedding-resource.services.ai.azure.com
BRAIN_EMBEDDING_AUTH=key
BRAIN_EMBEDDING_KEY=your-embedding-api-key         # optional — see fallback below
```

When `BRAIN_*_KEY` is omitted, the SDK reads its default env var:
- OpenAI models: `AZURE_OPENAI_API_KEY`
- Anthropic models: `ANTHROPIC_API_KEY`

Foundry embeddings always use the OpenAI-compatible API (Azure exposes all deployed models through it), so `BRAIN_EMBEDDING_KEY` falls back to `AZURE_OPENAI_API_KEY` regardless of the model string prefix.

#### Option 3: Azure AI Foundry with AAD (managed identity)

Use `DefaultAzureCredential` for token-based auth — no API keys needed.

```bash
BRAIN_REASONING_MODEL=openai:gpt-4o-mini
BRAIN_REASONING_FOUNDRY_URL=https://your-resource.services.ai.azure.com
BRAIN_REASONING_AUTH=aad

BRAIN_EMBEDDING_MODEL=openai:text-embedding-3-small
BRAIN_EMBEDDING_FOUNDRY_URL=https://your-embedding-resource.services.ai.azure.com
BRAIN_EMBEDDING_AUTH=aad
```

Requires the `azure-identity` package and a configured Azure identity (managed identity, az CLI login, etc.).

#### Mixing providers

Reasoning and embedding are configured independently. You can mix and match — for example, use Anthropic for reasoning via direct API while routing embeddings through Azure Foundry:

```bash
# Reasoning: direct Anthropic
BRAIN_REASONING_MODEL=anthropic:claude-sonnet-4-5
ANTHROPIC_API_KEY=sk-ant-...
# No BRAIN_REASONING_FOUNDRY_URL → direct passthrough

# Embedding: Azure Foundry with API key
BRAIN_EMBEDDING_MODEL=openai:text-embedding-3-small
BRAIN_EMBEDDING_FOUNDRY_URL=https://your-resource.services.ai.azure.com
BRAIN_EMBEDDING_AUTH=key
```

### Provider resolution summary

| `*_FOUNDRY_URL` | `*_AUTH` | Authentication |
|---|---|---|
| unset | — | Direct passthrough: PydanticAI uses `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` |
| set | `key` | Azure Foundry: uses `BRAIN_*_KEY` if set, otherwise SDK default env var |
| set | `aad` | Azure Foundry: `DefaultAzureCredential` (no keys needed) |

### Full variable reference

| Variable | Default | Description |
|---|---|---|
| `BRAIN_DB_PATH` | `data/brain.db` | SurrealDB file path |
| `BRAIN_REASONING_MODEL` | `openai:gpt-4o-mini` | LLM model string (`provider:name`) |
| `BRAIN_EMBEDDING_MODEL` | `openai:text-embedding-3-small` | Embedding model string |
| `BRAIN_EMBEDDING_DIMENSIONS` | `1536` | Vector dimensions |
| `BRAIN_TEST_MODE` | `false` | Stub models + in-memory DB |
| `BRAIN_REASONING_FOUNDRY_URL` | — | Azure Foundry endpoint for reasoning |
| `BRAIN_REASONING_AUTH` | `key` | `key` or `aad` |
| `BRAIN_REASONING_KEY` | — | Explicit API key for reasoning Foundry endpoint |
| `BRAIN_EMBEDDING_FOUNDRY_URL` | — | Azure Foundry endpoint for embeddings |
| `BRAIN_EMBEDDING_AUTH` | `key` | `key` or `aad` |
| `BRAIN_EMBEDDING_KEY` | — | Explicit API key for embedding Foundry endpoint |
| `OPENAI_API_KEY` | — | Required for `openai:` models without Foundry |
| `ANTHROPIC_API_KEY` | — | Required for `anthropic:` models without Foundry |

## Docker deployment

### Production

```bash
make docker-build
make docker-up          # starts on :8000 with .env and persistent volume
make docker-down        # stop
```

The `.env` file is mounted into the container. Data persists in a Docker volume.

## Development

```bash
make install            # Install deps + pre-commit hooks
make dev                # Start server with hot reload
make build-client       # Build the Go TUI binary
make check              # Lint + typecheck + test (Python)
make check-all          # All checks (Python + Go)
make docker-build       # Build Docker image
make docker-up          # Start production server
make docker-down        # Stop Docker services
make clean              # Remove build artifacts
```
