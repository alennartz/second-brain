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

## Steps

**Pre-implementation commit:** `ddf80cc552dead6f41fe02f079981b27c927e5f2`

### Planning Decisions

The user approved these scope decisions during planning:

- **Jev stays out of scope.** `run_converse_turn` and `agents/routing.py` stay stubbed. Do not change Jev tests. `test_intake_converse.py::test_converse_ingest_stages_original_text_without_calling_old_agent[fast]` stays red until the `jev-converse-routing` topic lands. The Jev tests `test_run_converse_turn_fast_ingest_matches_converse_tool_path` and `test_http_converse_uses_routing_and_preserves_response_contract[ingest-*]` expect the old ingest agent. The Jev topic owns their update.
- **Delete obsolete tests instead of keeping code for them.** Remove job-polling tests, legacy ingest-agent guards that patch removed symbols, and the `--wait` CLI test. Do not keep compatibility imports or functions for tests.
- **Remove `pause_dream`.** Scheduler interaction uses `activity_callback` only.

Findings from the code that shape the steps:

- The `surrealdb` 1.0.8 embedded engine returns `"... read or write conflict. This transaction can be retried"` for concurrent `BEGIN … COMMIT` blocks. It does not detect phantom inserts. A `SELECT … WHERE idempotency_key = $key` guard lets two concurrent stagings insert. A deterministic record ID (`intake_key:⟨key⟩`) does conflict.
- `AsyncSurreal.query` returns only the first statement result. Multi-statement transactions need `query_raw`. Its result list omits `BEGIN`/`COMMIT`, so the final entry is the trailing `RETURN`. A `THROW` marks statements with `status: "ERR"`.
- Embedded datetimes round-trip as timezone-aware `datetime` values. `make_serializable` emits ISO strings with `+00:00`.
- HNSW search omits deleted rows at once.

Pre-existing failures (59 Jev tests in `test_converse_agent.py`, `test_converse_routing_http.py`, `test_routing.py`) remain after this plan.

### Step 1: Remove `pause_dream`

In `src/second_brain/config.py`, delete `intake_pause_dream`. In `src/second_brain/agents/ingestion_pipeline.py`, delete the `pause_dream` keyword parameter and the `self.pause_dream` attribute from `IngestionPipeline.__init__`.

**Verify:** `rg pause_dream src tests` returns nothing. `uv run basedpyright src/` passes.
**Status:** done

### Step 2: Intake schema and search specification in `Storage`

In `src/second_brain/db.py`:

- Extend `init_schema` with a `SCHEMALESS` `intake_chunk` table. Define fields: `intake_id` (string), `chunk_index` (int), `total_chunks` (int), `content` (string), `source` (string), `hints` (array<string>), `embedding` (option<array<float>>), `state` (string), `attempt_count` (int, default 0), `next_attempt_at`, `lease_token`, `lease_expires_at`, `worker_id`, `last_error`, `idempotency_key` (all `option<…>`), `created_at`, and `updated_at` (datetime). Do not use `time::now()` defaults for queue timestamps. Staging writes them from the injected clock.
- Add indexes: `intake_chunk_content_fts` (BM25 on `content` with `simple_analyzer`), a plain index on `intake_id`, and a plain index on `state`. Add `intake_chunk_embedding_hnsw` in `init_vector_indexes`.
- Define a `SCHEMALESS` `intake_key` table. Its record ID is the idempotency key, and it holds `intake_id`.
- Add a module constant `_SEARCH_FIELDS: dict[str, str] = {"note": "content", "entity": "name", "intake_chunk": "content"}`. Add private helpers `_vector_candidates(table, embedding, k)` and `_fulltext_candidates(table, query, k)`. They validate `table` against `_SEARCH_FIELDS` (raise `ValueError` otherwise). They return normalized records without `embedding` or `score`, with a `table` key (use `normalize_node`).
- Rewrite `hybrid_search`, `vector_search`, and `fulltext_search` on these helpers. Move the existing RRF loop into a private pure function `_rrf_fuse(paths: list[list[dict]], k: int) -> list[dict]`. Keep public signatures and behavior unchanged.

