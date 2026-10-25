# Plan: TypeScript server rewrite

## Context

Replace the Python server with a Bun-native TypeScript server using the Pi TypeScript SDK. Start with an empty database managed by the latest compatible SurrealDB stack and preserve the non-conversation HTTP service, while removing MCP and conversation mode. The completed TypeScript server is cut over as one replacement; the old service remains available only until the fresh-schema and behavior gate passes. The brainstorm is recorded in [`docs/brainstorms/typescript-server-rewrite.md`](../brainstorms/typescript-server-rewrite.md).

## Architecture

### Impacted Modules

- **Core** — becomes TypeScript configuration, shared domain types, validation, latest embedded SurrealDB storage, and provider adapters. Storage owns the fresh schema, vectors, hybrid search, graph primitives, and intake queue primitives. It owns embedding and search fusion in line with DR-002, and it does not leak SurrealDB SDK values through its interface.
- **Tools** — the shallow Python tool files become a deep `KnowledgeGraph` module. Its model-facing Pi tool adapters expose search, graph inspection, creation, exact editing, merging, edge removal, and edge-type renaming. It composes storage primitives but owns graph business rules.
- **Agents** — becomes three workflows: **ingest**, **recall**, and **dream**. Pi replaces PydanticAI. Dream remains one workflow with separate deduplication and connection sessions. Conversation and Jev routing disappear.
- **API** — becomes an Elysia HTTP adapter and application composition root. It preserves the non-conversation routes, response shapes, status codes, queue controls, dream jobs, and graph lookup. It does not mount MCP or conversation routes.
- **Client** — unchanged in this work. Existing conversation paths become stale because the server intentionally removes those routes.
- **Manual Test Tools** — the smoke suite moves to Bun-facing HTTP journeys and checks the new server lifecycle, fresh database initialization, intake pipeline, recall, graph reads, and dream jobs. Automated coverage must explicitly port the existing server tests, queue and scheduler tests, fresh-schema checks, HTTP contracts, and direct/Codemode tool contracts.

### New Modules

- **Pi agent runtime** (`src/agent-runtime/`) — a deep adapter around `createAgentSession`. It owns model selection, request-scoped in-memory sessions, closed tool loadouts, Codemode setup, prompt execution, event observation, cancellation, and disposal. Workflows do not import Pi session or resource-loader details.
- **Knowledge graph** (`src/knowledge/`) — a deep domain module over storage. It owns model-facing tool contracts, canonical-ID validation, forgiving argument normalization, duplicate and self-edge handling, exact node edits, identity merges, edge merges, edge removal, and global edge-type renaming.
- **Application runtime** (`src/application/`) — owns startup composition and shutdown. It creates one shared model runtime, embedding adapter, storage instance, knowledge module, intake pipeline, dream scheduler, and in-memory dream-job registry, then supplies them to Elysia route handlers.
- **Embedding adapter** (`src/embeddings/`) — wraps the official OpenAI TypeScript client for the configured embedding model and dimensions while remaining independent from Pi’s chat-agent runtime.

### Interfaces

#### Configuration and model selection

The server configuration exposes one required Pi model reference per workflow:

```ts
type ThinkingLevel =
  | "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";

type WorkflowModelRef = {
  provider: string;
  model: string;
  thinkingLevel: ThinkingLevel;
};

interface Settings {
  ingestModel: WorkflowModelRef;
  recallModel: WorkflowModelRef;
  dreamModel: WorkflowModelRef;
  embeddingModel: string;
  embeddingDimensions: number;
  dbPath: string;
  intake: IntakeSettings;
  dream: DreamSettings;
}
```

`BRAIN_INGEST_MODEL`, `BRAIN_RECALL_MODEL`, and `BRAIN_DREAM_MODEL` must use `provider/model:effort`. The parser splits the provider and model at the first slash and the thinking level at the final colon, then rejects unsupported levels. Pi’s standard provider credentials and model configuration supply authentication and custom endpoint definitions. Embeddings keep `BRAIN_EMBEDDING_MODEL` and `BRAIN_EMBEDDING_DIMENSIONS`, without the removed reasoning-provider settings.

#### Pi agent runtime

```ts
interface AgentRuntime {
  run(request: AgentRunRequest): Promise<AgentRunResult>;
}

type AgentRunRequest = {
  model: WorkflowModelRef;
  systemPrompt: string;
  prompt: string;
  tools: readonly AgentTool[];
  signal?: AbortSignal;
  onEvent?: (event: AgentEvent) => void;
};

type AgentRunResult = {
  settled: boolean;
  aborted: boolean;
  lastAssistantText?: string;
  toolResults: readonly StructuredToolResult[];
};
```

