# Plan: Intake chunk queue

## Context

Replace direct LLM ingestion with synchronous staging and continuous background processing. `POST /ingest` will chunk and embed input into searchable `intake_chunk` rows; an always-on worker will process context-sized batches and delete successful rows. Pending chunks will remain part of recall as explicitly unprocessed evidence.

The brainstorm that established the intent and product decisions is [`docs/brainstorms/intake-chunk-queue.md`](../brainstorms/intake-chunk-queue.md).

## Architecture

### Impacted Modules

#### Core

`Storage` remains the only module that issues SurrealQL. It will own the `intake_chunk` schema, BM25 and HNSW indexes, embedding during staging, queue-row claim/release/delete primitives, queue snapshots, and per-layer search candidates. It will not own retry policy, worker loops, or operator workflow.

The search implementation will replace hard-coded note/entity field selection with a validated search specification for `note`, `entity`, and `intake_chunk`. A multi-table candidate operation will embed a query once, run each table's BM25 and vector paths, and return ranked candidates for one global fusion pass.

`models.py` will add typed shapes for intake requests, chunk records, queue snapshots, unprocessed recall evidence, and recall citations. Existing graph node and edge normalization remains unchanged.

`config.py` will add provider-neutral limits and worker settings: maximum request characters, chunk characters, processing-batch characters, worker concurrency, lease duration, polling interval, retry base delay, retry maximum delay, and dream-pause behavior.

#### Tools

`recall_tools.py` will expose a fixed `search_memory` operation that searches notes, entities, and intake chunks together. It will apply candidate caps and global RRF, label the source layer, and enrich only graph nodes with edge neighborhoods. Intake chunks have no graph enrichment.

`ingest_tools.py` will keep the existing search-and-decide plus `store_knowledge` behavior. It will report write failures through ingest dependencies so the pipeline can decide whether to acknowledge a processing batch. It will not know queue leases or retry timing.

#### Agents

`ingest.py` will keep the DR-001 batched tool-driven agent. Its dependencies will expose per-run outcome state for storage failures. The agent will process the worker's assembled processing batch, not individual queue rows.

A new `IngestionPipeline` module will own chunk preparation orchestration, worker lifecycle, batch packing, lease handling, retry/backoff policy, pause/resume/discard operations, and pipeline snapshots. It will depend on `Storage` and an injected ingest-batch runner adapter. It will not issue raw SQL or duplicate search logic.

`recall.py` will use the fixed `search_memory` tool and cite unprocessed chunk IDs separately from graph node and edge IDs.

`scheduler.py` will remain unchanged as the idle dream scheduler. `POST /ingest` keeps its existing activity signal. The `IngestionPipeline` signals scheduler activity when it starts and completes each processing batch, which pushes the idle timer back while ingestion is active and restarts the idle window after a batch completes. Retry backoff emits no activity, so a long delayed retry can allow a dream cycle. A new ready batch pushes the timer back again.

#### API and integration

`app.py` lifespan will construct and start the `IngestionPipeline`, wire it into all ingest entry points, expose synchronous staging, expose aggregate pipeline operations, and stop the pipeline before closing storage. The existing in-memory ingest job store and job polling routes will be removed.

`mcp.py` will route `ingest` through synchronous staging and report queued chunk counts. Its recall output will include unprocessed citations when present.

The Go client will remove job polling and async ingest types. Its synchronous ingest response will expose the stored chunk count. Go recall/context types will add the separate unprocessed collection while the graph panel continues to render only graph nodes and edges.

### New Modules

#### `IngestionPipeline` (`src/second_brain/agents/ingestion_pipeline.py`)

A deep module with a small application-facing interface. It hides chunking, queue selection, lease recovery, retry backoff, worker task management, batch assembly, and intake controls.

Its implementation will use an injected `IngestBatchRunner` adapter so tests can exercise queue behavior without PydanticAI or a live model. The production adapter wraps the existing ingest agent and records dependency-level write failures. An optional activity callback lets the app wire batch activity to `DreamScheduler.touch_activity` without coupling the pipeline to the scheduler.

The pipeline is an in-app worker pool. The initial concurrency is one, and configuration can increase it. A worker assembles each batch from eligible chunks and sorts chunks from the same intake by `chunk_index` before invoking the runner. Queue selection has no ordering guarantee.

### Interfaces

#### Intake staging

