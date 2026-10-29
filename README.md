# Second Brain

Second Brain stores, connects, and retrieves notes and ideas. It stages intake
text for immediate search, then organizes it in a graph with Pi workflows.
The server runs as a Bun-native TypeScript application with an embedded
SurrealDB database.

## Quickstart

**Prerequisites:** Bun 1.4+, Docker for container workflows, Go 1.25+ for the
terminal client, and Flutter tooling for Android builds.

```bash
# Install dependencies and pre-commit hooks
make install

# Configure provider credentials and workflow models
cp .env.example .env
# Edit .env. Set credentials for the configured Pi chat provider and embeddings.

# Start the Bun server with hot reload
make dev

# In another terminal, build the supported CLI client
make build-client
./client/brain ingest "A first memory"
```

The server initializes a fresh latest-schema `surrealkv://` database at
`BRAIN_DB_PATH`. It does not migrate database files from the former server. The
Docker image carries its dedicated Pi model and settings files under
`config/pi`; it does not depend on the host's `~/.pi/agent` directory.
Before cutover, build the Bun image, then archive and reset the active database
with the procedure in [`deploy/README.md`](deploy/README.md). To start over later,
stop the server and remove its database directory.

## HTTP API

The server exposes the non-conversation API:

- `GET /health`
- `POST /ingest` with optional `Idempotency-Key`
- `GET /ingest/pipeline`
- `POST /ingest/pipeline/{intake_id}/pause`
- `POST /ingest/pipeline/{intake_id}/resume`
- `POST /ingest/pipeline/{intake_id}/discard`
- `POST /recall`
- `POST /dream` and `GET /dream/jobs/{job_id}`
- `GET /graph/{record_id}`

`POST /ingest` stages searchable chunks before it returns. The background
pipeline later organizes those chunks. Each intake request must include the
client capture time in `captured_at`. Use `POST /recall` with a JSON body
containing `question` and optional `hints`. Conversation and MCP routes are
intentionally absent.

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/ingest \
  -H 'content-type: application/json' \
  -H 'Idempotency-Key: capture-1' \
  -d '{"text":"Kubernetes pods are deployable units","hints":["kubernetes"],"captured_at":"2026-01-01T12:00:00-05:00"}'
curl -X POST http://localhost:8000/recall \
  -H 'content-type: application/json' \
  -d '{"question":"What do I know about Kubernetes?"}'
```

## CLI client

The Go client supports one-shot ingest, recall, and graph commands. The legacy
interactive TUI targets conversation routes that the Bun server does not expose
and is not part of the supported client workflow.

```bash
brain ingest "Kubernetes pods are the smallest deployable units"
brain recall "what do I know about Kubernetes?"
brain graph "entity:abc123"
brain --server http://localhost:8000 recall "..."
```

All commands accept `--server URL` and default to `http://localhost:8000`.

## Android mobile client

The Android-first Flutter app provides Capture and one-shot Ask. It stores the
server URL and one failed Capture draft. Use the project-owned containerized
workflow on Linux hosts with Docker and host ADB:

```bash
cp .env.mobile.example .env.mobile.local
# Set MOBILE_DEVICE, MOBILE_SERVER_URL, MOBILE_DEVTOOLS_PORT, and credentials.
make mobile-image
make mobile-check
make mobile-server-up
make mobile-connect
make mobile-install
make mobile-debug
# In another terminal:
make mobile-devtools
```

The mobile server uses real models, an isolated `mobile-brain-data` volume, and
port 8200 on a trusted private LAN. See [`tools/mobile/README.md`](tools/mobile/README.md)
for pairing, cache, and DevTools boundaries.

## Configuration

All settings use environment variables. Workflow model references use
`provider/model:effort`, where effort is one of `off`, `minimal`, `low`,
`medium`, `high`, `xhigh`, or `max`.