The production adapter creates a Pi `AgentSession` with `SessionManager.inMemory()`, no built-in filesystem, shell, network, or MCP tools, and no persistent resources. It loads `createCodemodeExtension({ mode: "on", models: false })` and activates Codemode alongside the selected direct domain tools. Direct tools remain callable for less capable models. Every domain tool supplies a TypeBox parameter schema, an `outputSchema` where it returns data, and `structuredContent` so direct calls and Codemode scripts share one result contract. Tool execution receives the session signal and must stop on cancellation. The adapter waits for settlement, aborts on cancellation, and disposes the session on every exit path.

#### Storage and embeddings

```ts
interface Embedder {
  embed(text: string, signal?: AbortSignal): Promise<readonly number[]>;
  embedBatch(texts: readonly string[], signal?: AbortSignal): Promise<readonly (readonly number[])[]>;
}

interface Storage {
  init(): Promise<void>;
  close(): Promise<void>;

  createNode(input: NewNode): Promise<NodeRecord>;
  getNode(id: NodeId): Promise<NodeRecord | undefined>;
  updateNodeFields(id: NodeId, fields: NodeFields): Promise<NodeRecord | undefined>;
  deleteNode(id: NodeId): Promise<void>;

  createEdge(input: NewEdge): Promise<EdgeRecord>;
  getEdge(id: EdgeId): Promise<EdgeRecord | undefined>;
  deleteEdge(id: EdgeId): Promise<void>;
  getIncomingEdges(id: NodeId): Promise<readonly EdgeRecord[]>;
  getOutgoingEdges(id: NodeId): Promise<readonly EdgeRecord[]>;
  findEdges(from: NodeId, edgeType: string, to: NodeId): Promise<readonly EdgeRecord[]>;

  searchCandidates(query: string, limit: number): Promise<MemorySearchResult>;
  findSimilarCandidates(id: NodeId, limit: number): Promise<readonly NodeRecord[]>;

  claimIntakeBatch(...): Promise<ClaimedBatch | undefined>;
  renewIntakeBatch(...): Promise<number>;
  deleteIntakeBatch(...): Promise<number>;
  releaseIntakeBatch(...): Promise<void>;
  intakeQueueSnapshot(): Promise<IntakeQueueSnapshot>;
}
```

The storage implementation uses the latest compatible `surrealdb`, `@surrealdb/node`, and `@surrealdb/node-native` packages, connects to a fresh `surrealkv://<path>`, initializes the TypeScript-owned `brain` namespace/database schema and indexes, and normalizes record IDs and datetimes into plain values. It owns automatic embeddings for node creation and searchable field changes, plus BM25/vector fusion. It does not expose raw SurrealQL or SDK record types to workflows or tools.

#### Knowledge graph tool contracts

All ordinary operations are singular. Pi can issue repeated calls in one turn. Dependent calls use a later turn after earlier tool results return IDs.

```ts
type StoreNodeInput =
  | { kind: "entity"; name: string; type: string; description?: string }
  | { kind: "note"; content: string; source?: string; summary?: string };

interface StoreNodeTool {
  storeNode(input: StoreNodeInput): Promise<NodeRecord>;
}

interface StoreEdgeTool {
  storeEdge(input: {
    fromId: NodeId;
    edgeType: string;
    toId: NodeId;
    context?: string;
  }): Promise<EdgeWriteResult>;
}

interface UpdateNodeTool {
  updateNode(input: {
    id: NodeId;
    field: EditableNodeField;
    oldText: string;
    newText: string;
  }): Promise<NodeRecord>;
}
```

`storeNode` creates exactly one note or entity and never updates or merges. `storeEdge` accepts only existing canonical node IDs and never creates nodes or resolves names. It returns a structured created or skipped result for self-edges and duplicate relationships. `updateNode` reads the selected field, requires exactly one occurrence of `oldText`, performs no write when the match count is zero or greater than one, validates the resulting field, and re-embeds searchable text. It never accepts an unconditional field overwrite.

Each mutation tool call executes in its own short SurrealDB transaction and commits before returning. `storeNode` and `storeEdge` therefore return real IDs immediately. Earlier successful calls remain after a later Pi turn fails, and no transaction remains open during model requests. Composite operations such as node merge, edge merge, and edge-type rename are atomic within their individual calls.

Read tools expose `searchMemory`, `getNode`, and `exploreGraph`. Discovery tools expose `findSimilar` and `findUnlinkedCooccurrences`. Results contain canonical IDs, bounded node fields, edge IDs, and unprocessed evidence projections; they omit embeddings and queue lease metadata.

Destructive graph operations are separate:

```ts
mergeNodes({
  survivorId: NodeId,
  loserIds: readonly NodeId[],
  survivorFields?: NodeFields,
}): Promise<MergeNodesResult>;

mergeEdges({
  survivorId: EdgeId,
  loserIds: readonly EdgeId[],
  context?: string,
}): Promise<MergeEdgesResult>;

removeEdge({ id: EdgeId }): Promise<RemovedEdgeResult>;

renameEdgeType({
  fromType: string,
  toType: string,
}): Promise<RenameEdgeTypeResult>;
```

