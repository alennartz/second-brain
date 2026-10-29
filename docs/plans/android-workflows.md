# Plan: Android workflows

## Context

The Android client grows from two screens (Capture, one-shot Ask) into three journeys: reliable offline-first Capture, repeatable local Answer snapshots, and read-only Graph workspace exploration across named Brain profiles. Direction and reasoning live in [docs/brainstorms/android-workflows.md](../brainstorms/android-workflows.md). Interaction contracts are settled by the approved mock.

## Architecture

### Impacted Modules

**Storage (`src/storage/`)** — Intake keys become permanent. `createIntakeChunks` stops returning `0` on a key replay: a matching fingerprint returns the original `chunk_count`, and `cleanup()` no longer deletes `intake_key` rows when their chunks are consumed. Conflict on mismatched fingerprint is unchanged.

**HTTP (`src/http/`)** — Two new routes over the existing Elysia boundary: `POST /search` (hybrid search without an answer) and `POST /graph/refresh` (batch node refresh). TypeBox schemas extend; `HttpApplication` gains `search` and `refreshGraph`.

**Application (`src/application/`)** — Wires the new operations without new model calls: `search` delegates to the Pi package graph library's `searchMemory` (the same function behind `memory_search`), and `refreshGraph` batches existing storage node reads and edge walks, reusing the `getGraph` connection projection.

**Pi package (`packages/pi-second-brain/`)** — No changes; `searchMemory` is consumed as-is.

**Flutter mobile client (`client/mobile/`)** — Largest change. `SharedPreferences` settings give way to a sqflite persistence layer holding Brain profiles, the Capture outbox, Answer snapshots, and Graph workspaces. The gateway interface grows search, graph, and batch-refresh operations. Screens gain Explore (search, canvas, node detail), a combined Outbox, Brains management, and Answer history. A sync engine retries all profiles' outboxes on app open and resume.

**Manual Test Tools (`tools/manual-test/`)** — The HTTP smoke suite gains journeys for the new search and refresh routes during the manual-test phase.

### New Modules

**Client persistence (`client/mobile/lib/src/persistence/`)** — sqflite database plus repositories for Brain profiles, outbox entries, answer snapshots, and workspaces. Owns the one-time migration from the legacy settings store: the existing server configuration becomes the first Brain profile and the legacy pending draft becomes its first outbox entry, preserving key and capture time.

**Client sync engine (`client/mobile/lib/src/sync/`)** — Owns outbox delivery: retry on app open and resume for every profile, per-entry idempotency-key reuse, and the accepted/edited/conflict outcome rules. Transport-agnostic through the injected gateway factory.

**Explore workspace controller (`client/mobile/lib/src/explore/`)** — Owns the per-profile workspace state machine: loaded vs. missing vs. new flags, canvas layout, batch refresh application, and clear/clear-deleted behavior. Rendered by a custom-canvas view; no graph layout dependency.

### Interfaces

Server boundary:

```
POST /search
  body:    { query: string, limit?: int 1..100 }
  200:     { nodes: NodeProjection[], unprocessed: ChunkProjection[] }
  400/503: { detail }
NodeProjection and ChunkProjection match the memory_search tool output
projections (no embeddings, no queue metadata). Unprocessed chunks are
returned separately; only nodes open exploration.

POST /graph/refresh
  body:    { ids: string[] }            // expanded node ids, bounded (<= 200)
  200:     { results: RefreshResult[] }
  400/503: { detail }
RefreshResult =
  | { id, status: "found",   node: NodeWire, connections: ConnectionWire[] }
  | { id, status: "missing" }
ConnectionWire matches GET /graph/:record_id ({ edge, node } pairs).
A transport failure fails the whole request; only a confirmed missing
node yields "missing".

POST /ingest (behavior change, same wire shape)
  Replaying an idempotency key with the same content fingerprint returns
  200 { chunks_stored: <original count> }.
  Replaying a key with different content returns 409 { detail }.
```

Application contract additions (`HttpApplication`):