**Verify:** `uv run pytest tests/test_db.py tests/test_storage.py tests/test_recall_tools.py` passes. `Storage("mem://", …).init()` succeeds twice on the same connection (idempotent schema).
**Status:** done

### Step 3: Transaction helper and atomic staging

In `src/second_brain/db.py`:

- Add a private exception `_RetryableConflict(RuntimeError)`. Add `async def _run_transaction(self, sql: str, vars: dict, context: str) -> Any`. It calls `self._db.query_raw` and inspects every statement result. It raises `_RetryableConflict` when any `ERR` result contains `"can be retried"` or a plan-specific `THROW` marker such as `"intake_conflict"`. It raises `RuntimeError(f"{context}: …")` for other errors. Otherwise it returns the last statement's `result`.
- Add `async def _retry_transaction(self, attempt: Callable[[], Awaitable[T]], attempts: int = 8) -> T`. It re-runs `attempt` on `_RetryableConflict` and re-raises after the last attempt. A short jittered `asyncio.sleep` between attempts is allowed.
- Implement `create_intake_chunks(intake_id, chunks, idempotency_key) -> int`:
  1. Return `0` when `chunks` is empty.
  2. When `idempotency_key` is set and an `intake_key:⟨key⟩` record exists, return `0` before embedding.
  3. Embed all chunk contents with one `self._embedder.embed_batch` call. An embedding error propagates, and no row exists.
  4. In one transaction (via `_retry_transaction`), `CREATE type::thing('intake_key', $key)` when a key is set, then create every row with `state = 'ready'`, `attempt_count = 0`, `created_at` and `updated_at` from `self._clock()`, hints as a list, and `idempotency_key`. Return the created count.
  5. Treat a `CREATE` "already exists" failure on the key record as a duplicate and return `0`. A retried conflict re-runs from the transaction. It sees the winner's key and returns `0`.

**Verify:** These tests in `tests/test_intake_storage.py` pass: `test_create_intake_chunks_persists_every_chunk_and_returns_count`, `test_create_intake_chunks_is_all_or_nothing_when_embedding_fails`, and `test_concurrent_idempotent_staging_stores_one_intake`. They also need Step 5 search and Step 6 snapshot.
**Status:** done

### Step 4: Claim, release, and delete leases

In `src/second_brain/db.py`:

- Add a module-level pure function:

  ```python
  def _select_claim(
      rows: list[dict], now: datetime, max_chars: int
  ) -> tuple[str, list[Any]] | None
  ```

  `rows` hold `id`, `intake_id`, `chunk_index`, `state`, `next_attempt_at`, `lease_expires_at`, `created_at`, and `chars`. A row is *eligible* when `state == "ready"`, or `state == "retry_wait"` with `next_attempt_at <= now`, or `state == "leased"` with `lease_expires_at <= now`. An intake is *claimable* when no row holds a live lease (`leased` with `lease_expires_at > now`) and its lowest-`chunk_index` row is eligible. Pick any claimable intake. Prefer the oldest `created_at`, but ordering is not a contract. Take ascending eligible rows from the head while the cumulative `chars` stays within `max_chars`. Always take the head row. Stop at the first non-eligible row. Return the intake ID and the raw record IDs.
- Implement `claim_intake_batch(worker_id, max_chars, lease_seconds) -> ClaimedBatch | None` as a retry loop (`_retry_transaction`):
  1. Read every queue row with `SELECT id, intake_id, chunk_index, state, next_attempt_at, lease_expires_at, created_at, string::len(content) AS chars FROM intake_chunk`.
  2. Call `_select_claim` with `now = self._clock()`. Return `None` when it returns `None`.
  3. Run one transaction. It `THROW`s the conflict marker when the intake now has a live lease or when any selected row is no longer eligible. Otherwise it sets `state = 'leased'`, a new `lease_token` (`uuid4().hex`), `lease_expires_at = now + lease_seconds`, `worker_id`, and `updated_at = now`. It returns the updated rows.
  4. Return `None` after the retries run out. A claim conflict is not an error for workers.
  5. Return `ClaimedBatch(lease_token, intake_id, chunks)`. `chunks` holds normalized dicts sorted by `chunk_index`, without `embedding`, with `table`.