`mergeNodes` accepts one survivor and a group of losers, accepts explicit reconciled survivor fields, atomically repoints incident edges, removes self-edges, deduplicates converging edges, and deletes loser nodes. `mergeEdges` requires all selected edges to connect the same ordered node pair, keeps the survivor identity, and deletes the losers. `removeEdge` removes one canonical edge ID. `renameEdgeType` rewrites every edge of the old type to the target type in one transaction and auto-merges collisions using the edge-merge policy.

#### Workflow tool sets

- **Ingest workflow:** `searchMemory`, `getNode`, `exploreGraph`, `storeNode`, `storeEdge`, and `updateNode`. It processes one leased intake batch, commits each successful mutation call, and reports errors so an interrupted batch can retry without holding a transaction across model requests.
- **Recall workflow:** `searchMemory`, `getNode`, `exploreGraph`, and a model-only `answerRecall` tool. `answerRecall` accepts the existing answer, evidence flag, and node/edge/unprocessed citation arrays. It validates citations against evidence collected in the session and terminates the run only when the response is valid. The HTTP layer still resolves citations against live storage before returning the response.
- **Dream workflow:** one scheduler-facing workflow with separate request-scoped Pi sessions for deduplication and connection discovery. Deduplication gets `findSimilar`, `getNode`, `exploreGraph`, `mergeNodes`, `mergeEdges`, `updateNode`, `removeEdge`, and `renameEdgeType`. Connection discovery gets `findSimilar`, `findUnlinkedCooccurrences`, `getNode`, `exploreGraph`, `storeEdge`, and `updateNode`.

#### Intake pipeline and dream scheduler

```ts
interface IntakePipeline {
  enqueue(request: IntakeRequest): Promise<EnqueueResult>;
  start(): Promise<void>;
  stop(): Promise<void>;
  snapshot(): Promise<PipelineSnapshot>;
  pause(intakeId: string): Promise<number>;
  resume(intakeId: string): Promise<number>;
  discard(intakeId: string): Promise<number>;
}

interface DreamScheduler {
  start(): void;
  stop(): Promise<void>;
  touchActivity(): void;
  runCycle(): Promise<DreamCycleResult>;
}
```

The intake pipeline keeps paragraph/sentence chunking, synchronous searchable staging, contiguous leased batches, lease renewal, retry backoff, pause/resume/discard, and clean-acknowledgement semantics. A batch is acknowledged only after the ingest workflow completes without errors; mutation calls commit independently, so committed calls remain after a later failure and replay remains at-least-once. The dream scheduler keeps idle backoff, activity wake-up, per-idle-period convergence limits, dedup-before-connect ordering, cancellation, and dream-age updates.

#### HTTP adapter

Elysia routes call the application interfaces and contain no Pi or SurrealDB code. They preserve the current non-conversation request and response shapes:

- `GET /health`
- `POST /dream` with `202` and `Location: /dream/jobs/:job_id`
- `GET /dream/jobs/:job_id`
- `POST /ingest` with `Idempotency-Key` support
- `GET /ingest/pipeline`
- `POST /ingest/pipeline/:intake_id/pause`
- `POST /ingest/pipeline/:intake_id/resume`
- `POST /ingest/pipeline/:intake_id/discard`
- `POST /recall`
- `GET /graph/:record_id`

Elysia uses the shared TypeBox schemas for JSON bodies, headers, path parameters, and responses. `POST /converse`, `/converse/stream`, and `/mcp` do not exist. Missing routes return the framework’s normal `404` response.

### Review additions

Recall preserves caller hints through `RecallWorkflow.run(question, signal, hints)`. The application exposes `createRecallService` with an injected workflow and live evidence store. It resolves node, edge, and intake citations against current records before returning HTTP context. Storage failures cannot produce stale context. A citation that no longer resolves must not reach the HTTP response.

Composite graph mutations use the storage adapter's atomic transaction seam. Storage and its transaction scope expose `getEdgesByType` for atomic global renames. Storage also exposes normalized unlinked cooccurrence candidates with canonical IDs and shared note IDs. Discovery follows note-to-entity `references` relations and excludes linked entity pairs. Raw SurrealQL remains inside storage. Intake staging uses an atomic content fingerprint contract. Matching idempotency retries return zero newly stored chunks while the intake remains queued. Conflicting content cannot change stored evidence.

Embedding tests use a configured adapter factory and deterministic provider injection. Storage tests use stateful boundary operations, not fixed stub responses. Fresh-database tests use isolated local databases, initialize the latest schema, verify indexes and relations, and reopen the database without migration or Python fixtures. Production startup and the test suite do not require Python server sources.

The Pi runtime exposes an SDK-backed smoke seam with deterministic model transport. Tests execute direct and Codemode calls through actual Pi orchestration, validate tool schemas, and check provider/model selection without external model requests.

