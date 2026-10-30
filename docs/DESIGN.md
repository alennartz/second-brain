# Design Document

Living design document for Second Brain. Feature plans and historical designs live
in `docs/plans/`. This document describes the current architecture and its
reasons.

---

## Vision

Second Brain stores, connects, and retrieves knowledge for people and agents. It
stages source text for immediate search, then organizes that evidence in a graph.

## Architectural Principles

### Small, single-process deployment

The Bun server runs in one process and stores data in an embedded SurrealKV
database. This avoids a separate database service. The server owns the fresh
schema and indexes. It does not migrate databases from the former server.

### Deterministic staging, agent-led organization

Intake staging chunks, embeds, and stores source text before the HTTP request
returns. A background worker leases ordered chunks and runs the ingest workflow.
Each successful graph mutation commits independently. A failed batch can retry
without holding a database transaction during model requests.

Recall searches both organized graph records and unprocessed intake evidence. It
uses a bounded agent loop and returns only validated answers with citations. The
HTTP layer resolves those citations against current storage before it returns
context.

The dream scheduler runs graph refinement after activity settles. It performs
deduplication before connection discovery, then tracks convergence and backs off
until new activity.

### Explicit agent capabilities

Pi provides request-scoped file-backed agent sessions. Transcripts live in
server-owned per-workflow directories and do not carry context between runs. The ingest, recall, and
dream workflows each receive a closed set of domain tools. Direct tools and
Codemode share validated structured results. The runtime disables built-in
filesystem, shell, network, MCP, and persistent-resource capabilities. Codemode
cannot access the model catalog.

### Storage owns search and database details

Storage owns embeddings on writes, lexical and vector candidate retrieval,
search fusion, SurrealDB transactions, schema initialization, and SDK value
normalization. Workflows and knowledge tools use plain domain values. They do
not issue SurrealQL or depend on SurrealDB SDK records.

### Stable HTTP boundary

Elysia exposes the non-conversation HTTP API used by the Go and Flutter clients.
TypeBox schemas validate request and response boundaries. Route handlers depend
on application interfaces, not on Pi or storage implementations. The server does
not expose conversation or MCP routes.

## Data Model

Organized knowledge uses two node kinds:

- **Note** — source-derived knowledge with content, summary, source, timestamps,
  and an embedding.
- **Entity** — a named concept with a type, description, timestamps, and an
  embedding.

Directed, named edges connect graph nodes. The `references` relation links notes
to entities. Other edge types describe knowledge relationships and remain
explicit graph records.

Before organization, intake documents consist of ordered, searchable document
chunks outside the graph. Recall returns these chunks separately as unprocessed
evidence. A clean processing batch removes its chunks after the workflow has
organized them.

The fresh TypeScript-owned SurrealDB schema defines graph records, queue state,
search indexes, and vector indexes. Public domain records omit embeddings and
operational queue metadata.

## Workflows

### Ingest and intake pipeline

The HTTP intake path validates and stages source text synchronously. The
background pipeline leases contiguous eligible chunks, renews ownership, and
runs the ingest workflow. Ingest can search existing knowledge, create singular
nodes and edges, and make exact field edits. Each mutation commits before the
agent continues. The pipeline acknowledges a batch only after a clean run and
releases failed or canceled work for retry. Known node-field validation failures
pause the intake before release so a deterministic model error cannot replay
successful writes indefinitely.

### Recall

Recall uses bounded search and graph-inspection tools. It collects evidence in
the request session and accepts an answer only through a validated citation
tool. The application resolves cited nodes, edges, and intake chunks against
live storage before returning the answer. It returns unprocessed evidence
separately from graph context.

### Dream

Dream has two request-scoped sessions: deduplication and connection discovery.
Deduplication can merge nodes and edges, make exact edits, remove edges, and
rename edge types. Connection discovery can find shared-note co-occurrences and
create edges. The scheduler runs deduplication first, cancels on new activity,
limits repeated idle cycles through convergence tracking, and fails a cycle
that exceeds its configured timeout.

## Search and Embeddings

Storage combines BM25 lexical search with vector similarity through reciprocal
rank fusion. It searches graph nodes and unprocessed chunks, then returns
bounded candidates. Embeddings use the official OpenAI TypeScript client and
remain independent of Pi chat model selection. The configured model and vector
dimensions must match the fresh database indexes.

## Provider Configuration

The server requires one Pi model reference for each workflow:

- `BRAIN_INGEST_MODEL`
- `BRAIN_RECALL_MODEL`
- `BRAIN_DREAM_MODEL`

Each value uses `provider/model:effort`. Pi's standard provider configuration
supplies credentials and model definitions. `BRAIN_EMBEDDING_MODEL` and
`BRAIN_EMBEDDING_DIMENSIONS` configure the separate embedding adapter. See the
root README for environment settings and defaults.

## HTTP API

The server exposes health, intake, pipeline controls, recall, dream jobs, and
graph lookup:

- `GET /health`
- `POST /ingest`
- `GET /ingest/pipeline`
- `POST /ingest/pipeline/:intake_id/pause`
- `POST /ingest/pipeline/:intake_id/resume`
- `POST /ingest/pipeline/:intake_id/discard`
- `POST /recall`
- `POST /search`
- `POST /graph/refresh`
- `POST /dream` and `GET /dream/jobs/:job_id`
- `GET /graph/:record_id`

`POST /ingest` supports permanent idempotency keys. Replaying a key with the
same content returns the original chunk count, including after its chunks are
processed or discarded. Replaying the key with different content returns
`409`. `POST /search` returns graph nodes and unprocessed chunks without
answer generation. `POST /graph/refresh` refreshes up to 200 graph nodes in one
request. `POST /dream` returns an asynchronous job location.

## Clients

Second Brain has a Go CLI and TUI and an Android-first Flutter app. They use the
HTTP API and remain separate from server implementation code. The Go client
supports intake, recall, and graph operations. The mobile app supports offline-
first Capture with a per-profile outbox, saved Ask answer snapshots, and a
per-profile graph workspace for search and exploration. Brain profiles,
captures, answers, and workspaces persist locally. Access credentials use
platform secure storage.

Explore is graph-first. Search matches appear directly on the canvas while their
connections load in the background. Following nodes and edges stays on the map.
The Details action opens the separate drill-down view. Evidence links also enter
the map. Memory labels use names, summaries, or human fallbacks, never database
record IDs.

## Development and Deployment

Bun manages server dependencies, runs the server and tests, and builds the
production image. `bun test` covers unit, integration, HTTP, fresh-database, and
tool-contract behavior. Runtime tests use deterministic transports where they
do not need external providers. Go and Flutter clients keep their own toolchains.

Docker Compose provides the server and separate test and mobile profiles with
isolated database volumes. The local production deployment builds the Bun image,
mounts persistent data, binds to loopback, and archives the active database
before updates. See `deploy/README.md` for installation, reset, backup, and
restore procedures.