```python
@dataclass(frozen=True)
class IntakeRequest:
    text: str
    hints: tuple[str, ...] = ()
    source: str = "api"
    idempotency_key: str | None = None

@dataclass(frozen=True)
class EnqueueResult:
    chunks_stored: int

async def enqueue(request: IntakeRequest) -> EnqueueResult
```

`enqueue` rejects empty or over-limit input, creates natural-boundary disjoint chunks using the configured character limit, asks `Storage` to embed and persist all chunks, and returns only after every row is searchable. Natural boundaries are preferences, not a requirement to split every short paragraph into a separate row. Persistence is all-or-nothing. An idempotency key collapses duplicate requests only while matching rows remain in the queue. After the final row is deleted, the same key is a new request.

#### Intake chunk persistence

`Storage` will expose queue primitives with these invariants:

```python
async def create_intake_chunks(
    intake_id: str,
    chunks: list[IntakeChunkDraft],
    idempotency_key: str | None,
) -> int

async def claim_intake_batch(
    worker_id: str,
    max_chars: int,
    lease_seconds: float,
) -> ClaimedBatch | None

async def release_intake_batch(
    lease_token: str,
    error: str,
    next_attempt_at: datetime,
) -> None

async def delete_intake_batch(lease_token: str) -> int

async def search_intake_chunks(query: str, k: int) -> list[dict]

async def intake_queue_snapshot() -> IntakeQueueSnapshot
```

A row contains an internal `intake_id`, `chunk_index`, `total_chunks`, `content`, source metadata, embedding, state, attempt count, next-attempt time, lease token, lease expiry, last error, and timestamps. Successful rows are deleted. There is no completed state. `chunk_index` preserves source order for batch assembly and citations, not queue priority.

`claim_intake_batch` atomically selects any eligible ready rows for a processing batch and leases them. Expired leases are eligible for replay. The claim implementation may use one multi-statement SurrealQL query because the installed client does not expose a transaction object across separate calls.

The queue is intentionally at least once. The worker writes organized graph records through the existing agent flow, then deletes the claimed rows. A crash between those effects leaves rows for replay. The replay performs normal hybrid search and matching; later dream cycles can consolidate duplicates.

#### Ingest batch runner

```python
@dataclass
class IngestBatchOutcome:
    completed: bool
    summary: str | None = None
    errors: list[str] = field(default_factory=list)

class IngestBatchRunner(Protocol):
    async def run(
        self,
        text: str,
        hints: list[str],
    ) -> IngestBatchOutcome: ...
```

The production adapter invokes the existing tool-driven ingest agent with the assembled processing batch. Every processing batch receives fresh dependencies and context. No batch receives rolling state from an earlier batch, and the pipeline runs no document-level consolidation pass. `IngestDeps` records unresolved storage errors. The pipeline releases the lease for retry when the agent raises or records an error; it deletes the batch only after a clean run. A crash remains at least once by design.

#### Processing and worker lifecycle

```python
async def start() -> None
async def stop() -> None
async def snapshot() -> PipelineSnapshot
async def pause_intake(intake_id: str) -> None
async def resume_intake(intake_id: str) -> None
async def discard_intake(intake_id: str) -> int
```

Workers claim any eligible ready batches with configurable parallelism. A failed batch returns to the queue after a configured base delay; the delay backs off exponentially to a configured cap. Other ready work proceeds while a failed batch waits. Queue order and fairness are not contracts. At most one processing batch per intake can hold a live lease. Different intakes can run concurrently. Storage and the pipeline accept an optional UTC clock callback for lease and retry decisions. Production uses the current UTC time. Tests advance the injected clock without elapsed-time assumptions. Pause changes ready and retry-wait rows to paused. Resume makes them ready. Discard deletes remaining rows and never rolls back graph records already produced by earlier batches.

The snapshot reports ready, leased, retry-wait, and paused counts; oldest ready/retry time; worker count and active leases; an explicit bounded `stuck_intakes` list; and recent errors with intake identifiers. A stuck intake is a retrying or paused intake surfaced by its age and latest error, not a terminal state. Queue metrics are operational visibility only and do not change the dream scheduler's existing timer policy.

#### Memory recall

