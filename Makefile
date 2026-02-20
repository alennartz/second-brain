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