Ingest batches expose `attemptCount` for capped retry backoff. Lease renewal failure cancels work and prevents acknowledgement. Dream scheduling exposes a public snapshot and optional state observer. These report completed idle cycles, the convergence limit, and convergence state. The limit preserves `ceil(sqrt(nodeCount / batchSize))` and resets on activity.

### Technology Choices

- **Bun** — package manager, runtime, test runner, and production image. This removes Python from the server runtime.
- **`@earendil-works/pi-coding-agent` AgentSession SDK** — the in-process Pi seam. `SessionManager.inMemory()` and explicit custom tool loadouts match request-scoped server work better than the CLI, RPC, or lower-level agent loop.
- **Pi Codemode with `models: false`** — allows model-authored scripts to compose domain tools without exposing filesystem, shell, MCP, or classifier/image model capabilities. Direct tools remain active.
- **Elysia** — Bun-native HTTP routing and lifecycle integration.
- **TypeBox** — shared runtime schemas for Elysia, Pi tools, Codemode structured results, and inferred TypeScript types.
- **Latest SurrealDB JavaScript SDK with the native embedded engine** — use the latest compatible `surrealdb`, `@surrealdb/node`, and `@surrealdb/node-native` packages for fresh `surrealkv://` storage. The fresh-schema and reopen smoke test is an implementation gate; no old-file compatibility is required.
- **Official OpenAI TypeScript client** — direct embedding adapter, independent of Pi chat sessions, using standard provider credentials and preserving the current embedding model dimensions.
- **Standard Pi provider configuration** — workflow model strings select models and thinking levels; standard Pi credentials and model definitions provide authentication and custom endpoint metadata.
- **Bun test** — native test runner for unit, integration, HTTP, fresh-schema, and tool-contract tests.

### DR Supersessions

- **DR-001** (Batched Ingest Tool Over Structured Output) — superseded because the Pi rewrite keeps the search-before-write agent loop but replaces the old positional batch contract with singular `storeNode` and `storeEdge` tools, direct and Codemode invocation, canonical IDs for existing records, and explicit update/merge operations. The new design accepts partial graph progress during at-least-once intake processing.

## Tests

**Pre-test-write commit:** `babef48d9b6b4eed0ea649bc0899133a54fd600a`

### Interface Files

- `src/core/config.ts` — workflow model references, environment settings, intake settings, and dream settings.
- `src/core/types.ts` — node, edge, search, intake chunk, claimed batch, and queue snapshot data types.
- `src/embeddings/embedder.ts` — embedding adapter contract and test stub.
- `src/storage/storage.ts` — storage, graph primitive, search, and intake queue contracts with a test stub.
- `src/storage/embedded.ts` — Bun-native embedded SurrealDB storage factory seam.
- `src/agent-runtime/index.ts` — request-scoped Pi runtime, injectable session factory, SDK-backed runtime factory, tool, event, and structured result contracts.
- `src/knowledge/index.ts` — KnowledgeGraph reads, discovery, mutation, merge, removal, rename, and tool contracts.
- `src/workflows/workflows.ts` — ingest, recall, and dream workflow contracts.
- `src/workflows/intake-pipeline.ts` — staged intake, queue adapter, clock, and pipeline lifecycle contracts.
- `src/workflows/dream-scheduler.ts` — dream queue, cycle result, and scheduler lifecycle contracts.
- `src/http/contracts.ts` — HTTP request, response, pipeline, dream job, and application contracts.
- `src/http/schemas.ts` — shared TypeBox schema boundary types.
- `src/http/server.ts` — Elysia server adapter boundary.
- `src/application/runtime.ts` — startup composition and shutdown contracts.

### Test Files

- `tests/config.test.ts` — workflow model parsing and complete environment settings.
- `tests/embedding.test.ts` — configured single and batch embedding adapter calls, cancellation, and empty batches.
- `tests/embedding-adapter.test.ts` — configured provider/model/dimension forwarding, invalid vectors, and provider failures.
- `tests/storage.test.ts` — storage lifecycle, graph records, search projections, intake leases, and queue snapshots.
- `tests/surrealdb-latest.test.ts` — fresh latest-engine `surrealkv://` startup, schema/index initialization, SDK value normalization, and reopen gate.
- `tests/agent-runtime.test.ts` — isolated sessions, closed tools, Codemode configuration, events, cancellation, results, and disposal.
- `tests/agent-runtime/sdk-smoke.test.ts` — SDK-backed runtime operations with deterministic provider transport, direct/Codemode invocation, and schema failures.
- `tests/knowledge.test.ts` — graph writes, canonical IDs, exact edits, read and discovery projections, atomic merges, edge operations, schemas, and cancellation.
- `tests/workflows.test.ts` — ingest, recall, and dream tool loadouts, citations, mutation failures, and cancellation.
- `tests/intake-pipeline.test.ts` — synchronous staging, chunk bounds, idempotency, queue controls, retries, acknowledgement, and worker shutdown.
- `tests/dream-scheduler.test.ts` — phase order, convergence, errors, idle backoff, activity wake-up, cancellation, and lifecycle.
- `tests/http-schemas.test.ts` — TypeBox body, header, path, response, status, and evidence shape boundaries.
- `tests/http.test.ts` — non-conversation routes, status codes, Location headers, idempotency forwarding, validation, and removed routes.
- `tests/application.test.ts` — shared composition, startup ordering, failure cleanup, worker shutdown, and storage closure.
- `tests/recall-service.test.ts` — caller hints, live citation resolution, evidence-free context, and storage failures.
- `tests/intake-reliability.test.ts` — heartbeat ownership loss, workflow exceptions, and capped retry delays.
- `tests/dream-convergence.test.ts` — per-idle-period cutoff, public convergence state, and activity reset.