`Storage.search_memory_candidates(query: str, k: int) -> MemorySearchCandidates` returns best-first, unfused BM25 and vector lists for `note`, `entity`, and `intake_chunk`. `RankedSearchCandidates` holds the two lists. `MemorySearchCandidates` holds one ranked-candidate value per table. Storage embeds the query once and caps each table/path at `k`. It removes embedding arrays before returning candidates. The tools perform global layer-balanced fusion with RRF offset 60. Each note/entity path has half the weight of each intake path. Thus both memory layers have equal total contribution. `Storage.get_intake_chunks(record_ids: list[str]) -> list[dict]` fetches citation evidence without embeddings and skips deleted records. Intake citation IDs never pass through graph-node or graph-edge fetch operations.

```python
@dataclass
class MemorySearchResult:
    nodes: list[dict]
    unprocessed: list[dict]

async def search_memory(query: str, k: int = 5) -> MemorySearchResult
```

The operation searches `note`, `entity`, and `intake_chunk` candidates, embeds the query once, caps candidates per layer, and performs layer-balanced RRF with equal organized and unprocessed contribution after those caps. It returns graph nodes separately from unprocessed chunks. Recall tools enrich only graph nodes. The recall agent cites `cited_node_ids`, `cited_edge_ids`, and `cited_unprocessed_ids`.

`Context` gains an `unprocessed` collection. The HTTP and MCP response models and Go client mirror that shape. A chunk that disappears between search and citation fetch is skipped without failing the answer. The final result contains at most `k` records across both collections. Organized and unprocessed layers contribute equally, regardless of the organized layer's two tables. Candidate caps apply before fusion. Ranking ties do not define a queue or search ordering contract.

#### HTTP and MCP

```http
POST /ingest
Request: {"text": string, "hints": string[], "source": string?}
Response 200: {"chunks_stored": integer}

GET /ingest/pipeline
Response: aggregate pipeline snapshot

POST /ingest/pipeline/{intake_id}/pause
POST /ingest/pipeline/{intake_id}/resume
POST /ingest/pipeline/{intake_id}/discard
```

The `Idempotency-Key` header is optional. Intake controls identify the selected intake in their response. Discard reports `chunks_discarded`. No graph rollback response field is required. The old `/ingest/jobs/{id}` routes and asynchronous job models are removed. All HTTP, converse, and MCP ingest entry points call the same staging interface. Only the background pipeline invokes the LLM ingest agent.

### Technology Choices

- **Sizing:** Use configurable provider-neutral character limits with a safety margin. Do not add a tokenizer dependency or couple the pipeline to OpenAI tokenization. Keep separate settings for maximum request size, chunk size, and processing-batch size.
- **Queue claim:** Use SurrealDB query-level atomicity for claims and lease updates. Do not add a new queue database or external broker.
- **Agent persistence:** Retain the existing tool-driven agent from DR-001. At-least-once replay plus normal search/deduplication and later dream consolidation is preferred over a structured-output rewrite or a transaction-scoped write-set protocol.
- **Search ownership:** Follow DR-002. `Storage` owns embedding and search mechanics; `recall_tools` owns cross-layer fusion and evidence shaping.

## Tests

**Pre-test-write commit:** `e7cf38a1eb13bdd1aec4f0a97e494ffb771b6575`

### Interface Files

- `src/second_brain/models.py` — typed intake requests, enqueue results, chunk drafts and records, claimed batches, queue and pipeline snapshots, cross-layer memory results, and the unprocessed collection on `Context`.
- `src/second_brain/config.py` — provider-neutral intake limits, lease and polling settings, retry backoff settings, worker concurrency, and dream-pause configuration.
- `src/second_brain/db.py` — queue persistence, lease, deletion, search, citation fetch, multi-table ranked candidates, and snapshot stubs on `Storage`, plus an injectable UTC clock.
- `src/second_brain/agents/ingestion_pipeline.py` — `IngestBatchOutcome`, `IngestBatchRunner`, and the application-facing `IngestionPipeline` lifecycle and intake-control interface. Every operation is a `not implemented` stub.
- `src/second_brain/agents/ingest.py` — per-run storage-error collection on `IngestDeps`.
- `src/second_brain/agents/recall.py` — `cited_unprocessed_ids` on `RecallOutput`.
- `src/second_brain/agents/converse.py` — optional shared staging pipeline dependency.
- `client/internal/types/types.go` — stored chunk counts and separate unprocessed evidence types. Legacy wire fields remain until implementation replaces their consumers.
- `src/second_brain/tools/recall_tools.py` — fixed cross-layer `search_memory` operation stub.

### Test Files

