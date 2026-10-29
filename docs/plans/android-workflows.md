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
  Future<void> updateAddress(String id, String url,
      {({String clientId, String clientSecret})? credentials});
  // Clears old Access credentials, then saves a supplied replacement pair.
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

### Review-approved construction and lifecycle contracts

`client/mobile/lib/src/workflow_contract.dart` materializes the following public seams:

- `openMobileStore(path, legacy: ...)` opens durable repositories and migrates legacy settings once. Reopening the same path preserves records. Tests use isolated temporary paths.
- `MobileStore` exposes profile, outbox, answer, and workspace repositories plus `close`.
- `createSyncEngine(store)` injects the repositories that supply foreground sync work.
- `createExploreController(brainId, workspaces, gateway)` returns a controller after loading local workspace data, without requiring transport.
- `createMobileWorkflow(store, gatewayFor, now, newKey)` injects persistence, transport, time, and identity generation.

`MobileWorkflow` owns durable Capture and composer reset, automatic successful Ask snapshots, offline snapshot reopening, source-brain graph links, app-open/resume sync, and first Explore visit behavior. Each brain receives one automatic expanded-node refresh per workflow lifetime. A new workflow represents a new app launch. `visitExplore` returns cached state without awaiting transport. The controller's `refreshCompleted` future lets consumers await the scheduled refresh without timers.

`AnswerSnapshot.id` supplies the stable local history identity used for reopening and deletion. Repository tests verify stored evidence content, not object identity. Search chunk projections match `memory_search`, which omits an `unprocessed` flag. The gateway derives that marker from the separate unprocessed collection.

The Explore controller exposes `selectNode` and `state.selectedNodeId`. Canvas and detail views share this selection and loaded node/edge projection. Refresh keeps confirmed-missing edges as well as nodes. New connections retain directed edge identity without expanding destinations.

### Interaction Mocks

- `docs/mocks/android-workflows/index.html` — Capture and outbox retry/edit/conflict, Ask with automatic snapshots and history, Explore search/canvas/detail with refresh, dimming, and clear-deleted, Brain profile add/update-address/switch, offline and reopen-app behavior.

### Technology Choices

- **Client persistence: sqflite** — transactional multi-record storage for profiles, outbox, snapshots, workspaces. Access credentials remain in `FlutterSecureSecretStore`, keyed per profile. sqflite holds non-secret profile fields. `openMobileStore` accepts an optional `SecretStore`. Android defaults to secure storage. Other platforms use a durable file-backed store beside the database for host tests and non-mobile builds only. Host tests use dev-only `sqflite_common_ffi`, with a version compatible with the pinned Flutter 3.22.3 toolchain. Preserve legacy capture timestamps. If absent, assign the migration-time timestamp. Rejected: `SharedPreferences` (single-record, weak fit for growing related data), Drift (typed queries and codegen not worth the added dependency set).
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
- `client/mobile/lib/src/workflow_contract.dart` — Durable store opening/migration, injected construction, and foreground mobile journey contracts.

### Test Files

- `tests/android-workflows.test.ts` — Search, graph refresh, ingest replay/conflict, and permanent intake-key behavior.
- `client/mobile/test/android_gateway_test.dart` — Search, graph detail, and batch refresh gateway behavior.
- `client/mobile/test/android_repositories_test.dart` — Brain profile, outbox, snapshot, and workspace persistence behavior.
- `client/mobile/test/android_sync_engine_test.dart` — Accepted, conflict, pending, and all-profile sync outcomes.
- `client/mobile/test/android_explore_controller_test.dart` — Explore refresh, edge following, missing-item cleanup, shared selection, and workspace clear behavior.
- `client/mobile/test/android_workflow_test.dart` — Durable Capture and composer reset, automatic Ask snapshots, offline reopening, source-brain graph links, foreground lifecycle sync, and cached-first Explore visits.
- `client/mobile/test/android_contract_fixtures.dart` — Controlled transport and shared domain fixtures.

### Behaviors Covered

#### HTTP and storage boundary

