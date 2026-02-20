# DevX Tooling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a production-ready Dockerfile, Docker Compose, server test mode, Go e2e tests, and a unified Makefile.

**Architecture:** The server gets a `BRAIN_TEST_MODE` env var that swaps real LLM/embedding calls for `TestModel()` and zero-vector stubs. Docker Compose exposes two profiles: default (production-like on :8000) and test (mocked LLM on :8001). Go e2e tests in `client/e2e/` hit the test server via the existing `internal/api` client. A root Makefile wraps all dev commands.

**Tech Stack:** Docker multi-stage builds, Docker Compose profiles, PydanticAI TestModel, Go build tags, GNU Make.

---

### Task 1: Add `test_mode` to server config

**Files:**
- Modify: `src/second_brain/config.py`
- Test: `tests/test_config.py` (create)

**Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
import os

from second_brain.config import Settings


def test_test_mode_defaults_false():
    s = Settings(
        _env_file=None,
        db_path="data/brain.db",
        embedding_model="openai:text-embedding-3-small",
        reasoning_model="openai:gpt-4o-mini",
        embedding_dimensions=1536,
    )
    assert s.test_mode is False


def test_test_mode_from_env(monkeypatch):
    monkeypatch.setenv("BRAIN_TEST_MODE", "true")
    s = Settings(
        _env_file=None,
        db_path="data/brain.db",
        embedding_model="openai:text-embedding-3-small",
        reasoning_model="openai:gpt-4o-mini",
        embedding_dimensions=1536,
    )
    assert s.test_mode is True
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `Settings` has no field `test_mode`

**Step 3: Write minimal implementation**

In `src/second_brain/config.py`, add the field to `Settings`:

```python
class Settings(BaseSettings):
    db_path: str = "data/brain.db"
    embedding_model: str = "openai:text-embedding-3-small"
    reasoning_model: str = "openai:gpt-4o-mini"
    embedding_dimensions: int = 1536
    test_mode: bool = False

    model_config = {"env_prefix": "BRAIN_", "env_file": ".env"}
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/second_brain/config.py tests/test_config.py
git commit -m "feat: add BRAIN_TEST_MODE setting"
```

---

### Task 2: Wire test mode into app lifespan

**Files:**
- Modify: `src/second_brain/app.py`

**Step 1: Write the failing test**

Add to `tests/test_app.py`:

```python
async def test_health_in_test_mode():
    """Server starts and serves /health in test mode."""
    from unittest.mock import patch

    with patch("second_brain.app.settings") as mock_settings:
        mock_settings.test_mode = True
        mock_settings.db_path = "data/brain.db"
        mock_settings.embedding_dimensions = 1536
        mock_settings.reasoning_model = "openai:gpt-4o-mini"
        # Re-import won't help since lifespan captures settings at startup.
        # Instead we test that the code path exists by checking _get_test_model import.
        from second_brain.app import _get_test_model

        model = _get_test_model()
        from pydantic_ai.models.test import TestModel

        assert isinstance(model, TestModel)
```

Actually — a simpler approach. Since the lifespan swaps global state, and the existing tests mock at a higher level, it's better to just verify the code path works structurally. Instead:

**Step 1: Modify `app.py` lifespan**

Update the lifespan in `src/second_brain/app.py` to support test mode:

```python
from pydantic_ai.models.test import TestModel

# Module-level state that lifespan configures
_db: Any = None
_model: Any = None
_embed: Any = None

_ingest_agent = create_ingest_agent()
_recall_agent = create_recall_agent()
_converse_agent = create_converse_agent()


def _dummy_embed(dimensions: int):
    """Return an embed function that produces zero vectors."""
    async def _embed(text: str) -> list[float]:
        return [0.0] * dimensions
    return _embed


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db, _model, _embed

    if settings.test_mode:
        _db = AsyncSurreal("mem://")
        _model = TestModel()
        _embed = _dummy_embed(settings.embedding_dimensions)
    else:
        _db = AsyncSurreal(f"surrealkv://{settings.db_path}")
        _model = settings.reasoning_model
        _embed = embed_text

    await _db.use("brain", "brain")
    await init_schema(_db)
    await init_vector_indexes(_db)
    yield
    if _db:
        await _db.close()
        _db = None
```

Then update the three `run_*` functions to use `_model` and `_embed` instead of hardcoded `settings.reasoning_model` and `embed_text`:

In `run_ingest_agent`:
```python
    result = await _ingest_agent.run(
        prompt,
        deps=IngestDeps(db=_db, embed_fn=_embed),
        model=_model,
    )
```

In `run_recall_agent`:
```python
    result = await _recall_agent.run(
        prompt,
        deps=RecallDeps(db=_db, embed_fn=_embed),
        model=_model,
    )
```

In `run_converse_agent`:
```python
    deps = ConverseDeps(
        db=_db,
        embed_fn=_embed,
        model_setting=_model,
    )
    # ...
    result = await _converse_agent.run(
        message,
        deps=deps,
        model=_model,
        message_history=pydantic_history,
    )
```