- `tests/test_intake_storage.py` — queue row staging, all-or-nothing embedding, idempotency, claims and lease expiry, retry release, successful deletion, search evidence, and operational snapshots.
- `tests/test_ingestion_pipeline.py` — synchronous chunk enqueueing, request validation, idempotency, ordered batch packing, success deletion, failure retry, independent ready work, intake controls, snapshots, and scheduler activity callbacks.
- `tests/test_intake_recall.py` — separate organized and unprocessed evidence, per-layer caps, balanced fusion, and graph-only enrichment.
- `tests/test_intake_http.py` — synchronous `/ingest`, metadata, validation, staging failures, aggregate visibility, intake controls, and removed job polling.
- `tests/test_intake_mcp.py` — direct configured MCP staging and separate unprocessed citations.
- `tests/test_intake_converse.py` — shared staging dependency, synchronous acknowledgement, errors, and HTTP dependency injection.
- `tests/test_intake_recall_http.py` — separate citation collections, disappearing chunks, and unprocessed-only HTTP/SSE context.
- `client/internal/api/intake_test.go` — chunk-count response propagation and recall/SSE evidence decoding.
- `client/internal/types/intake_test.go` — wire shapes and separate unprocessed evidence.
- `client/internal/tui/intake_test.go` — document chunks stay outside graph rendering.

### Behaviors Covered

#### Intake staging and queue persistence

- Empty and over-limit intake requests are rejected before any rows are stored.
- Natural-boundary, disjoint chunks retain intake identity, source order, source metadata, and hints.
- Every chunk is embedded and searchable before enqueue returns; partial embedding failures leave no rows.
- A matching idempotency key collapses duplicate requests only while queued rows remain. After final deletion, the key is accepted again.
- Queue search returns intake evidence without embedding arrays.

#### Lease and retry primitives

- Claims select eligible contiguous chunks from one intake within the character budget and attach a lease.
- Expired leases become eligible for replay with a new token.
- Failed batches return to retry-wait with the latest error and next-attempt time.
- Successful deletion removes only rows belonging to the acknowledged lease.
- Queue snapshots expose ready, leased, retry-wait, paused, oldest-work, active-lease, worker, stuck-intake, and recent-error visibility.

#### Ingestion pipeline

- `enqueue` returns the number of searchable chunks and preserves request hints and source metadata.
- Workers invoke the injected runner with source-ordered batches bounded by the processing character budget.
- Clean runner outcomes delete claimed rows only after the run completes.
- Failed outcomes release leases for retry while other ready intakes continue.
- Pause and resume change only the selected intake's queue rows. Discard removes remaining rows without rolling back graph records.
- Pipeline snapshots report queue visibility and worker health. Batch start and completion emit activity callbacks.

#### Memory recall

- One search result separates organized graph nodes from explicitly unprocessed intake chunks.
- Candidate caps apply before balanced cross-layer fusion.
- Only graph nodes receive edge-neighborhood enrichment. Intake chunks remain edge-free evidence.

#### HTTP and MCP

- `POST /ingest` returns `200` with `chunks_stored` only after synchronous staging and accepts optional source and idempotency metadata.
- `GET /ingest/pipeline` exposes aggregate queue counts and bounded operational errors.
- Pause, resume, and discard routes expose intake controls. Discard does not report graph rollback.
- MCP ingest reports queued chunk counts rather than an asynchronous job receipt.

### Reviewed Behaviors

The approved review expands the contract to deterministic capped retries, raised and recorded failures, multi-batch independence, per-intake lease exclusion, cross-intake concurrency, in-flight idempotency, immediate evidence deletion, graph retention, graceful shutdown, and activity-free retry waiting. Search tests cover one query embedding, adversarial candidate caps, normalized global RRF, a final total `k`, and graph-only enrichment. Integration tests cover all ingest entry points and citation disappearance. Natural-boundary tests enforce disjoint content and size limits without prescribing a split for every short paragraph.

### Red Gate

The reviewed Python contract contains **104 tests: 98 fail and 6 pass**. All collect without errors. Passing cases cover existing request validation and MCP callback forwarding. The full Python suite reports **265 passed and 157 failed**, including the same **59 pre-existing failures**. All queue/pipeline/search behavior remains red against interface stubs. `go test ./...` has one expected failure: the current ingest client drops `chunks_stored`. Other Go packages pass. Ruff, Basedpyright, and commit hooks validate the interface changes.

**Review status:** approved