- Search returns organized nodes and unprocessed chunks as separate collections.
- Search accepts a bounded query and optional result limit, including both limit boundaries.
- Invalid search/refresh input returns 400. Transport failures return 503 and never fabricate missing records.
- Production HTTP search matches the agent-facing hybrid search projection without generating an answer.
- Production batch refresh matches existing graph detail and preserves confirmed missing records.
- Batch graph refresh preserves requested order and distinguishes found nodes from confirmed missing nodes.
- Replayed intake returns the original count, while changed content under the same key returns conflict.
- Intake keys survive chunk cleanup and storage reopening, and continue enforcing the original fingerprint.

#### Mobile gateway

- Hybrid search exposes graph nodes and raw chunks without an answer-generation call.
- Single-node graph reads expose directed connections.
- Batch refresh exposes found details and confirmed missing records in request order.
- Search supports empty results. Gateway operations reject malformed payloads and expose HTTP and transport failures.

#### Persistence repositories

- Brain profiles begin disconnected, can be selected, and clear Access credentials when their address changes.
- Outbox entries preserve idempotency keys through edits, remove accepted entries, retain conflicts, and requeue deliberate new captures with new keys.
- Answer snapshots save only successful answers as self-contained evidence and support query and deletion operations.
- Workspaces persist independently per Brain profile with nodes, edges, status flags, and refresh time across reopening.
- Legacy settings and pending drafts migrate exactly once, preserving credentials, brain association, key, and capture time.
- Snapshot evidence includes graph content and connection IDs, survives reopening, and stays isolated per brain.

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
- Clear workspace removes all local workspace data after the explicit clear operation.
- Found-node refresh marks removed connections missing without erasing cached edges.
- New edges connect to loaded destinations without duplicates and do not expand unloaded destinations.
- Canvas and detail consumers share the controller's selected node and loaded graph projection.

#### Foreground mobile journeys

- Capture persists before transport completes and returns a clean composer.
- App open and resume retry inactive profiles' captures with unchanged identities.
- Successful Ask automatically saves question, answer, time, and displayed evidence. Failed Ask saves nothing.
- Answer snapshots reopen offline after store and workflow restart.
- Graph links retain the source brain after active-profile switching.
- First Explore visit renders saved data during a controlled pending refresh. Repeated visits retain the current projection. Relaunch permits a new automatic refresh.

**Review status:** approved

## Steps

**Pre-implementation commit:** `057a0bfe55e098a635323d2a76033b530a91649c`

### Step 1: Preserve intake receipts

Change `createIntakeChunks` in `src/storage/embedded.ts` to return the stored `chunk_count` for matching fingerprints. Keep mismatched fingerprints as conflicts. Remove intake-key deletion from `cleanup` and its chunk-deletion paths. Keep accepted keys through chunk consumption, discard, and database reopening. Do not recreate chunks on replay.

**Verify:** The intake-key persistence cases in `bun test tests/android-workflows.test.ts` pass. Existing storage and intake reliability tests retain their behavior.
**Status:** done

### Step 2: Implement graph application operations

In `src/application/composition.ts`, replace `search` and `refreshGraph` stubs. Import and call `searchMemory` from `packages/pi-second-brain/lib/graph.ts` without a model invocation. Extract the existing `getGraph` projection into a local reusable operation. Use it for single reads and batch refresh. Return results in requested order, including repeated IDs. Only a successful absent-node read returns `missing`. A failed batch rejects the whole operation.

Keep the existing routes and schemas in `src/http/server.ts` and `src/http/schemas.ts`. Ensure invalid search and refresh input returns 400 rather than Elysia's default validation status. Preserve existing error mapping for transport failures and ingest conflicts.

**Verify:** All cases in `bun test tests/android-workflows.test.ts` pass. Run `make check`.
**Status:** done

### Step 3: Implement graph gateway decoding

Replace graph stubs in `client/mobile/lib/src/gateway/http_brain_gateway.dart`. Send search and refresh JSON to their POST routes. Encode graph record IDs for GET requests. Reuse `_send`, `_requestHeaders`, and existing node/edge validation. Decode found and missing refresh variants in response order. Reject malformed successful payloads.

Search uses the separate `unprocessed` collection to set `IntakeChunk.isUnprocessed`. Do not require the recall-only wire marker for search chunks. Preserve recall validation. Node projections use the table supplied by the server, or derive it from the canonical ID when absent. Keep the approved `BrainGraphGateway` compatibility adapter in `brain_gateway.dart`.