```ts
search(request: { query: string; limit?: number }): Promise<SearchResponse>;
refreshGraph(ids: readonly string[]): Promise<{ results: RefreshResult[] }>;
```

Gateway interface (client):

```dart
abstract interface class BrainGateway {
  Future<void> checkHealth();
  Future<IngestReceipt> stageIntake(String text,
      {required String idempotencyKey, required String capturedAt});
  Future<RecallResult> recall(String question);
  Future<MemorySearchResult> searchMemory(String query, {int? limit});
  Future<GraphNodeDetail> getGraph(String recordId);
  Future<GraphRefreshResult> refreshGraph(List<String> recordIds);
}
```

Client repositories (all scoped by brain profile id):

```dart
abstract interface class BrainProfileRepository {
  Future<List<BrainProfile>> list();
  Future<BrainProfile?> active();
  Future<void> add(BrainProfileDraft draft);          // saved as Never connected
  Future<void> updateAddress(String id, String url);  // clears Access credentials
  Future<void> markConnected(String id);
  Future<void> use(String id);                        // set active brain
}

abstract interface class CaptureOutboxRepository {
  Future<List<OutboxEntry>> pendingAll();             // every brain, for the combined view
  Future<OutboxEntry> enqueue(String brainId, String text,
      String idempotencyKey, String capturedAt);
  Future<void> updateText(String id, String text);    // keeps key, marks edited
  Future<void> markAccepted(String id);
  Future<void> markConflict(String id);               // original accepted; keep edit
  Future<void> requeueAsNew(String id);               // deliberate new capture, new key
}

abstract interface class AnswerSnapshotRepository {
  // AnswerSnapshot is self-contained: question, answer text, answered-at time,
  // and a full copy of the evidence items shown at answer time. Graph record
  // IDs ride along only as links into the current graph; rendering the
  // snapshot never reads live records.
  Future<void> save(String brainId, AnswerSnapshot snapshot); // only successful asks
  Future<List<AnswerSnapshot>> find(String brainId, String query);
  Future<void> delete(String id);
}

abstract interface class GraphWorkspaceRepository {
  Future<Workspace?> load(String brainId);
  Future<void> save(String brainId, Workspace workspace); // nodes, edges, flags, fetchedAt
}
```

Sync engine contract:

```dart
/// Retries every profile's outbox. Per entry:
///  200 -> markAccepted
///  409 -> markConflict (original accepted; edited text stays recoverable)
///  transport error -> leave pending
/// Runs on app open and resume. No background scheduling.
Future<SyncReport> syncAll(BrainGateway Function(BrainProfile) gatewayFor);
```

Workspace rules (owned by the explore controller):

- Opening a node online refreshes that node and adds its connections.
- Following an edge loads the destination and its connections; new edges from refresh connect to unloaded destinations unless the destination is already loaded.
- First Explore visit per app launch renders the saved workspace immediately, then runs a background batch refresh of expanded nodes; manual Refresh repeats it.
- Confirmed-missing nodes and edges render dimmed and stay; Clear deleted removes them locally without a server call; Clear workspace empties the workspace (confirmed action).
- A failed refresh leaves cached data unchanged and unmarked.

### Interaction Mocks

- `docs/mocks/android-workflows/index.html` — Capture and outbox retry/edit/conflict, Ask with automatic snapshots and history, Explore search/canvas/detail with refresh, dimming, and clear-deleted, Brain profile add/update-address/switch, offline and reopen-app behavior.

### Technology Choices

- **Client persistence: sqflite** — transactional multi-record storage for profiles, outbox, snapshots, workspaces. Rejected: `SharedPreferences` (single-record, weak fit for growing related data), Drift (typed queries and codegen not worth the added dependency set).
- **Graph canvas: custom Flutter canvas inside `InteractiveViewer`** — supports distinct directed edges, unloaded edge endpoints, per-item selection, and dimming. Rejected: `graphview` (layout-first, edge identity too weak), `flutter_force_directed_graph` (collapses parallel edges between the same nodes).
- **Graph API: HTTP JSON routes** — client follows paths one hop at a time; batch refresh covers the multi-node case. Rejected: GraphQL (schema and runtime overhead without a query-shape benefit for this access pattern).

