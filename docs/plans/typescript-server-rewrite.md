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

A short-lived mutation coordinator gives each Pi assistant message one SurrealDB transaction. Mutation tools execute inside that transaction and can return IDs allocated by it. The coordinator commits after the assistant message completes and rolls back that message’s intents if the turn fails. A later failed turn does not undo earlier committed turns, and no transaction remains open during model requests.

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

- **Ingest workflow:** `searchMemory`, `getNode`, `exploreGraph`, `storeNode`, `storeEdge`, and `updateNode`. It processes one leased intake batch, commits successful mutation turns, and reports errors so an interrupted batch can retry without holding a transaction across model requests.
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

The intake pipeline keeps paragraph/sentence chunking, synchronous searchable staging, contiguous leased batches, lease renewal, retry backoff, pause/resume/discard, and clean-acknowledgement semantics. A batch is acknowledged only after the ingest workflow completes without errors; mutation turns commit independently, so committed turns remain after a later failure and replay remains at-least-once. The dream scheduler keeps idle backoff, activity wake-up, per-idle-period convergence limits, dedup-before-connect ordering, cancellation, and dream-age updates.

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
