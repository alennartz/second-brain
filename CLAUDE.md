# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync --all-extras

# Setup pre-commit hooks (run once after clone)
uv run pre-commit install

# Run dev server (http://localhost:8000)
uv run uvicorn second_brain.app:app --reload

# Run all tests
uv run pytest -v

# Run a single test file
uv run pytest -v tests/test_recall_tools.py

# Run a single test function
uv run pytest -v tests/test_recall_tools.py::test_full_text_search

# Lint
uv run ruff check src/ tests/

# Format
uv run ruff format src/ tests/

# Type check
uv run basedpyright src/

# Run all hooks manually
uv run pre-commit run --all-files
```

### Pre-commit hooks

The following checks run automatically on every `git commit`. Do not run these manually before committing — the hooks handle it and will block the commit if there are errors. If a hook fails, fix the reported issues and retry the commit.

**Python:** `ruff check --fix`, `ruff format`, `basedpyright`
**Go (client/):** `golangci-lint fmt` (goimports), `golangci-lint run --fix`

## Environment

Requires a `.env` file (copy from `.env.example`). Key variables use the `BRAIN_` prefix:
- `OPENAI_API_KEY` — required for embeddings and agent LLM calls
- `BRAIN_DB_PATH` — SurrealDB file path (default: `data/brain.db`)
- `BRAIN_REASONING_MODEL` — LLM for agents (default: `openai:gpt-4o-mini`)
- `BRAIN_EMBEDDING_MODEL` — embedding model (default: `openai:text-embedding-3-small`)
- `BRAIN_EMBEDDING_DIMENSIONS` — vector dimensions (default: `1536`)

## Architecture

Personal knowledge engine: FastAPI REST API backed by an embedded SurrealDB graph database and two PydanticAI agent loops.

### Data flow

```
POST /ingest {text, source}  →  Ingest Agent  →  creates notes, entities, edges in SurrealDB
POST /recall {question}      →  Recall Agent   →  searches (FTS + vector + graph) → synthesized answer
```

### Key modules

- **`app.py`** — FastAPI app with lifespan (DB init on startup). Three endpoints: `/health`, `/ingest`, `/recall`.
- **`db.py`** — SurrealDB schema definition (`init_schema`). Tables: `note`, `entity`. Edge tables: `references`, `relates_to`, `derived_from`. Full-text search analyzers (BM25) and field definitions.
- **`embedding.py`** — `embed_text()` calls OpenAI embeddings API. `init_vector_indexes()` creates HNSW cosine indexes on `note.embedding` and `entity.embedding`.
- **`config.py`** — `Settings(BaseSettings)` with `BRAIN_` env prefix.
- **`agents/ingest.py`** — PydanticAI agent that parses input into notes/entities, searches for existing knowledge, creates graph relationships, and generates embeddings. Dependencies: `IngestDeps(db, embed_fn)`.
- **`agents/recall.py`** — PydanticAI agent that iteratively searches (FTS, vector, graph traversal) and synthesizes answers. Dependencies: `RecallDeps(db)`.
- **`tools/ingest_tools.py`** — DB write operations: `create_note`, `create_entity`, `create_edge`, `update_node`, `search_existing`, `embed`.
- **`tools/recall_tools.py`** — DB read operations: `full_text_search`, `vector_search`, `get_node`, `get_connections`, `graph_traverse`.

### Database

SurrealDB runs embedded (in-process) via `surrealkv://` protocol. Namespace and database are both `brain`. Tables are SCHEMALESS — fields are defined but the schema is flexible. The schema is idempotent (safe to re-run `init_schema`).

### Testing patterns

- Shared `db` fixture in `conftest.py` provides an in-memory SurrealDB (`mem://`) per test.
- Agent tests use `pydantic_ai.models.test.TestModel()` for deterministic behavior without real LLM calls.
- Endpoint tests use `httpx.AsyncClient` with FastAPI's `ASGITransport`.
- All tests are async (pytest-asyncio with `asyncio_mode = "auto"`).