### Behaviors Covered

#### Configuration and model selection

- Workflow model references split provider, model, and final thinking level and reject malformed or unsupported values.
- Settings expose all three workflow models, embedding configuration, database path, intake limits, and dream controls.

#### Embeddings and storage

- Embedding calls return one vector per text and preserve batch order while accepting cancellation signals.
- Storage owns lifecycle, canonical node and edge records, graph edge direction, search results, and separate unprocessed evidence.
- Intake storage exposes contiguous lease, renewal, release, acknowledgement, and queue snapshot contracts without leaking SDK values.
- The embedded storage adapter accepts a local SurrealKV path and returns plain domain values instead of SurrealDB SDK records.
- Fresh latest-engine storage initializes the TypeScript-owned schema, indexes, vectors, relations, and queue state, then reopens the same newly created database without migration.
- Stateful storage tests cover embedding updates, hybrid search, atomic transaction rollback, intake content fingerprints, replay, lease expiry, and ownership checks without Python fixtures.

#### Pi agent runtime

- Each run creates an isolated in-memory session with the selected model, explicit direct tools, Codemode enabled, and built-ins/resources disabled.
- Runtime results preserve settled state, assistant text, structured tool results, events, cancellation, and disposal on every exit path.

#### Knowledge graph

- Node and edge mutations use canonical IDs, create singular records, reject names and missing endpoints, and skip self or duplicate edges with structured results.
- Exact node edits require one match, validate resulting fields, re-embed searchable text, and do not write on invalid match counts.
- Read and discovery tools return bounded graph and unprocessed evidence projections without embeddings or lease metadata.
- Node and edge merges, removals, and global edge-type renames preserve survivor identities, repoint or deduplicate edges, remove self-edges, and remain atomic on invalid input.
- Direct tools expose TypeBox parameter and output schemas with structured results compatible with Codemode, and cancellation stops execution.

#### Workflows

- Ingest uses only its closed read/write tool set, submits leased chunks in source order, reports errors, preserves earlier committed calls, and never acknowledges unsettled or aborted runs.
- Recall uses only read tools plus validated `answerRecall`, accepts citations from collected evidence, rejects invented citations, and does not return free-form unvalidated text.
- Dream runs deduplication and connection as separate phases with their distinct closed tool sets and propagates mutation errors and cancellation.

#### Intake pipeline and dream scheduler

- Intake stages nonblank text into bounded ordered chunks before acknowledgement, forwards idempotency keys, exposes queue controls, and reports retry/error state.
- Pipeline acknowledges only clean batches, releases failed or aborted leases, and cancels active work during shutdown.
- Dream deduplicates before connection, skips empty graphs, records phase failures, advances dream age, converges idle cycles with capped exponential delays, wakes on activity, and cancels active phases on stop.

#### HTTP and application runtime

- Shared TypeBox schemas validate bodies, headers, paths, response shapes, integer counts, job states, and separate unprocessed evidence.
- Elysia preserves health, ingest, pipeline controls, recall, graph lookup, and asynchronous dream-job routes with documented statuses, Location headers, idempotency forwarding, and 404/422 behavior.
- Conversation and MCP routes remain absent and return normal missing-route responses.
- Application startup creates one shared model runtime, embedder, storage, knowledge module, workers, scheduler, and dream-job registry in dependency order.
- Shutdown and startup failures stop workers before storage closure and release resources on every partial-start path.

**Review status:** approved

## Steps

### Step 1: Establish the Bun dependency gate

Use Bun package-manager commands to install the latest compatible SurrealDB, Elysia, TypeBox, Pi, OpenAI, and Bun type dependencies and generate `bun.lock`. Pin native engine versions through Bun, not manual manifest edits. Keep `package.json` test and typecheck commands. Keep the old service runnable until the fresh-schema and behavior gate passes.

Read the installed Pi SDK documentation for sessions, resource loaders, model runtime, custom tools, and Codemode before implementing its adapter. Use the installed SDK version, not CLI orchestration.

**Verify:** Bun loads the native engine and the installed Pi exports used by `tests/agent-runtime/sdk-smoke.test.ts`. Existing Python startup remains available.
**Status:** not started

### Step 2: Implement configuration and embeddings

