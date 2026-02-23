# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
make install        # Install deps + pre-commit hooks
make dev            # Start server with hot reload
make test           # Run Python tests
make lint           # Lint Python
make format         # Format Python
make typecheck      # Type-check Python
make check          # All Python checks (lint + typecheck + test)
make build-client   # Build the TUI client
make test-client    # Run Go tests
make lint-client    # Lint Go
make check-all      # All checks (Python + Go)
make docker-build   # Build Docker image
make docker-up      # Start production server
make docker-down    # Stop Docker services
make e2e            # Run e2e tests (full lifecycle)
make e2e-up         # Start test server only
make e2e-down       # Stop test server
make clean          # Remove build artifacts
make help           # List all targets
```

Run a single test (no Makefile equivalent):

```bash
uv run pytest -v tests/test_recall_tools.py::test_full_text_search
```

### Pre-commit hooks

The following checks run automatically on every `git commit`. Do not run these manually before committing — the hooks handle it and will block the commit if there are errors. If a hook fails, fix the reported issues and retry the commit.

**Python:** `ruff check --fix`, `ruff format`, `basedpyright`
**Go (client/):** `golangci-lint fmt` (goimports), `golangci-lint run --fix`

## Environment

Requires a `.env` file (copy from `.env.example`). All app variables use the `BRAIN_` prefix.

### Core

- `BRAIN_DB_PATH` — SurrealDB file path (default: `data/brain.db`)
- `BRAIN_REASONING_MODEL` — LLM for agents (default: `openai:gpt-4o-mini`). Any PydanticAI model string works (e.g. `anthropic:claude-sonnet-4-5`, `groq:llama-3.3-70b`)
- `BRAIN_EMBEDDING_MODEL` — embedding model (default: `openai:text-embedding-3-small`)
- `BRAIN_EMBEDDING_DIMENSIONS` — vector dimensions (default: `1536`)
- `BRAIN_TEST_MODE` — when `true`, uses `TestModel()` and in-memory SurrealDB (no API keys needed)

### Direct API keys

- `OPENAI_API_KEY` — required when using `openai:` models without Foundry
- `ANTHROPIC_API_KEY` — required when using `anthropic:` models without Foundry

### Azure Foundry (optional, per-concern)

Each concern (reasoning, embedding) can independently target an Azure AI Foundry endpoint:

| Variable | Description |
|---|---|
| `BRAIN_REASONING_FOUNDRY_URL` | Foundry endpoint for reasoning |
| `BRAIN_REASONING_AUTH` | `aad` (DefaultAzureCredential) or `key` (default: `key`) |
| `BRAIN_REASONING_KEY` | Explicit API key override; when omitted, SDK reads its default env var (`AZURE_OPENAI_API_KEY` for openai, `ANTHROPIC_API_KEY` for anthropic) |
| `BRAIN_EMBEDDING_FOUNDRY_URL` | Foundry endpoint for embeddings |
| `BRAIN_EMBEDDING_AUTH` | `aad` or `key` (default: `key`) |
| `BRAIN_EMBEDDING_KEY` | Explicit API key override; when omitted, SDK reads `AZURE_OPENAI_API_KEY` |

**Resolution logic:** `*_FOUNDRY_URL` unset → PydanticAI passthrough (uses `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` directly). Set + `auth=aad` → DefaultAzureCredential. Set + `auth=key` → explicit `BRAIN_*_KEY` if provided, otherwise SDK reads its own default env var.

## Architecture

Personal knowledge engine: FastAPI REST API backed by an embedded SurrealDB graph database and three PydanticAI agent loops, with a Go terminal client. See [DESIGN.md](docs/DESIGN.md) for design rationale.

### Data flow

```
POST /ingest   {text, hints}        →  Ingest Agent    →  creates notes, entities, edges (auto-embeds)
POST /recall   {question, hints}    →  Recall Agent    →  hybrid search (BM25 + vector) → synthesized answer + context
POST /converse {message, history}   →  Converse Agent  →  routes to recall/ingest, multi-turn conversation
GET  /graph/{record_id}             →  node + connections lookup
```

### Key modules (server — `src/second_brain/`)

- **`app.py`** — FastAPI app with lifespan (DB init on startup). Endpoints: `/health`, `/ingest`, `/recall`, `/converse`, `/graph/{record_id}`.
- **`db.py`** — SurrealDB schema definition (`init_schema`) and vector index setup (`init_vector_indexes`). Tables: `note`, `entity`. Edge tables: `references`, `relates_to`, `derived_from`. Full-text search analyzers (BM25) and HNSW cosine indexes.
- **`providers.py`** — Model and embedding factory. `create_model` and `create_embed_fn` accept an optional `key` parameter for explicit API key override. Per-concern Foundry support: when `BRAIN_REASONING_FOUNDRY_URL` or `BRAIN_EMBEDDING_FOUNDRY_URL` is set, constructs Azure Foundry clients with the configured auth mode (`aad` for DefaultAzureCredential, `key` for explicit key or SDK default env var). Any model string prefix is accepted for Foundry embeddings (OpenAI-compatible API). Otherwise, model strings pass through to PydanticAI for native resolution.
- **`config.py`** — `Settings(BaseSettings)` with `BRAIN_` env prefix.
- **`models.py`** — Shared `Context` model (nodes + edges) and `make_serializable()` for SurrealDB types.
- **`agents/ingest.py`** — PydanticAI agent that parses input into notes/entities, searches for existing knowledge, and creates graph relationships. Auto-embeds on create. Tools: `create_note`, `create_entity`, `create_edge`, `update_node`, `search_knowledge`. Dependencies: `IngestDeps(db, embed_fn)`.
- **`agents/recall.py`** — PydanticAI agent that searches via hybrid search and graph traversal, returns `RecallOutput` with answer + cited IDs. Tools: `search_knowledge`, `get_node`, `get_connections`, `graph_traverse`. Dependencies: `RecallDeps(db, embed_fn)`.
- **`agents/converse.py`** — Conversational router that delegates to recall/ingest agents as internal tools. Supports multi-turn history. Accumulates `Context` across tool calls. Dependencies: `ConverseDeps(db, embed_fn, model_setting)`.
- **`tools/ingest_tools.py`** — DB write operations: `create_note`, `create_entity`, `create_edge`, `update_node`.
- **`tools/recall_tools.py`** — DB read operations: `hybrid_search` (BM25 + vector with RRF fusion), `get_node`, `get_connections`, `graph_traverse`, `fetch_records_by_ids`.

### Client (`client/`)

Go terminal app built with Cobra (CLI) and Bubble Tea (TUI).

- **`cmd/brain/`** — CLI entry points: `root.go` (TUI launcher), `ingest.go`, `recall.go`, `graph.go` (one-shot commands).
- **`internal/api/`** — HTTP client wrapping all server endpoints.
- **`internal/tui/`** — Bubble Tea TUI with split-pane layout (chat panel + graph panel), input bar, message history, and keyboard navigation.
- **`internal/types/`** — Shared type definitions.

### Docker

The server has a multi-stage production Dockerfile. Docker Compose provides two profiles:
- **default**: Production-like server on `:8000` with `.env` file and persistent volume
- **test** (`--profile test`): Test server on `:8001` with `BRAIN_TEST_MODE=true` (uses `TestModel()` and in-memory SurrealDB, no OpenAI key needed)

### E2E Tests

Go tests in `client/e2e/` gated behind `//go:build e2e`. They exercise the full HTTP API against a Docker-hosted test server. Run with `make e2e` or manually:

```bash
make e2e-up
cd client && go test -tags e2e -v ./e2e/ -count=1
make e2e-down
```

### Database

SurrealDB runs embedded (in-process) via `surrealkv://` protocol. Namespace and database are both `brain`. Tables are SCHEMALESS — fields are defined but the schema is flexible. The schema is idempotent (safe to re-run `init_schema`).

### Testing patterns

- Shared `db` fixture in `conftest.py` provides an in-memory SurrealDB (`mem://`) per test.
- Agent tests use `pydantic_ai.models.test.TestModel()` for deterministic behavior without real LLM calls.
- Endpoint tests use `httpx.AsyncClient` with FastAPI's `ASGITransport`.
- All tests are async (pytest-asyncio with `asyncio_mode = "auto"`).
- Go tests use standard `go test` with table-driven test patterns.