**Step 2: Run existing tests to verify nothing breaks**

Run: `uv run pytest -v`
Expected: All existing tests PASS (they mock `run_ingest_agent` etc., so the lifespan changes don't affect them)

**Step 3: Run lint and typecheck**

Run: `uv run ruff check src/ tests/ && uv run basedpyright src/`
Expected: PASS

**Step 4: Commit**

```bash
git add src/second_brain/app.py
git commit -m "feat: wire BRAIN_TEST_MODE into app lifespan"
```

---

### Task 3: Create `.dockerignore`

**Files:**
- Create: `.dockerignore`

**Step 1: Create the file**

```
.venv/
.git/
client/
tests/
data/
docs/
*.pyc
__pycache__/
.env
.env.example
.pre-commit-config.yaml
.ruff_cache/
Makefile
docker-compose.yml
.dockerignore
```

**Step 2: Commit**

```bash
git add .dockerignore
git commit -m "chore: add .dockerignore"
```

---

### Task 4: Create the Dockerfile

**Files:**
- Create: `Dockerfile`

**Step 1: Create the Dockerfile**

```dockerfile
FROM python:3.12-slim AS builder

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-editable

COPY src/ src/

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv .venv
COPY --from=builder /app/src src

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "second_brain.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 2: Build and verify**

Run: `docker build -t second-brain .`
Expected: Build succeeds. Image has `uvicorn` in PATH.

**Step 3: Quick smoke test**

Run: `docker run --rm -e BRAIN_TEST_MODE=true -p 8000:8000 second-brain &`
Wait a few seconds, then:
Run: `curl http://localhost:8000/health`
Expected: `{"status":"ok"}`

Stop the container after.

**Step 4: Commit**

```bash
git add Dockerfile
git commit -m "feat: add production-ready Dockerfile"
```

---

### Task 5: Create `docker-compose.yml`

**Files:**
- Create: `docker-compose.yml`

**Step 1: Create the file**

```yaml
services:
  server:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    volumes:
      - brain-data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 5s
      timeout: 3s
      retries: 3

  server-test:
    build: .
    ports:
      - "8001:8000"
    environment:
      BRAIN_TEST_MODE: "true"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 5s
      timeout: 3s
      retries: 3
    profiles:
      - test

volumes:
  brain-data:
```

Note: `server-test` is in the `test` profile so it only starts with `docker compose --profile test up`.

**Step 2: Test the test profile**

Run: `docker compose --profile test up -d server-test`
Run: `docker compose --profile test ps` (verify server-test is healthy)
Run: `curl http://localhost:8001/health`
Expected: `{"status":"ok"}`
Run: `docker compose --profile test down`

**Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add docker-compose with production and test profiles"
```

---

### Task 6: Create Go e2e tests

**Files:**
- Create: `client/e2e/e2e_test.go`

**Step 1: Create the e2e test file**

Create `client/e2e/e2e_test.go`:

```go
//go:build e2e

package e2e_test

import (
	"fmt"
	"net/http"
	"os"
	"testing"
	"time"

	"second-brain-client/internal/api"
)

var serverURL string

func TestMain(m *testing.M) {
	serverURL = os.Getenv("E2E_SERVER_URL")
	if serverURL == "" {
		serverURL = "http://localhost:8001"
	}

	// Wait for server to be healthy
	client := &http.Client{Timeout: 2 * time.Second}
	healthURL := fmt.Sprintf("%s/health", serverURL)
	for i := range 30 {
		resp, err := client.Get(healthURL)
		if err == nil && resp.StatusCode == http.StatusOK {
			_ = resp.Body.Close()
			break
		}
		if i == 29 {
			fmt.Fprintf(os.Stderr, "server not healthy after 30 attempts at %s\n", healthURL)
			os.Exit(1)
		}
		time.Sleep(1 * time.Second)
	}

	os.Exit(m.Run())
}

func TestHealth(t *testing.T) {
	resp, err := http.Get(fmt.Sprintf("%s/health", serverURL))
	if err != nil {
		t.Fatalf("health request failed: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
}

func TestIngest(t *testing.T) {
	c := api.New(serverURL)
	resp, err := c.Ingest("The Feynman Technique is a learning method where you explain concepts in simple terms.", nil)
	if err != nil {
		t.Fatalf("ingest failed: %v", err)
	}
	if resp.Summary == "" {
		t.Error("expected non-empty summary")
	}
}

func TestRecall(t *testing.T) {
	c := api.New(serverURL)

	// Ingest first so there's something to recall
	_, err := c.Ingest("Spaced repetition is an evidence-based learning technique using increasing intervals.", nil)
	if err != nil {
		t.Fatalf("ingest failed: %v", err)
	}

	resp, err := c.Recall("What do I know about learning?", nil)
	if err != nil {
		t.Fatalf("recall failed: %v", err)
	}
	if resp.Answer == "" {
		t.Error("expected non-empty answer")
	}
}

func TestConverse(t *testing.T) {
	c := api.New(serverURL)
	resp, err := c.Converse("Hello, what do you know?", nil)
	if err != nil {
		t.Fatalf("converse failed: %v", err)
	}
	if resp.Response == "" {
		t.Error("expected non-empty response")
	}
}

func TestGraphNotFound(t *testing.T) {
	c := api.New(serverURL)
	_, err := c.Graph("note:nonexistent")
	if err == nil {
		t.Error("expected error for nonexistent node")
	}
}
```

**Step 2: Verify the tests compile (but skip running — no server yet)**

Run: `cd client && go vet -tags e2e ./e2e/`
Expected: No errors (compiles cleanly)

**Step 3: Run e2e tests against the test server**

First start the test server:
Run: `docker compose --profile test up -d server-test`
Wait for healthy, then:
Run: `cd client && go test -tags e2e -v ./e2e/ -count=1`
Expected: All tests PASS

Tear down:
Run: `docker compose --profile test down`

**Step 4: Commit**

```bash
git add client/e2e/
git commit -m "feat: add Go e2e tests for server API"
```

---

### Task 7: Create the Makefile

**Files:**
- Create: `Makefile`

**Step 1: Create the Makefile**

```makefile
.DEFAULT_GOAL := help

# --- Dev workflow ---

.PHONY: install
install: ## Install all dependencies (Python + pre-commit hooks)
	uv sync --all-extras
	uv run pre-commit install

.PHONY: dev
dev: ## Start the dev server with hot reload
	uv run uvicorn second_brain.app:app --reload

# --- Python quality ---

.PHONY: test
test: ## Run Python tests
	uv run pytest -v

.PHONY: lint
lint: ## Lint Python code
	uv run ruff check src/ tests/

.PHONY: format
format: ## Format Python code
	uv run ruff format src/ tests/

.PHONY: typecheck
typecheck: ## Type-check Python code
	uv run basedpyright src/

.PHONY: check
check: lint typecheck test ## Run all Python quality checks

# --- Go quality ---

.PHONY: build-client
build-client: ## Build the Go TUI client
	cd client && go build -o brain ./cmd/brain

.PHONY: test-client
test-client: ## Run Go unit tests
	cd client && go test ./...

.PHONY: lint-client
lint-client: ## Lint Go code
	cd client && golangci-lint run

# --- All quality ---

.PHONY: check-all
check-all: check test-client lint-client ## Run all quality checks (Python + Go)

# --- Docker ---

.PHONY: docker-build
docker-build: ## Build the Docker image
	docker compose build

.PHONY: docker-up
docker-up: ## Start the production server in Docker
	docker compose up -d server

.PHONY: docker-down
docker-down: ## Stop all Docker services
	docker compose down

# --- E2E ---

.PHONY: e2e-up
e2e-up: ## Start the test server for e2e tests
	docker compose --profile test up -d server-test
	@echo "Waiting for server-test to be healthy..."
	@until curl -sf http://localhost:8001/health > /dev/null 2>&1; do sleep 1; done
	@echo "server-test is ready on :8001"

.PHONY: e2e-down
e2e-down: ## Stop the e2e test server
	docker compose --profile test down

.PHONY: e2e
e2e: e2e-up ## Run e2e tests (starts server, runs tests, tears down)
	cd client && go test -tags e2e -v ./e2e/ -count=1; \
	status=$$?; \
	cd .. && $(MAKE) e2e-down; \
	exit $$status

# --- Utility ---

.PHONY: clean
clean: ## Remove build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -f client/brain

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
```

**Step 2: Verify help works**

Run: `make help`
Expected: Nicely formatted list of all targets with descriptions.

**Step 3: Verify existing commands work through Make**

Run: `make test`
Expected: Python tests pass.

Run: `make test-client`
Expected: Go tests pass.

**Step 4: Run the full e2e flow**

Run: `make e2e`
Expected: Builds Docker image, starts test server, runs Go e2e tests, tears down. All pass.

**Step 5: Commit**

```bash
git add Makefile
git commit -m "feat: add unified Makefile for all dev commands"
```

---

### Task 8: Update CLAUDE.md with new commands

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add Makefile section to CLAUDE.md**

Add after the existing "Pre-commit hooks" section in the Commands block:

```markdown
### Makefile (unified entry point)

```bash
# Setup
make install        # Install deps + pre-commit hooks

# Dev
make dev            # Start server with hot reload

# Python quality
make test           # Run Python tests
make lint           # Lint Python
make format         # Format Python
make typecheck      # Type-check Python
make check          # All Python checks (lint + typecheck + test)

# Go quality
make build-client   # Build the TUI client
make test-client    # Run Go tests
make lint-client    # Lint Go

# All quality
make check-all      # All checks (Python + Go)

# Docker
make docker-build   # Build Docker image
make docker-up      # Start production server
make docker-down    # Stop Docker services

# E2E
make e2e            # Run e2e tests (full lifecycle)
make e2e-up         # Start test server only
make e2e-down       # Stop test server

# Utility
make clean          # Remove build artifacts
make help           # List all targets
```
```

Also add to the Architecture section:

```markdown
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
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add Makefile, Docker, and e2e test docs to CLAUDE.md"
```