### DR Supersessions

- **DR-004** (Android-First Flutter Client with a Typed Gateway Seam) — superseded in part. The single-draft `shared_preferences` storage decision no longer holds: sqflite replaces it for multi-record local data. The rest of DR-004 (Android-first Flutter, the injected `BrainGateway` seam, focused packages, Makefile targets outside `check-all`) carries into the replacement record with provenance.

## Tests

**Pre-test-write commit:** `81dc0b818c63d83c3f1b518705ca186541fd4c71`

### Interface Files

- `src/http/contracts.ts` — Search and batch graph-refresh response projections and application operations.
- `src/http/schemas.ts` — Request and response schemas for search and graph refresh.
- `src/http/server.ts` — HTTP boundary routes for search and batch graph refresh.
- `src/application/composition.ts` — Structural application stubs for the new operations.
- `client/mobile/lib/src/gateway/brain_gateway.dart` — Extended graph gateway capability and compatibility adapters.
- `client/mobile/lib/src/gateway/http_brain_gateway.dart` — Gateway stubs for search, node detail, and batch refresh.
- `client/mobile/lib/src/gateway/models.dart` — Search, graph detail, and refresh result projections.
- `client/mobile/lib/src/persistence/models.dart` — Brain, outbox, snapshot, and workspace data shapes.
- `client/mobile/lib/src/persistence/repositories.dart` — Profile, outbox, snapshot, and workspace repository contracts.
- `client/mobile/lib/src/sync/sync_engine.dart` — Foreground sync report and engine contract.
- `client/mobile/lib/src/explore/explore_controller.dart` — Explore workspace state and controller contract.
- `client/mobile/lib/second_brain_mobile.dart` — Public exports for the Android workflow interfaces.

### Test Files

- `tests/android-workflows.test.ts` — Search, graph refresh, ingest replay/conflict, and permanent intake-key behavior.
- `client/mobile/test/android_gateway_test.dart` — Search, graph detail, and batch refresh gateway behavior.
- `client/mobile/test/android_repositories_test.dart` — Brain profile, outbox, snapshot, and workspace persistence behavior.
- `client/mobile/test/android_sync_engine_test.dart` — Accepted, conflict, pending, and all-profile sync outcomes.
- `client/mobile/test/android_explore_controller_test.dart` — Explore refresh, edge following, missing-item cleanup, and workspace clear behavior.

### Behaviors Covered

#### HTTP and storage boundary

- Search returns organized nodes and unprocessed chunks as separate collections.
- Search accepts a bounded query and optional result limit.
- Batch graph refresh preserves requested order and distinguishes found nodes from confirmed missing nodes.
- Replayed intake returns the original count, while changed content under the same key returns conflict.
- Intake keys survive chunk cleanup and continue enforcing the original fingerprint.

#### Mobile gateway

- Hybrid search exposes graph nodes and raw chunks without an answer-generation call.
- Single-node graph reads expose directed connections.
- Batch refresh exposes found details and confirmed missing records in request order.

#### Persistence repositories

- Brain profiles begin disconnected, can be selected, and clear Access credentials when their address changes.
- Outbox entries preserve idempotency keys through edits, remove accepted entries, retain conflicts, and requeue deliberate new captures with new keys.
- Answer snapshots save only successful answers as self-contained evidence and support query and deletion operations.
- Workspaces persist independently per Brain profile with nodes, edges, status flags, and refresh time.

#### Sync engine

- Foreground sync retries every profile's outbox.
- Accepted entries leave the outbox.
- Conflicts retain edited text for recovery.
- Transport failures leave entries pending.

#### Explore workspace controller

- Opening a node and following an edge refresh the destination and merge connections into the workspace.
- Saved workspace data renders before expanded-node refresh.
- Failed refresh leaves cached data unchanged and unmarked.
- Clear deleted removes only confirmed missing items.
- Clear workspace removes all local workspace data after confirmation.
