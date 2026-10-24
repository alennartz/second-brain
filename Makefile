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

# --- Benchmark runner ---

.PHONY: bench-start
bench-start: ## Start a supervised benchmark: make bench-start NAME=run-id NOTES="..."
	@test -n "$(NAME)" || { echo "set NAME=..." >&2; exit 2; }
	experiments/benchctl.sh start "$(NAME)" "$(NOTES)"

.PHONY: bench-resume
bench-resume: ## Resume a stopped or failed benchmark: make bench-resume NAME=run-id
	@test -n "$(NAME)" || { echo "set NAME=..." >&2; exit 2; }
	experiments/benchctl.sh resume "$(NAME)"

.PHONY: bench-status
bench-status: ## Show benchmark service and live progress
	@test -n "$(NAME)" || { echo "set NAME=..." >&2; exit 2; }
	experiments/benchctl.sh status "$(NAME)"

.PHONY: bench-stop
bench-stop: ## Interrupt benchmark safely: make bench-stop NAME=run-id
	@test -n "$(NAME)" || { echo "set NAME=..." >&2; exit 2; }
	experiments/benchctl.sh stop "$(NAME)"

.PHONY: bench-log
bench-log: ## Follow benchmark log: make bench-log NAME=run-id
	@test -n "$(NAME)" || { echo "set NAME=..." >&2; exit 2; }
	experiments/benchctl.sh log "$(NAME)"

# --- Systemd user deployment (machine-specific config lives in deploy/deploy.env, gitignored) ---

DEPLOY_ENV := deploy/deploy.env
MODE ?= daily

.PHONY: deploy
deploy: ## Build and install the local image and systemd user service
	bash deploy/update.sh

.PHONY: deploy-backup
deploy-backup: ## Create a daily or pre-update archive (MODE=daily by default)
	@test -n "$(MODE)" || { echo "MODE must be nonempty" >&2; exit 1; }
	bash deploy/backup.sh $(MODE)

.PHONY: deploy-restore
deploy-restore: ## Restore an explicit archive (ARCHIVE=/path/to/archive.tar.gz)
	@test -n "$(ARCHIVE)" || { echo "set ARCHIVE=/path/to/archive.tar.gz" >&2; exit 1; }
	bash deploy/backup.sh restore $(shell bash -c 'printf "%q" "$$1"' _ "$(ARCHIVE)")

.PHONY: deploy-undeploy
deploy-undeploy: ## Stop, disable, and remove the systemd service and backup timer
	@test -f $(DEPLOY_ENV) || { echo "$(DEPLOY_ENV) missing" >&2; exit 1; }
	. $(DEPLOY_ENV) && \\
		systemctl --user disable --now "$${BRAIN_DEPLOY_NAME}-backup.timer" "$${BRAIN_DEPLOY_NAME}-backup.service" "$${BRAIN_DEPLOY_NAME}.service" && \\
		rm -f "$${XDG_CONFIG_HOME:-$$HOME/.config}/systemd/user/$${BRAIN_DEPLOY_NAME}.service" \\
			"$${XDG_CONFIG_HOME:-$$HOME/.config}/systemd/user/$${BRAIN_DEPLOY_NAME}-backup.service" \\
			"$${XDG_CONFIG_HOME:-$$HOME/.config}/systemd/user/$${BRAIN_DEPLOY_NAME}-backup.timer" && \\
		systemctl --user daemon-reload

.PHONY: deploy-status
deploy-status: ## Show systemd status for the deployed service
	@test -f $(DEPLOY_ENV) || { echo "$(DEPLOY_ENV) missing" >&2; exit 1; }
	. $(DEPLOY_ENV) && systemctl --user status "$${BRAIN_DEPLOY_NAME}.service" --no-pager

.PHONY: deploy-logs
deploy-logs: ## Follow logs of the deployed service
	@test -f $(DEPLOY_ENV) || { echo "$(DEPLOY_ENV) missing" >&2; exit 1; }
	. $(DEPLOY_ENV) && journalctl --user -u "$${BRAIN_DEPLOY_NAME}.service" -f

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