- Implement `release_intake_batch(lease_token, error, next_attempt_at)`. Update only rows with `lease_token = $token AND state = 'leased'`. Set `state = 'retry_wait'`, `last_error`, `next_attempt_at`, `attempt_count += 1`, `lease_token = NONE`, `lease_expires_at = NONE`, and `updated_at = now`.
- Implement `delete_intake_batch(lease_token) -> int` in one transaction. Delete rows with `lease_token = $token AND state = 'leased'`, and count them. When no row remains for that intake, delete its `intake_key` records. A stale token matches nothing and returns `0`.

**Verify:** These tests in `tests/test_intake_storage.py` pass: the claim, lease-expiry, stale-lease, release, retry-head, delete, and idempotency tests (`test_idempotency_key_*`, `test_claim_*`, `test_concurrent_claims_*`, `test_stale_lease_*`, `test_release_*`, `test_delete_intake_batch_*`).
**Status:** done

### Step 5: Intake evidence fetch and search candidates

In `src/second_brain/db.py`:

- Implement `get_intake_chunks(record_ids) -> list[dict]`. Skip IDs that fail `validate_record_id` or whose table is not `intake_chunk`. Fetch the rest with `OMIT embedding`. Skip missing rows. Return normalized dicts with `table`.
- Implement `search_intake_chunks(query, k) -> list[dict]`. Embed once, run `_vector_candidates` and `_fulltext_candidates` on `intake_chunk`, and fuse with `_rrf_fuse`. Return all states, at most `k`, without embeddings. Workers and tests rely on this search to see every queued row when vectors match.
- Implement `search_memory_candidates(query, k) -> MemorySearchCandidates`. Call `self._embedder.embed(query)` exactly once, even when tables are empty. For each of `note`, `entity`, and `intake_chunk`, build `RankedSearchCandidates(bm25=…, vector=…)` from the helpers, capped at `k`. Do not fuse.

**Verify:** `test_get_intake_chunks_*`, `test_search_intake_chunks_*`, and `test_search_memory_candidates_*` in `tests/test_intake_storage.py` pass.
**Status:** done

### Step 6: Queue snapshot and intake controls in `Storage`

In `src/second_brain/db.py`:

- Add a module-level pure function `_summarize_queue(rows: list[dict], now: datetime) -> IntakeQueueSnapshot`. It counts rows by `state`. It sets `oldest_ready_at` to the minimum `created_at` of `ready` rows and `oldest_retry_at` to the minimum `next_attempt_at` of `retry_wait` rows. `active_leases` counts distinct `lease_token` values on live leases. `worker_count` stays `0`. `stuck_intakes` holds one entry per intake with `retry_wait` or `paused` rows: `{"intake_id", "state", "attempt_count", "last_error", "since"}`. Sort it oldest first and cap it at 100. `recent_errors` holds one entry per intake with a `last_error`: `{"intake_id", "error", "at"}`. Sort it by `updated_at` ascending, so the newest is last, and cap it at 20. Emit timestamps as `datetime`.
- Implement `intake_queue_snapshot()`. Select queue rows without `content` or `embedding`, then return `_summarize_queue(rows, self._clock())`.
- Add `async def set_intake_paused(self, intake_id: str, paused: bool) -> int`. Pausing moves `ready` and `retry_wait` rows to `paused`. Resuming moves `paused` rows to `ready` and clears `next_attempt_at`. Leased rows stay unchanged. Return the number of rows updated.
- Add `async def delete_intake(self, intake_id: str) -> int`. In one transaction, delete every row of the intake and its `intake_key` records. Return the deleted row count.

**Verify:** `uv run pytest tests/test_intake_storage.py` passes in full.
**Status:** done

### Step 7: Chunking and retry policy functions

In `src/second_brain/agents/ingestion_pipeline.py`, add two module-level pure functions:

```python
def split_intake_text(text: str, max_chars: int) -> list[str]: ...
def retry_delay(failed_attempts: int, base: float, cap: float) -> float: ...
```