Implement `parseWorkflowModelRef` and `parseSettings` in `src/core/config.ts`. Require all three workflow references. Split the first slash and final colon. Validate the complete thinking-level range and numeric limits. Port intake and dream defaults from `src/second_brain/config.py`, without reasoning-provider or Jev settings.

Implement `createEmbedder` in `src/embeddings/embedder.ts` using its injected `EmbeddingProvider`. Forward model, dimensions, ordered texts, and cancellation. Reject wrong vector counts, dimensions, and non-finite values. Empty batches require no provider call. Add `src/embeddings/openai.ts` to adapt the official OpenAI client to `EmbeddingProvider`. Preserve the configured embedding model and dimensions. Keep chat model selection independent.

**Verify:** `bun test tests/config.test.ts tests/embedding.test.ts tests/embedding-adapter.test.ts` passes.
**Status:** not started

### Step 3: Open latest embedded storage

Implement `createEmbeddedStorage` in `src/storage/embedded.ts`. Keep SDK connection, fresh schema initialization, and normalization inside storage. Add private storage files where needed, including `src/storage/schema.ts` for the TypeScript-owned definitions.

Connect with `createNodeEngines()` to `surrealkv://<dbPath>`, then select the `brain` namespace and database. Define the latest schema and vector indexes without migration code. Initialize relation tables, queue fields, index names, and configured dimensions. Normalize SDK IDs and datetimes into `src/core/types.ts` values. Omit vectors from public records. Make close safe after partial initialization.

**Verify:** `bun test tests/surrealdb-latest.test.ts` passes once search support in Step 5 is complete. Fresh startup, index creation, and reopen checks pass now.
**Status:** not started

### Step 4: Implement graph storage transactions

Implement graph operations from `Storage` and `StorageTransaction` in `src/storage/storage.ts` behind the embedded adapter. Implement `withTransaction` with commit on callback success and rollback on rejection. Keep transaction-scoped operations on that transaction, without nested commits.

Implement node creation, lookup, field updates, and deletion. Preserve unrelated fields during updates. Embed note content and searchable entity name/description changes. Summary-only updates require no embedding call. Reject failed embeddings without changing records.

Implement relation creation, lookup, deletion, incoming/outgoing traversal, `findEdges`, and `getEdgesByType`. Preserve directed endpoints and canonical relation-table IDs. Commit each standalone mutation before returning. Validate identifiers before dynamic table access. Do not expose raw queries or SDK objects.

**Verify:** Graph and transaction cases in `tests/storage.test.ts` pass, including rollback and retention of earlier committed calls.
**Status:** not started

### Step 5: Implement search and discovery storage

Implement `searchCandidates`, `findSimilarCandidates`, `searchIntakeChunks`, and `findUnlinkedCooccurrenceCandidates` inside storage. Port lexical/vector candidate retrieval and reciprocal-rank fusion from `src/second_brain/db.py`. Embed each query once. Return bounded graph results and separate unprocessed evidence. Follow DR-002 for fusion ownership.

Keep embeddings internally available for similarity searches. Exclude the source node from similar candidates. Discover entity pairs through shared note-to-entity `references` relations. Exclude pairs already linked in either direction. Return canonical IDs and shared note IDs without SDK values or queue metadata.

**Verify:** Search and discovery cases in `tests/storage.test.ts` and the full `tests/surrealdb-latest.test.ts` pass.
**Status:** not started

### Step 6: Implement atomic intake storage

Implement `createIntakeChunks`, `getIntakeChunks`, queue claiming, renewal, acknowledgement, release, controls, and snapshots inside storage. Port `_intake_fingerprint`, `_select_claim`, and `_summarize_queue` behavior from `src/second_brain/db.py`. Use the injected clock for ownership and retry comparisons.

Stage chunks and the idempotency record atomically. Match the Python fingerprint encoding. Matching retries return zero without embedding again. Conflicting content cannot modify evidence. Delete the idempotency record when its intake no longer has queued chunks, preserving later replay behavior.

Claim one intake's contiguous eligible head chunks within the character budget. Reclaim expired leases. Renewal, deletion, and release require current ownership. Failed batch embeddings and rejected transaction callbacks leave no partial rows. Keep operational metadata available only through queue records and snapshots.

**Verify:** All intake and transaction cases in `tests/storage.test.ts` pass, including stale ownership, replay, and batch rollback.
**Status:** not started

### Step 7: Implement knowledge reads and singular writes

Implement `createKnowledgeGraph` in `src/knowledge/index.ts`. Add `src/knowledge/schemas.ts` for domain input and output schemas. Port applicable validation and projection rules from `src/second_brain/validation.py` and the Python tool files. Keep graph business rules here and queries inside storage.

Implement `storeNode`, `storeEdge`, and `updateNode`. Store one independent record per node call. Validate canonical existing endpoints before relation writes. Return structured self-edge and duplicate skips. Exact edits require one nonempty match in an editable field. Validate the resulting node and never write on invalid matches. Use short storage transactions for mutation calls.

