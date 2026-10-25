.DEFAULT_GOAL := help

# --- Dev workflow ---

.PHONY: install
install: ## Install Bun dependencies and pre-commit hooks
	bun install --frozen-lockfile
	pre-commit install

.PHONY: dev
dev: ## Start the Bun server with hot reload
	bun --watch run src/main.ts

# --- TypeScript quality ---

.PHONY: test
test: ## Run Bun tests
	bun test

.PHONY: typecheck
typecheck: ## Type-check TypeScript code
	bun run typecheck

.PHONY: check
check: typecheck test ## Run TypeScript checks

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

# --- Flutter mobile quality ---

.PHONY: build-mobile
build-mobile: ## Build the Android Flutter client
	cd client/mobile && flutter build apk

.PHONY: test-mobile
test-mobile: ## Run Flutter mobile tests
	cd client/mobile && flutter test

.PHONY: analyze-mobile
analyze-mobile: ## Analyze the Flutter mobile client
	cd client/mobile && flutter analyze

# --- Containerized Flutter mobile workflow ---

.PHONY: mobile-image
mobile-image: ## Build the pinned Flutter toolchain image
	bash tools/mobile/mobile-image

.PHONY: mobile-check
mobile-check: ## Run Flutter package, analysis, and widget checks in Docker
	bash tools/mobile/mobile-check

.PHONY: mobile-build
mobile-build: ## Build a debug APK in the container
	bash tools/mobile/mobile-build

.PHONY: mobile-server-up
mobile-server-up: ## Start the isolated real-model mobile server
	bash tools/mobile/mobile-server-up

.PHONY: mobile-server-down
mobile-server-down: ## Stop only the isolated mobile server
	bash tools/mobile/mobile-server-down

.PHONY: mobile-connect
mobile-connect: ## Connect and verify the wireless debugging phone
	bash tools/mobile/mobile-connect

.PHONY: mobile-install
mobile-install: ## Build and install the debug APK on the selected phone
	bash tools/mobile/mobile-install

.PHONY: mobile-debug
mobile-debug: ## Run an interactive Flutter debug session on the phone
	bash tools/mobile/mobile-debug

.PHONY: mobile-devtools
mobile-devtools: ## Run loopback-only Flutter DevTools
	bash tools/mobile/mobile-devtools

# --- All quality ---

.PHONY: check-all
check-all: check test-client lint-client ## Run all Bun and Go checks (excludes optional Flutter checks)

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
	. $(DEPLOY_ENV) && \
		systemctl --user disable --now "$${BRAIN_DEPLOY_NAME}-backup.timer" "$${BRAIN_DEPLOY_NAME}-backup.service" "$${BRAIN_DEPLOY_NAME}.service" && \
		rm -f "$${XDG_CONFIG_HOME:-$$HOME/.config}/systemd/user/$${BRAIN_DEPLOY_NAME}.service" \
			"$${XDG_CONFIG_HOME:-$$HOME/.config}/systemd/user/$${BRAIN_DEPLOY_NAME}-backup.service" \
			"$${XDG_CONFIG_HOME:-$$HOME/.config}/systemd/user/$${BRAIN_DEPLOY_NAME}-backup.timer" && \
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
