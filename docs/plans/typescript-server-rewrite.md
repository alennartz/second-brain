# Plan: TypeScript server rewrite

## Context

Replace the Python server with a Bun-native TypeScript server using the Pi TypeScript SDK. Keep the existing SurrealDB file and the non-conversation HTTP service, while removing MCP and conversation mode. The completed TypeScript server is cut over as one replacement; the architecture must keep the old service runnable until the compatibility gate passes. The brainstorm is recorded in [`docs/brainstorms/typescript-server-rewrite.md`](../brainstorms/typescript-server-rewrite.md).

## Architecture

### Impacted Modules

- **Core** — becomes TypeScript configuration, shared domain types, validation, embedded SurrealDB storage, and provider adapters. Storage keeps the existing schema, record IDs, vectors, hybrid search, graph primitives, and intake queue primitives. It owns embedding and search fusion in line with DR-002, and it does not leak SurrealDB SDK values through its interface.
- **Tools** — the shallow Python tool files become a deep `KnowledgeGraph` module. Its model-facing Pi tool adapters expose search, graph inspection, creation, exact editing, merging, edge removal, and edge-type renaming. It composes storage primitives but owns graph business rules.
- **Agents** — becomes three workflows: **ingest**, **recall**, and **dream**. Pi replaces PydanticAI. Dream remains one workflow with separate deduplication and connection sessions. Conversation and Jev routing disappear.
- **API** — becomes an Elysia HTTP adapter and application composition root. It preserves the non-conversation routes, response shapes, status codes, queue controls, dream jobs, and graph lookup. It does not mount MCP or conversation routes.
- **Client** — unchanged in this work. Existing conversation paths become stale because the server intentionally removes those routes.
- **Manual Test Tools** — the smoke suite moves to Bun-facing HTTP journeys and checks the new server lifecycle, database compatibility, intake pipeline, recall, graph reads, and dream jobs. Automated coverage must explicitly port the existing server tests, queue and scheduler tests, HTTP contracts, database compatibility cases, and direct/Codemode tool contracts.

### New Modules

- **Pi agent runtime** (`src/agent-runtime/`) — a deep adapter around `createAgentSession`. It owns model selection, request-scoped in-memory sessions, closed tool loadouts, Codemode setup, prompt execution, event observation, cancellation, and disposal. Workflows do not import Pi session or resource-loader details.
- **Knowledge graph** (`src/knowledge/`) — a deep domain module over storage. It owns model-facing tool contracts, canonical-ID validation, forgiving argument normalization, duplicate and self-edge handling, exact node edits, identity merges, edge merges, edge removal, and global edge-type renaming.
- **Application runtime** (`src/application/`) — owns startup composition and shutdown. It creates one shared model runtime, embedding adapter, storage instance, knowledge module, intake pipeline, dream scheduler, and in-memory dream-job registry, then supplies them to Elysia route handlers.
- **Embedding adapter** (`src/embeddings/`) — wraps the official OpenAI TypeScript client for the configured embedding model. It preserves the existing embedding dimensions and vector space while remaining independent from Pi’s chat-agent runtime.

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

The storage implementation uses `surrealdb` with `@surrealdb/node` and `@surrealdb/node-native`, connects to `surrealkv://<path>`, initializes the existing `brain` namespace/database schema and indexes, and normalizes record IDs and datetimes into plain values. It owns automatic embeddings for node creation and searchable field changes, plus BM25/vector fusion. It does not expose raw SurrealQL or SDK record types to workflows or tools.

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

### Technology Choices

- **Bun** — package manager, runtime, test runner, and production image. This removes Python from the server runtime.
- **`@earendil-works/pi-coding-agent` AgentSession SDK** — the in-process Pi seam. `SessionManager.inMemory()` and explicit custom tool loadouts match request-scoped server work better than the CLI, RPC, or lower-level agent loop.
- **Pi Codemode with `models: false`** — allows model-authored scripts to compose domain tools without exposing filesystem, shell, MCP, or classifier/image model capabilities. Direct tools remain active.
- **Elysia** — Bun-native HTTP routing and lifecycle integration.
- **TypeBox** — shared runtime schemas for Elysia, Pi tools, Codemode structured results, and inferred TypeScript types.
- **SurrealDB JavaScript SDK with the native embedded engine** — `surrealdb`, `@surrealdb/node`, and pinned `@surrealdb/node-native` preserve direct `surrealkv://` access. The Bun compatibility smoke test is an implementation gate.
- **Official OpenAI TypeScript client** — direct embedding adapter, independent of Pi chat sessions, using standard provider credentials and preserving the current embedding model dimensions.
- **Standard Pi provider configuration** — workflow model strings select models and thinking levels; standard Pi credentials and model definitions provide authentication and custom endpoint metadata.
- **Bun test** — native test runner for unit, integration, HTTP, database-compatibility, and tool-contract tests.

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
- `src/agent-runtime/index.ts` — request-scoped Pi runtime, session, tool, event, and structured result contracts.
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
- `tests/embedding.test.ts` — single and batch embedding results with cancellation signals.
- `tests/storage.test.ts` — storage lifecycle, graph records, search projections, intake leases, and queue snapshots.
- `tests/surrealdb-compatibility.test.ts` — embedded `surrealkv://` storage startup and SDK value normalization gate.
- `tests/agent-runtime.test.ts` — isolated sessions, closed tools, Codemode configuration, events, cancellation, results, and disposal.
- `tests/knowledge.test.ts` — graph writes, canonical IDs, exact edits, read and discovery projections, atomic merges, edge operations, schemas, and cancellation.
- `tests/workflows.test.ts` — ingest, recall, and dream tool loadouts, citations, mutation failures, and cancellation.
- `tests/intake-pipeline.test.ts` — synchronous staging, chunk bounds, idempotency, queue controls, retries, acknowledgement, and worker shutdown.
- `tests/dream-scheduler.test.ts` — phase order, convergence, errors, idle backoff, activity wake-up, cancellation, and lifecycle.
- `tests/http-schemas.test.ts` — TypeBox body, header, path, response, status, and evidence shape boundaries.
- `tests/http.test.ts` — non-conversation routes, status codes, Location headers, idempotency forwarding, validation, and removed routes.
- `tests/application.test.ts` — shared composition, startup ordering, failure cleanup, worker shutdown, and storage closure.

### Behaviors Covered

#### Configuration and model selection

- Workflow model references split provider, model, and final thinking level and reject malformed or unsupported values.
- Settings expose all three workflow models, embedding configuration, database path, intake limits, and dream controls.

#### Embeddings and storage

- Embedding calls return one vector per text and preserve batch order while accepting cancellation signals.
- Storage owns lifecycle, canonical node and edge records, graph edge direction, search results, and separate unprocessed evidence.
- Intake storage exposes contiguous lease, renewal, release, acknowledgement, and queue snapshot contracts without leaking SDK values.
- The embedded storage adapter accepts a local SurrealKV path and returns plain domain values instead of SurrealDB SDK records.

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