**Verify:** `flutter test test/android_gateway_test.dart test/gateway/http_brain_gateway_test.dart` passes from `client/mobile`.
**Status:** done

### Step 4: Open durable local storage

Use `flutter pub add` to add sqflite. Add `sqflite_common_ffi` with `flutter pub add --dev`, selecting a Flutter 3.22.3-compatible version. Never edit dependency manifests by hand.

Create `client/mobile/lib/src/persistence/mobile_store.dart` behind `MobileStore`. Implement database opening, versioned schema creation, repository construction, and safe repeated `close`. Keep profile selection, outbox, snapshot, workspace, and migration records durable. Android uses sqflite's platform factory. Host execution uses the approved FFI adapter.

Extend `openMobileStore` in `workflow_contract.dart` with optional `SecretStore` injection. Retain `FlutterSecureSecretStore` on Android. Create `persistence/host_secret_store.dart` for the approved durable non-mobile fallback beside the database. Keep Access credentials out of SQLite. Add lossless domain codecs in `persistence/codecs.dart` for both evidence variants, graph nodes, directed edges, workspace flags, and timestamps.

**Verify:** Store opening and reopening use isolated test paths without platform-channel failures. Dependency resolution and analysis succeed in the pinned mobile toolchain container.
**Status:** done

### Step 5: Implement profiles and outbox

Create `persistence/brain_profile_repository.dart` and `persistence/capture_outbox_repository.dart` as SQLite adapters. Wire them through `MobileStore`, replacing repository stubs at construction.

Profiles save offline as Never connected. Persist active selection and connection history independently of address changes. Extend `updateAddress` in `repositories.dart` with the approved optional replacement credential pair. Clear old credentials, then save a supplied pair through the profile-keyed secret store. Hydrate credentials when listing or reading profiles.

Outbox entries preserve brain, text, key, capture time, and state. Edits keep the original key. Acceptance removes the entry. Conflict keeps edited content recoverable. Requeue-as-new changes the key and returns the retained text to pending. Use the existing UUID package for repository-generated identities.

**Verify:** Profile and outbox cases in `flutter test test/android_repositories_test.dart` pass, including reopening.
**Status:** done

### Step 6: Persist snapshots, workspaces, and migration

Create `persistence/answer_snapshot_repository.dart` and `persistence/graph_workspace_repository.dart`. Save self-contained snapshots with stable IDs and complete displayed evidence. Search local question and answer text within the requested brain. Delete by snapshot ID. Store each brain's workspace independently, including directed edge identity, expansion flags, status flags, and refresh time.

Implement migration in `mobile_store.dart`. Read legacy configuration and pending Capture through `settings_store.dart`. Convert them to `LegacyMobileData` at startup. Preserve credentials, key, and capture time. Assign migration-time capture time only when absent. Commit the profile, associated outbox entry, and migration marker together. An open without legacy data must not prevent a later supplied migration. Repeated migration must not duplicate records.

**Verify:** All cases in `flutter test test/android_repositories_test.dart` pass. Legacy data survives reopen exactly once.
**Status:** in progress

### Step 7: Deliver foreground outboxes

Implement `SyncEngine` in `client/mobile/lib/src/sync/sync_engine.dart` and wire `createSyncEngine` in `workflow_contract.dart`. Read all profiles and outbox entries, not only the active profile. Resolve each entry's gateway from its saved brain. Deliver with unchanged key and capture time. Map acceptance, 409, and transport failure to the approved repository outcomes and `SyncReport`. Skip retained conflicts until deliberate requeue.

**Verify:** `flutter test test/android_sync_engine_test.dart` passes. Inactive brains receive their own captures and conflicts never resubmit automatically.
**Status:** in progress

### Step 8: Implement workspace transitions

Implement the controller behind `client/mobile/lib/src/explore/explore_controller.dart`. Wire `createExploreController` to load saved data without transport. Keep controller state instance-local and return immutable projections. Use pure merge functions over explicit cached state and refresh results.

Opening a node selects and expands it. Following a directed edge loads the other endpoint relative to selection. Merge edges by canonical edge ID, preserving parallel edges. Refresh only expanded nodes in batches of at most 200. Apply a successful refresh as one state transition. Mark absent connections and confirmed-missing nodes and incident edges missing, retaining cached content. Mark new connections new without expanding destinations. A failed refresh leaves data and flags unchanged.

