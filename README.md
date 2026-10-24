# Second Brain

Second Brain stores, connects, and retrieves your notes and ideas. It combines SurrealDB, hybrid search (BM25 + vector), and LLM agents. Intake stages source text for immediate search. Background workers organize it into notes, entities, and relationships. See [DESIGN.md](docs/DESIGN.md) for design principles.

## Quickstart

**Prerequisites:** [uv](https://docs.astral.sh/uv/) (Python), [Go 1.22+](https://go.dev/dl/) (for the CLI client)

```bash
# Install dependencies and pre-commit hooks
make install

# Configure your environment
cp .env.example .env
# Edit .env — at minimum set OPENAI_API_KEY (see Configuration below).
# Or skip credentials entirely: set BRAIN_TEST_MODE=true to use stub models
# and an in-memory DB (great for a first look).

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
| `brain ingest [text]` | Stage text for immediate search and background organization |
| `brain recall [question]` | Ask a question over your knowledge base |
| `brain graph [id]` | Show a node and its connections |

All commands accept `--server URL` (default: `http://localhost:8000`).

### Intake and recall

Ingest stages text before it returns. It splits and embeds the text, stores searchable chunks, and reports their count. The background pipeline later organizes those chunks into the knowledge graph. A successful response does not mean organization is complete.

Recall searches graph records and chunks awaiting processing. It returns unprocessed chunks separately from graph nodes and edges. Chunks leave recall after successful processing.

Use `GET /ingest/pipeline` to inspect queue counts, worker activity, retries, stuck intakes, and recent errors. Use `POST /ingest/pipeline/{intake_id}/pause`, `/resume`, or `/discard` to control one intake. `POST /ingest` accepts an optional `Idempotency-Key` header.

## Configuration

All settings live in a `.env` file (or environment variables). App-specific variables use the `BRAIN_` prefix.

### Core settings

| Variable | Default | Description |
|---|---|---|
| `BRAIN_DB_PATH` | `data/brain.db` | SurrealDB file path |
| `BRAIN_REASONING_MODEL` | `openai:gpt-4o-mini` | LLM for agents — any [PydanticAI model string](https://pydantic.dev/docs/ai/models/overview/) |
| `BRAIN_REASONING_EFFORT` | unset | Optional OpenAI `reasoning_effort`: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, or `max` |
| `BRAIN_EMBEDDING_MODEL` | `openai:text-embedding-3-small` | Embedding model |
| `BRAIN_EMBEDDING_DIMENSIONS` | `1536` | Vector dimensions (must match your embedding model). ⚠️ Changing this after first run requires wiping `data/` — HNSW indexes bake in the dimension. |
| `BRAIN_TEST_MODE` | `false` | Use stub models and in-memory DB (no API keys needed) |

Model strings follow the `provider:model_name` format (e.g. `openai:gpt-4o`, `anthropic:claude-sonnet-4-5`, `groq:llama-3.3-70b`, `google-gla:gemini-2.0-flash`).

### LLM provider configuration

There are three ways to connect to LLM providers, from simplest to most advanced.

#### Option 1: Direct API keys (simplest)

Set `BRAIN_REASONING_MODEL` / `BRAIN_EMBEDDING_MODEL` to any [PydanticAI model string](https://pydantic.dev/docs/ai/models/overview/) and provide the credentials that provider expects. PydanticAI handles routing — the provider prefix in the model string determines which SDK is used and which env var it reads. See [PydanticAI's provider docs](https://pydantic.dev/docs/ai/models/overview/) for the exact env var per provider.

The two most common examples:

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

For an OpenAI-compatible endpoint (such as vLLM or a local inference server), set `BRAIN_REASONING_BASE_URL` and/or `BRAIN_EMBEDDING_BASE_URL`. This route requires an `openai:` model string. Leave `BRAIN_REASONING_EFFORT` unset to use the provider default. When set, it sends the requested effort on every reasoning chat-completion call. The endpoint must support `reasoning_effort`.

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
| `BRAIN_REASONING_EFFORT` | — | Optional OpenAI request effort: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`; requires an `openai:` model |
| `BRAIN_REASONING_BASE_URL` | — | OpenAI-compatible endpoint for reasoning chat completions |
| `BRAIN_EMBEDDING_BASE_URL` | — | OpenAI-compatible endpoint for embeddings |
| `BRAIN_EMBEDDING_MODEL` | `openai:text-embedding-3-small` | Embedding model string |
| `BRAIN_EMBEDDING_DIMENSIONS` | `1536` | Vector dimensions (see note above) |
| `BRAIN_TEST_MODE` | `false` | Stub models + in-memory DB |
| `BRAIN_REASONING_FOUNDRY_URL` | — | Azure Foundry endpoint for reasoning |
| `BRAIN_REASONING_AUTH` | `key` | `key` or `aad` |
| `BRAIN_REASONING_KEY` | — | Explicit API key for reasoning Foundry endpoint |
| `BRAIN_EMBEDDING_FOUNDRY_URL` | — | Azure Foundry endpoint for embeddings |
| `BRAIN_EMBEDDING_AUTH` | `key` | `key` or `aad` |
| `BRAIN_EMBEDDING_KEY` | — | Explicit API key for embedding Foundry endpoint |
| Provider API keys | — | Whatever env vars the underlying provider SDK expects — see [PydanticAI's provider docs](https://pydantic.dev/docs/ai/models/overview/) (e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, …). |

## Local production deployment

The local production service uses a systemd user unit and a Docker image built
from this checkout. It listens only on `127.0.0.1:8100`, mounts the configured
host data directory, and archives the active database before updates.

```bash
cp deploy/deploy.env.example deploy/deploy.env
# Set the machine paths and BRAIN_DB_PATH=/data/brain.db in the app environment.
docker build -t second-brain:local .
bash deploy/install.sh          # first installation
make deploy-status
```

Use `make deploy` for routine updates after the service has an active database.
Use `make deploy-backup`, `make deploy-backup MODE=pre-update`, and
`make deploy-restore ARCHIVE=/path/to/archive.tar.gz` for local recovery. The
installer sets the application environment file to mode `0600`, enables a
persistent daily timer at 03:00 local time, and never pulls from a registry.
Loopback access is the trust boundary. The application has no authentication
layer. Routine deployment does not reset the database. Follow
[`deploy/README.md`](deploy/README.md) and the
[local production manual test journey](docs/manual-tests/local-production-server.md)
for setup, reset, update, and recovery procedures. See
[`docs/local-production.md`](docs/local-production.md) for the current instance
configuration, database state, upstream endpoints, and verification status.

## Docker development deployment

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