`split_intake_text` partitions `text.strip()` into verbatim, in-order slices. Each slice holds at most `max_chars` characters and some non-whitespace content. The slices concatenate back to the stripped text, except for dropped whitespace-only pieces. It prefers paragraph boundaries (blank lines), then sentence boundaries (`.`, `!`, `?` followed by whitespace). Separator whitespace stays attached to the preceding unit. Greedy packing puts several small units in one chunk when they fit. A unit longer than `max_chars` splits at its last whitespace within the limit, or at the limit when no whitespace exists.

`retry_delay` returns `min(base * 2 ** (failed_attempts - 1), cap)`. The sequence for base 2 and cap 5 is 2, 4, 5, 5.

**Verify:** The functions are pure and importable. The behavior surfaces through Step 8's enqueue tests.
**Status:** not started

### Step 8: `IngestionPipeline` staging, snapshot, and controls

In `src/second_brain/agents/ingestion_pipeline.py`:

- `enqueue(request)`: Raise `ValueError` when `request.text.strip()` is empty or `len(request.text) > max_request_chars`, before any embedding. Chunk with `split_intake_text(request.text, chunk_chars)`. Generate `intake_id = uuid4().hex`. Build `IntakeChunkDraft` values with `chunk_index`, `total_chunks`, `source`, and `hints` from the request. Return `EnqueueResult(chunks_stored=await storage.create_intake_chunks(intake_id, drafts, request.idempotency_key))`.
- `snapshot()`: Read `storage.intake_queue_snapshot()`. Return a `PipelineSnapshot` with the same fields and `worker_count` set to the number of running worker tasks (`0` when stopped).
- `pause_intake` and `resume_intake` call `storage.set_intake_paused(intake_id, True/False)`. `discard_intake` returns `storage.delete_intake(intake_id)`.

**Verify:** These tests in `tests/test_ingestion_pipeline.py` pass: `test_enqueue_*`, `test_idempotency_key_collapses_duplicate_requests_while_queued`, `test_concurrent_idempotent_requests_stage_one_intake`, and the `ready` case of `test_pause_and_resume_change_only_the_selected_intake`.
**Status:** not started

### Step 9: Worker pool lifecycle

In `src/second_brain/agents/ingestion_pipeline.py`, add private instance state: a list of worker tasks and an `asyncio.Event` for stopping. This lifecycle state stays private to the pipeline instance.

- `start()`: Do nothing when workers already run. Otherwise clear the stop event and create `worker_concurrency` tasks running `_worker_loop(worker_id)`, with worker IDs `f"{pipeline_id}-{n}"`.
- `stop()`: Set the stop event, await every worker task without cancelling it, then clear the task list. Stop does nothing when the pipeline never started.
- `_worker_loop`: Until stop is set, call `storage.claim_intake_batch(worker_id, processing_batch_chars, lease_seconds)`. With no batch, wait on the stop event for `poll_interval_seconds` and loop again. Catch and log storage exceptions so a worker never dies. With a batch, call `_process_batch(batch)`, then loop. Check the stop event before each claim.
- `_process_batch(batch)`:
  1. Call `activity_callback()` when it is set.
  2. Build `text = "".join(chunk["content"] for chunk in batch.chunks)`. The chunks are already in `chunk_index` order. Build a fresh `hints = list(batch.chunks[0]["hints"])` for each batch.
  3. Await `runner.run(text, hints)`. A clean run is `outcome.completed and not outcome.errors`.
  4. After a clean run, call `storage.delete_intake_batch(batch.lease_token)`. Otherwise compute an error message: the joined `outcome.errors`, `str(exc)` for an exception, or `"ingest batch did not complete"`. Then set `failed = max(chunk["attempt_count"]) + 1` and call `storage.release_intake_batch(token, message, clock() + timedelta(seconds=retry_delay(failed, base, cap)))`.
  5. Call `activity_callback()` again after delete or release. Log delete and release exceptions. The lease expires and the batch replays.
  6. Never pass summaries or state from one batch to the next.