| Variable | Default | Description |
|---|---|---|
| `BRAIN_DB_PATH` | `data/brain.db` | Fresh SurrealKV database path |
| `BRAIN_INGEST_MODEL` | required | Model for intake organization |
| `BRAIN_RECALL_MODEL` | required | Model for evidence-backed recall |
| `BRAIN_DREAM_MODEL` | required | Model for graph refinement |
| `BRAIN_EMBEDDING_MODEL` | `openai:text-embedding-3-small` | Embedding model |
| `BRAIN_EMBEDDING_DIMENSIONS` | `1536` | Vector dimensions |
| `BRAIN_DREAM_ENABLED` | `true` | Enable idle dream scheduling |
| `BRAIN_INTAKE_MAX_REQUEST_CHARS` | `100000` | Maximum intake request size |
| `BRAIN_INTAKE_CHUNK_CHARS` | `4000` | Maximum staged chunk size |
| `BRAIN_INTAKE_PROCESSING_BATCH_CHARS` | `12000` | Maximum leased batch size |
| `BRAIN_INTAKE_WORKER_CONCURRENCY` | `1` | Intake worker count |
| `BRAIN_INTAKE_LEASE_SECONDS` | `300` | Lease duration |
| `BRAIN_INTAKE_RETRY_BASE_DELAY_SECONDS` | `5` | Initial retry delay |
| `BRAIN_INTAKE_RETRY_MAX_DELAY_SECONDS` | `3600` | Retry delay cap |
| `BRAIN_INTAKE_POLL_INTERVAL_SECONDS` | `1` | Queue polling interval |
| `BRAIN_INTAKE_SHUTDOWN_GRACE_SECONDS` | `60` | Worker shutdown grace period |
| `BRAIN_DREAM_IDLE_TIMEOUT_MINUTES` | `10` | Idle time before a dream cycle |
| `BRAIN_DREAM_CYCLE_TIMEOUT_MINUTES` | `10` | Maximum time for one dream cycle |
| `BRAIN_DREAM_DELAY_MULTIPLIER` | `1.5` | Dream backoff multiplier |
| `BRAIN_DREAM_MAX_DELAY_MINUTES` | `720` | Maximum dream backoff |
| `BRAIN_DREAM_BATCH_SIZE` | `25` | Nodes per dream cycle |

Pi reads standard provider credentials. For OpenAI, set `OPENAI_API_KEY`.
Embeddings use the official OpenAI TypeScript client. Set `OPENAI_BASE_URL` for
an OpenAI-compatible embedding endpoint.

Changing embedding dimensions after initialization requires a new database.
The HNSW indexes store their configured dimension.

## Local production deployment

The local production service builds the Bun image, mounts `/data`, and listens
on loopback. The rendered service sets `BRAIN_DB_PATH` to the configured active
database under `/data`.

```bash
cp deploy/deploy.env.example deploy/deploy.env
docker build -t second-brain:local .
bash deploy/install.sh
make deploy-status
```

Use `make deploy` for updates and `make deploy-backup` before destructive
operations. The service has no authentication layer, so keep it on loopback or
a trusted network. Follow [`deploy/README.md`](deploy/README.md) and the
[local production manual journey](docs/manual-tests/local-production-server.md).

## Development commands

```bash
make install            # Bun dependencies and pre-commit hooks
make dev                # Bun server with hot reload
make test               # Bun tests
make typecheck          # TypeScript typecheck
make check              # Bun test and typecheck
make build-client       # Go CLI binary
make test-client        # Go tests
make mobile-image       # Pinned Flutter toolchain image
make mobile-check       # Containerized Flutter checks
make docker-build       # Build the Bun image
make docker-up          # Start the production server
make docker-down        # Stop the production Docker server
make clean              # Remove build artifacts
```

The existing `build-mobile`, `test-mobile`, and `analyze-mobile` targets remain
host-toolchain aliases. They are optional and are not part of `make check-all`.