Implement `searchMemory`, `getNode`, `exploreGraph`, `findSimilar`, and `findUnlinkedCooccurrences`. Bound traversal and result projections. Return absent nodes without fabrication. Reject names and non-node IDs in graph reads.

**Verify:** Singular write, exact edit, read, search, and discovery cases in `tests/knowledge.test.ts` pass.
**Status:** not started

### Step 8: Implement atomic graph reconciliation and tools

Implement `mergeNodes`, `mergeEdges`, `removeEdge`, and `renameEdgeType` in `src/knowledge/index.ts`. Validate all selected records before destructive changes. Use `withTransaction` for each composite call.

Node merges retain the survivor and explicit reconciled fields. Repoint incident edges, remove self-edges, deduplicate converging relationships, and delete losers. Edge merges require the same ordered pair and preserve survivor identity. Global renames enumerate types within the transaction and merge collisions using the same policy. Adapt existing reconciliation behavior from `src/second_brain/tools/dream_tools.py`.

Implement `tools(names)` with exactly the requested loadout. Each tool validates parameters, supplies an output schema, and returns `StructuredToolResult.structuredContent`. Normalize forgiving arguments without weakening canonical-ID or mutation validation. Check the session signal before work and before mutations.

**Verify:** `bun test tests/knowledge.test.ts` passes, including schema checks, cancellation, and atomic failure cases.
**Status:** not started

### Step 9: Implement the Pi runtime

Implement `createAgentRuntime` and `createSdkAgentRuntime` in `src/agent-runtime/index.ts`. Preserve the injected `SessionFactory` seam. Build one request-scoped in-memory session per run with the selected provider, model, and thinking level. Disable built-ins and persistent resources. Enable Codemode with `mode: "on"` and `models: false`, alongside direct domain tools.

Adapt `AgentTool` parameters, output validation, structured content, and failures to Pi custom tools. Preserve structured domain results from direct and Codemode execution. Observe events without changing results. Wait for settlement, propagate cancellation, abort active execution, and dispose on every exit. Cancellation before execution must not send a prompt.

Use only request-scoped session/result state. Reuse the injected shared `ModelRuntime` for model selection and standard credentials.

**Verify:** `bun test tests/agent-runtime.test.ts tests/agent-runtime/sdk-smoke.test.ts` passes without external model calls.
**Status:** not started

### Step 10: Implement the three workflows

Implement the workflow factories in `src/workflows/workflows.ts`. Add `src/workflows/prompts.ts` for prompts adapted from Python ingest, recall, dedup, and connection workflows. Update instructions to singular tools, canonical IDs, exact edits, and partial committed progress.

Ingest selects only its six approved tools and submits chunks in source order with hints. Return an unclean outcome for runtime exceptions, tool errors, unsettled runs, or cancellation. Do not acknowledge leases here.

Recall wraps read tools to collect successful evidence per request. Add the model-only `answerRecall` tool with TypeBox validation. Reject invented citations and accept a later valid answer. Keep the accepted answer and evidence in request-scoped state. Terminate only after validation. Distinguish successful answer termination from caller cancellation. Reject runs without a validated answer and never return free-form assistant text.

Dream selects its two distinct approved loadouts and creates a separate runtime call for each phase. Report mutation errors, cancellation, and touched node IDs without undoing earlier writes.

**Verify:** `bun test tests/workflows.test.ts` passes, including hints, citations, closed loadouts, partial progress, and cancellation.
**Status:** not started

### Step 11: Implement leased intake processing

Implement `createIntakePipeline` in `src/workflows/intake-pipeline.ts`. Port paragraph/sentence splitting and oversized-unit handling from `src/second_brain/agents/ingestion_pipeline.py`. Stage ordered bounded drafts synchronously, forwarding hints, source, and idempotency keys.

Use instance-owned worker, lease, and cancellation state. Keep `start` and `stop` idempotent. Renew active leases through the injected clock. Ownership loss or renewal failure cancels the workflow and prevents acknowledgement. Delete only clean, completed, still-owned batches. Release failed or aborted batches with capped retry delays derived from `attemptCount`. Report exceptions as failures.

Stop polling during shutdown, apply the grace period, cancel active workflows, release unacknowledged leases, and await settlement. Merge live worker visibility into snapshots. Forward pause/resume/discard to the selected intake. Notify activity after staging.

**Verify:** `bun test tests/intake-pipeline.test.ts tests/intake-reliability.test.ts` passes.
**Status:** not started

### Step 12: Implement dream storage and scheduling

Add `countNodes(): Promise<number>`, `selectDreamBatch(kind: "entity" | "all", limit: number)`, and `incrementDreamAge(nodeIds: readonly NodeId[]): Promise<void>` to `Storage` and its stub in `src/storage/storage.ts`. Implement them inside embedded storage. Count notes and entities, select lowest dream ages, and increment only existing canonical nodes without upserts. Preserve persisted `dream_age` and timestamp behavior.