**Verify:** `uv run pytest tests/test_ingestion_pipeline.py` passes in full. This covers packing, independence, success deletion, unclean runs, capped retries, cross-intake concurrency, pause in `retry_wait`, discard, snapshots, graceful stop, and activity callbacks.
**Status:** not started

### Step 10: Cross-layer `search_memory`

In `src/second_brain/tools/recall_tools.py`:

- Add a pure function `fuse_memory_candidates(candidates: MemorySearchCandidates, k: int) -> list[dict]`. Slice each of the six paths to `[:k]`. Score each record ID with `weight / (60 + rank + 1)`, using weight `0.5` for `note`/`entity` paths and `1.0` for `intake_chunk` paths, and sum the scores across paths. Sort by descending score (stable on first-seen order), and return the top `k` records. Each record carries `table` (`normalize_node`).
- Implement `search_memory(storage, query, k)`. Call `storage.search_memory_candidates(query, k)` once and fuse. Copy `intake_chunk` records into `unprocessed` with `"unprocessed": True` and no `connections`. Enrich the other records once each with `enrich_with_connections` into `nodes`. Return `MemorySearchResult(nodes, unprocessed)`. Do not call `hybrid_search`, `search_intake_chunks`, `vector_search`, or `fulltext_search`.

**Verify:** `uv run pytest tests/test_intake_recall.py tests/test_recall_tools.py` passes.
**Status:** not started

### Step 11: Write-failure reporting and the production batch runner

- `src/second_brain/tools/ingest_tools.py`: Add a `"storage_errors": list[str]` key to the `store_knowledge` return dict. It holds the "Note creation failed" and "Edge creation failed" messages. Keep them in `"errors"` too, so the agent still sees them. Reference-resolution errors stay agent feedback only.
- `src/second_brain/agents/ingest.py`: In the `store_knowledge` tool, extend `ctx.deps.storage_errors` with `result["storage_errors"]`. In the `except` branches of `store_knowledge` and `update_node`, append the error message to `ctx.deps.storage_errors`. Read-tool failures do not record errors.
- `src/second_brain/agents/ingest.py`: Add the production adapter:

  ```python
  class AgentIngestBatchRunner:
      def __init__(self, agent: Agent[IngestDeps, str], storage: Storage, model: Model | str) -> None: ...
      async def run(self, text: str, hints: list[str]) -> IngestBatchOutcome: ...
  ```

  `run` builds the prompt (`"Possibly related nodes: …\n\n{text}"` when `hints` is not empty, as the old `app.run_ingest_agent` did). It runs the agent with a fresh `IngestDeps(storage=…)` and returns `IngestBatchOutcome(completed=True, summary=result.output, errors=list(deps.storage_errors))`. Agent exceptions propagate to the pipeline. Import `IngestBatchOutcome` from `second_brain.agents.ingestion_pipeline`.

**Verify:** `uv run pytest tests/test_ingest_agent.py tests/test_store_knowledge.py tests/test_ingest_tools.py` passes. `uv run basedpyright src/` passes with no import cycle.
**Status:** not started

### Step 12: Recall agent search tool and citation fetch

In `src/second_brain/agents/recall.py`:

- Replace the `search_knowledge` tool body and signature with `search_knowledge(ctx, query: str, k: int = 5) -> dict`. It returns `{"nodes": …, "unprocessed": …}` from `recall_tools.search_memory`. Keep the tool name so `_RECALL_STATUS` and `tests/test_recall_agent.py` still match. On error, return `{"error": str(e)}`.
- Update the system prompt. Results hold organized graph nodes and unprocessed intake chunks. Unprocessed evidence is raw source text not yet organized. `get_node` applies to graph nodes only. Cite chunk IDs in `cited_unprocessed_ids`, never in `cited_node_ids`.
- Add a shared helper:

  ```python
  async def fetch_cited_context(storage: Storage, output: RecallOutput) -> Context
  ```

  It filters `cited_node_ids` to `note`/`entity` IDs and fetches them with `storage.get_nodes`. It fetches each `cited_edge_ids` entry with `storage.get_edge`, skipping `ValueError` and empty results. When `cited_unprocessed_ids` is not empty, it calls `storage.get_intake_chunks(cited_unprocessed_ids)` and marks each chunk with `"unprocessed": True`. Deleted chunks are skipped. It returns `Context` with normalized nodes and edges plus the unprocessed list.