Implement shared selection, local Clear deleted, persisted Clear workspace, and `refreshCompleted`. Persist successful workspace changes. Clear deleted also removes edges incident to removed nodes and clears invalid selection. Keep cached layout stable when adding nodes and edges.

**Verify:** `flutter test test/android_explore_controller_test.dart` passes. Both selection consumers see the same projection.
**Status:** not started

### Step 9: Implement mobile journeys

Create `client/mobile/lib/src/mobile_workflow.dart` and replace construction stubs in `workflow_contract.dart`. Inject store, profile gateway factory, clock, and key generation. Capture durably enqueues before resetting the composer and returning. Start delivery without delaying that return.

Ask resolves the source brain before transport. Save a successful answer, displayed evidence, generated snapshot ID, and injected answer time before returning. Failed Ask saves nothing. Reopen reads only local snapshots. Graph links use their supplied source brain even after switching profiles.

Route app-open and resume operations through foreground sync. Cache Explore controllers per brain for this workflow lifetime. `visitExplore` returns loaded cache without awaiting transport and schedules only one automatic expanded-node refresh per brain. A new workflow permits another automatic refresh.

**Verify:** `flutter test test/android_workflow_test.dart` passes, including controlled pending transport, offline reopening, source-brain links, and relaunch refresh.
**Status:** not started

### Step 10: Connect Capture, Outbox, and Brains

Update `client/mobile/lib/main.dart` to open the durable store, migrate legacy values, and construct one workflow per app launch. Update `src/mobile_application.dart` to use durable repositories and observe app resume. Keep existing Access request protection and unrelated concurrent changes intact.

Update `screens/capture_screen.dart` to use the workflow composer and local-first save. Add `screens/outbox_screen.dart` and `screens/brains_screen.dart`. Adapt `screens/server_settings_screen.dart` for add and update forms. Match `docs/mocks/android-workflows/index.html`: combined outbox badge, entries grouped by brain, retry pending, edit/cancel, conflict review, and Capture edit as new. Brains lists active selection and connection history. Save profiles offline, switch without deleting local records, and accept fresh credentials on address update. Health failure must not prevent saving or using a profile.

**Verify:** Existing mobile tests retain their supported contracts. The approved mock's offline Capture, edit/conflict recovery, add/update/switch, and reopen journeys work on Android.
**Status:** not started

### Step 11: Render Answer history and Explore

Update `screens/ask_screen.dart`, `screens/recall_result_screen.dart`, and `widgets/evidence_cards.dart` to display saved snapshots rather than refetching answers. Add `screens/answer_history_screen.dart` with local search, offline reopening, and confirmed deletion. Raw evidence has no graph-opening action. Graph evidence links retain the snapshot's source brain.

Add `screens/explore_screen.dart`, `screens/graph_node_detail_screen.dart`, and `explore/graph_canvas.dart`. Use a custom canvas within `InteractiveViewer`, with selectable nodes and distinct directed edge actions. Render unloaded endpoints, parallel edges, new markers, and dimmed missing items. Canvas and detail use controller selection and data. Preserve cached workspace during pending or failed refresh. Provide search results with separate raw chunks, empty/offline/error states, manual Refresh, local Clear deleted, and confirmed Clear workspace.

Add Explore to the main navigation in `mobile_application.dart`. Match the mock's search-to-detail, edge following, pan/zoom, back-to-map, missing/new refresh states, and empty workspace. Return from Outbox and Brains to the originating journey.

**Verify:** All Android contract tests and existing mobile tests pass. Walk through every approved Ask/history and Explore flow on Android, including offline snapshots and cached-first relaunch.
**Status:** not started

### Step 12: Check the complete workflow

Run `make check`, the mobile analysis/test container workflow, and `make mobile-build`. Keep approved contract tests unchanged. Resolve failures in implementation, not test expectations. Update `client/mobile/lib/second_brain_mobile.dart` exports for concrete construction as needed. Do not add manual smoke journeys here. The architecture assigns those to the manual-test phase.

**Verify:** Server checks, Flutter analysis, mobile tests, and Android APK build succeed with the pinned toolchain. No production constructor returns an interface stub.
**Status:** not started