Implement `createDreamScheduler` in `src/workflows/dream-scheduler.ts` using `DreamQueue`. Port idle timing and convergence rules from `src/second_brain/scheduler.py`. Deduplicate entities before connection discovery over a mixed batch. Report phase errors and age processed/touched surviving nodes.

Keep idle state and controllers inside the scheduler instance. Activity resets backoff and convergence, wakes idle waits, and cancels active work. Stop awaits active cycles. Preserve `ceil(sqrt(nodeCount / batchSize))`, capped exponential delays, public snapshots, and state notifications. Repeated starts create no duplicate loop.

**Verify:** `bun test tests/dream-scheduler.test.ts tests/dream-convergence.test.ts` passes.
**Status:** not started

### Step 13: Implement HTTP contracts and recall resolution

Implement `createHttpSchemas` in `src/http/schemas.ts` with TypeBox schemas for all fields in `HttpSchemas`. Preserve wire dictionaries, nullable recall context, separate unprocessed evidence, integer counts, named path parameters, and the four dream-job states.

Implement `HttpApplicationError` and `createRecallService` in `src/http/contracts.ts`. Forward question and hints to the workflow. Resolve every citation against live evidence before returning context. Reject missing records and storage failures rather than returning cached projections. Return null context for evidence-free answers.

**Verify:** `bun test tests/http-schemas.test.ts tests/recall-service.test.ts` passes.
**Status:** not started

### Step 14: Implement the Elysia adapter

Implement `createHttpServer` in `src/http/server.ts`. Mount only the non-conversation routes listed in the architecture. Attach shared body, header, path, and response schemas. Preserve snake-case wire fields, ingest defaults, idempotency forwarding, asynchronous dream status, and Location headers.

Map application failures to existing statuses and `{ detail }` responses. Return 404 for absent jobs, absent graph records, and zero-count pipeline controls. Malformed bodies return framework validation responses before application calls. Do not mount conversation or MCP routes. Route handlers import neither Pi nor SurrealDB.

**Verify:** `bun test tests/http.test.ts` passes, including ordinary missing-route 404s and validation 422s.
**Status:** not started

### Step 15: Compose and start the application

Implement `startApplication` in `src/application/runtime.ts` against `CompositionFactories`. Create one shared model runtime, embedder, storage, and knowledge module. Initialize storage before workers. Supply one instance-owned dream-job Map to the application. Clean up partial starts and stop both workers before closing storage, even when one stop fails.

Add `src/application/composition.ts` for production factories and domain adapters. Adapt storage snake-case intake records to `IngestBatch`, including attempt counts. Bind worker identity, batch-character limits, and lease duration in the queue adapter. Convert queue retry delays to clock-based timestamps. Map settings seconds/minutes to workflow milliseconds. Adapt the dream storage methods to `DreamQueue`.

Implement `HttpApplication` composition with staging limits, activity notifications, live recall evidence, graph wire projections, and pending/running/complete/failed dream jobs. Keep jobs and active lifecycle work within the application instance. Ensure shutdown settles manual dream jobs before storage closure.

Add `src/main.ts` to parse environment settings, create standard Pi model configuration and OpenAI embedding transport, start the application, listen on port 8000, and handle termination. Do not import Python or use global service locators.

**Verify:** `bun test tests/application.test.ts` passes. The Bun entry point serves `/health` and releases workers and storage on termination.
**Status:** not started

### Step 16: Pass the replacement gate and cut over

Run all listed TypeScript tests with `bun test`, then run the typecheck command. Resolve implementation failures without changing approved contracts. Keep the old production service available until fresh latest-schema initialization, runtime smoke, workflow reliability, and HTTP contracts pass.

Update `tools/manual-test/README.md` and `tools/manual-test/PLAN.md` for Bun-facing startup, staging, pipeline controls, recall, graph lookup, dream-job polling, restart, and shutdown journeys. Use the existing non-conversation HTTP contract. Record results under `docs/manual-tests/`.

After the gate passes, replace `Dockerfile` with a Bun production image and update `docker-compose.yml`, `Makefile`, `.env.example`, `.env.mobile.example`, and `README.md` for the TypeScript entry point and fresh database lifecycle. Preserve database volumes and mobile isolation. Update server health checks for the Bun image. Remove Python, PydanticAI, MCP, conversation, and Jev from production execution. Do not change client code or ignored local environment files.

Delete the old Python server, Python dependencies, compatibility fixture, and migration-only inputs. The new server owns a fresh database path and initializes its latest schema at startup. Do not import or execute Python in tests or production.

Update `codemap.md` to the implemented TypeScript modules. Record the specified DR-001 supersession through the decision-records skill.

**Verify:** All listed TypeScript tests and typecheck pass. Manual HTTP journeys pass. The production image starts without Python and initializes an empty latest-schema database.
**Status:** not started