**Verify:** `uv run pytest tests/test_recall_agent.py` passes. Steps 13 and 15 exercise the helper.
**Status:** not started

### Step 13: Converse staging and unprocessed context

In `src/second_brain/agents/converse.py`:

- Remove `_INGEST_STATUS`, the `_ingest_agent` creation, and the `IngestDeps`/`create_ingest_agent` imports.
- Add a module-level helper `async def stage_converse_ingest(deps: ConverseDeps, text: str) -> str`. It lets the Jev topic reuse the staging path later. When `deps.ingestion_pipeline` is `None`, return `"Intake staging is unavailable."` without other effects. Otherwise push a "Staging intake..." status and await `deps.ingestion_pipeline.enqueue(IntakeRequest(text=text, source="converse"))`. Exceptions propagate. Push `f"Queued {n} chunks as unprocessed intake"` and return a message like `f"Queued {n} chunks for background processing. They are searchable now as unprocessed evidence."`. Do not touch `deps.context` or `deps.storage`.
- Make the `ingest` tool call `stage_converse_ingest`. Update its docstring.
- Make the `recall` tool use `fetch_cited_context`. Merge nodes, edges, and `unprocessed` onto `deps.context`, deduplicated by `id`.
- Edit `tests/test_intake_converse.py` (user-approved). Remove the `create_ingest_agent` monkeypatch, the `legacy_ingest` mock, and every `legacy_ingest.run.assert_not_awaited()`. The fixture returns `(pipeline, storage)`. Remove the unused `converse_module` import.

**Verify:** `uv run pytest tests/test_intake_converse.py tests/test_converse_agent.py::test_converse_agent_runs tests/test_converse_agent.py::test_converse_agent_has_tools` passes, except the `[fast]` case and the HTTP cases that need Step 15. `[fast]` stays red because of the Jev stub.
**Status:** not started

### Step 14: MCP staging acknowledgement and citations

In `src/second_brain/mcp.py`:

- `ingest` awaits `_run_ingest(text, hints)`, which returns an `EnqueueResult`. It returns `f"Queued {result.chunks_stored} chunks as unprocessed intake. They are searchable now and will be organized in the background."`. Update the docstring.
- `recall` keeps the `Cited nodes:` line for graph nodes. It adds an `Unprocessed evidence: <ids>` line when `result.context.unprocessed` is not empty. Never mix the two ID sets.
- Edit `tests/test_intake_mcp.py` (user-approved). Remove the `app_module.run_ingest_agent` monkeypatch, the `legacy_ingest` mock, and its assertion. Adjust the fixture tuple and remove the unused `app_module` import if nothing else uses it.

**Verify:** `uv run pytest tests/test_intake_mcp.py tests/test_mcp.py` passes.
**Status:** not started

### Step 15: App wiring, routes, and job removal

In `src/second_brain/app.py`:

