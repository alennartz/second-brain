# DevX Tooling Design: Makefile, Docker, E2E Tests

**Date:** 2026-02-20

## Goals

1. Production-ready Docker image for the Python server
2. End-to-end tests in Go that exercise the full HTTP API against a running server
3. Unified Makefile as the single entry point for all dev commands

## Decisions

- **Docker scope:** Server only. The Go client stays a locally-built binary.
- **E2E LLM mocking:** Test-mode env var (`BRAIN_TEST_MODE=true`) swaps PydanticAI models for `TestModel()` and embeddings for a zero-vector stub. Same pattern as existing unit tests.
- **E2E language:** Go tests in `client/e2e/` using the existing `internal/api` client, gated behind a `//go:build e2e` tag.
- **Makefile scope:** Unified entry point wrapping all Python, Go, Docker, and e2e commands.

## 1. Dockerfile

Multi-stage build:

**Stage 1 (builder):** `python:3.12-slim`. Install `uv`, copy `pyproject.toml` + `uv.lock`, run `uv sync --no-dev`. Copy source.

**Stage 2 (runtime):** `python:3.12-slim`. Copy venv and source from builder. No uv, no dev deps, no build tools. Entrypoint: `uvicorn second_brain.app:app --host 0.0.0.0 --port 8000`.

Details:
- SurrealDB data at `/data/brain.db` (volume-mountable)
- Env vars passed at runtime, not baked in
- `.dockerignore` excludes `.venv/`, `client/`, `tests/`, `data/`, `docs/`, `.git/`

## 2. Docker Compose

Single `docker-compose.yml` with two profiles:

**Default profile (production-like):**
- `server` service on port 8000
- `env_file: .env`
- Named volume `brain-data` at `/data`
- Health check: `curl -f http://localhost:8000/health`

**Test profile (for e2e):**
- `server-test` service on port 8001 (no conflict with dev server)
- `BRAIN_TEST_MODE=true`, `BRAIN_DB_PATH` set to use in-memory SurrealDB
- Same health check

## 3. Server Test Mode

Add to `config.py`:
```python
test_mode: bool = False  # env: BRAIN_TEST_MODE
```

In `app.py` lifespan, when `settings.test_mode` is `True`:
- Connect to `mem://` SurrealDB instead of `surrealkv://{db_path}`
- Use `TestModel()` from `pydantic_ai.models.test` for all agents
- Use a dummy embedding function returning `[0.0] * settings.embedding_dimensions`

Agents themselves don't change. Only the deps wired at startup differ.

## 4. E2E Tests

**Location:** `client/e2e/e2e_test.go`

**Build tag:** `//go:build e2e` (excluded from `go test ./...`)

**Test cases:**
1. `GET /health` — server is alive
2. `POST /ingest` — send text, get summary back (200, valid shape)
3. `POST /recall` — ask question, get answer + context (200, valid shape)
4. `POST /converse` — multi-turn conversation (200, valid shape)
5. `GET /graph/{id}` — ingest then fetch node and connections (200 or 404)

**TestMain:** Waits for health endpoint at `http://localhost:8001` before running tests. Configurable via `E2E_SERVER_URL` env var.

**Assertions focus on:**
- Correct HTTP status codes
- Response JSON structure (has expected fields)
- No 500 errors
- Ingest-then-query flow works end-to-end

Not testing LLM quality — TestModel returns deterministic placeholder text.

## 5. Makefile

All targets `.PHONY`. Default target: `help`.

### Dev workflow
- `make dev` — `uv run uvicorn second_brain.app:app --reload`
- `make install` — `uv sync --all-extras`
- `make hooks` — `uv run pre-commit install`

### Quality (Python)
- `make test` — `uv run pytest -v`
- `make lint` — `uv run ruff check src/ tests/`
- `make format` — `uv run ruff format src/ tests/`
- `make typecheck` — `uv run basedpyright src/`
- `make check` — lint + typecheck + test (sequential)

### Quality (Go)
- `make test-client` — `cd client && go test ./...`
- `make lint-client` — `cd client && golangci-lint run`
- `make build-client` — `cd client && go build -o brain ./cmd/brain`

### Quality (all)
- `make check-all` — check + test-client + lint-client

### Docker
- `make docker-build` — `docker compose build`
- `make docker-up` — `docker compose up -d`
- `make docker-down` — `docker compose down`

### E2E
- `make e2e` — build test image, start it, wait for health, run Go e2e tests, tear down
- `make e2e-up` — start test server only
- `make e2e-down` — tear down test server

### Utility
- `make clean` — remove `__pycache__`, `client/brain` binary, build artifacts
- `make help` — list all targets with descriptions