- Add a module global `_ingestion_pipeline: IngestionPipeline | None = None`.
- In `lifespan`, after storage init and scheduler setup, construct `IngestionPipeline`. Pass `storage=_storage` and `runner=AgentIngestBatchRunner(_ingest_agent, _storage, _model)`. Read the limits and worker settings from the `settings.intake_*` values. Pass `activity_callback=_scheduler.touch_activity` when a scheduler exists. Then `await _ingestion_pipeline.start()`. Include the pipeline in the startup failure cleanup. On shutdown, `await _ingestion_pipeline.stop()` before stopping the scheduler and closing storage.
- Delete `run_ingest_agent`, `IngestJobResponse`, `_ingest_jobs`, and the `GET /ingest/jobs/{job_id}` route. Keep `JobStatus` and `_background_tasks` for dream jobs.
- Request and response models: `IngestRequest` gains `source: str = "api"`. `IngestResponse` becomes `chunks_stored: int`.
- `POST /ingest` returns 200 with `response_model=IngestResponse`. It reads the optional `Idempotency-Key` header (`Header(alias="Idempotency-Key")`). It touches scheduler activity, then awaits `_ingestion_pipeline.enqueue(IntakeRequest(text=req.text, hints=tuple(req.hints), source=req.source, idempotency_key=key))`. It maps `ValueError` to `HTTPException(400)` and lets other errors become 500s.
- `GET /ingest/pipeline` returns `await _ingestion_pipeline.snapshot()` (a dataclass that FastAPI serializes). `POST /ingest/pipeline/{intake_id}/pause` and `/resume` return `{"intake_id": intake_id}`. `/discard` returns `{"intake_id": intake_id, "chunks_discarded": n}`. These routes return 503 when the pipeline is `None`, and they touch no `Storage` method.
- Add `async def stage_mcp_ingest(text: str, hints: list[str] | None = None) -> EnqueueResult`. It enqueues `IntakeRequest(text=text, hints=tuple(hints or ()), source="mcp")`. Pass it to `configure_mcp(run_ingest=…)`.
- `run_recall_agent` uses `fetch_cited_context`. It returns `context=None` when nodes, edges, and unprocessed are all empty. Log the unprocessed citation count.
- Both converse endpoints build `ConverseDeps(..., ingestion_pipeline=_ingestion_pipeline)`. They keep `deps.context` when nodes, edges, or unprocessed are not empty.
- Edit `tests/test_app.py` (user-approved). Delete `test_ingest_returns_202_with_location`, `test_ingest_job_completes`, `test_ingest_with_hints`, and `test_ingest_job_not_found`. Edit `tests/test_intake_http.py`. Remove the `app_module.run_ingest_agent` monkeypatch line. Keep the `_ingest_agent` patch, which still guards that `POST /ingest` never runs the agent.

**Verify:** `uv run pytest tests/test_intake_http.py tests/test_intake_recall_http.py tests/test_intake_converse.py tests/test_intake_mcp.py tests/test_app.py` passes, except `test_intake_converse.py::…[fast]`. Starting the server with `BRAIN_TEST_MODE=true` and running `POST /ingest` returns `{"chunks_stored": n}`, and `GET /ingest/pipeline` shows the rows drain.
**Status:** not started

### Step 16: Go client synchronous ingest

In `client/`:

- `internal/types/types.go`: Remove `Summary` from `IngestResponse`. Remove `JobStatus`, its constants, and `IngestJobResponse`.
- `internal/api/client.go`: `IngestWithTimeout` performs one `c.post("/ingest", types.IngestRequest{…}, &resp, timeout)` and returns `&resp`. `Ingest` keeps `ingestTimeout`. Delete `SubmitIngest`, `submitIngest`, `awaitIngestJob`, `getIngestJob`, `submitTimeout`, the poll constants, and the doc text about job polling. Remove imports that become unused.
- `cmd/brain/ingest.go`: Remove the `--wait` flag and the job-submit branch. Keep `--timeout` for the synchronous POST. Print `Queued N chunks for background ingestion.`
- Tests (user-approved): Delete `TestIngest`, `TestIngestJob`, and `TestIngestJobFailed` from `internal/api/client_test.go`. `intake_test.go` covers synchronous ingest. Delete `TestIngestCommandNoWait`. Rewrite `TestIngestCommand`: the server returns `{"chunks_stored":3}`, the args omit `--wait`, and the output contains `3`. In `e2e/e2e_test.go`, `TestIngest` asserts `resp.ChunksStored > 0` instead of a summary.
- The TUI needs no change. `types.Context.Unprocessed` already exists, and the TUI intake tests pass.

**Verify:** `cd client && go test ./... && go vet -tags e2e ./... && golangci-lint run` pass.
**Status:** not started

### Step 17: Full verification

Run `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run basedpyright src/`, `uv run pytest`, and `cd client && go test ./...`.

**Verify:** Ruff, Basedpyright, and Go pass. Pytest fails only the 59 pre-existing Jev tests plus `tests/test_intake_converse.py::test_converse_ingest_stages_original_text_without_calling_old_agent[fast]`. All other intake tests pass.
**Status:** not started
