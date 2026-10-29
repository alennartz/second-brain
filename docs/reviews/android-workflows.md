# Review: Android workflows

**Plan:** `docs/plans/android-workflows.md`
**Diff range:** `81dc0b818c63d83c3f1b518705ca186541fd4c71..2544ab3e8f924e0228844a2025b2517d0b61bbdf`
**Date:** 2026-10-29

## Summary

The implementation covers most planned server, persistence, sync, and Explore work, but the reviewed range does not compile. Several workflow defects also cause data loss, stale UI, or broken graph navigation. The review found critical build and test-baseline violations plus additional correctness and design risks.

## Findings

### 1. Required settings and error APIs are outside the reviewed range

- **Category:** plan deviation
- **Severity:** critical
- **Location:** `client/mobile/lib/src/persistence/settings_store.dart`, `client/mobile/lib/src/gateway/errors.dart`; consumers in `client/mobile/lib/main.dart`, `client/mobile/lib/src/persistence/mobile_store.dart`, `client/mobile/lib/src/gateway/http_brain_gateway.dart`, and `client/mobile/lib/src/screens/server_settings_screen.dart`
- **Status:** resolved
- **Fix:** Commit the required `ServerConfiguration`, `SecretStore`, `FlutterSecureSecretStore`, `loadServerConfiguration`, `secretStore`, and `ConfigurationException` changes in the reviewed range.

The reviewed range leaves the old settings and error APIs unchanged while new production files reference symbols and constructors that do not exist there. The exact range cannot compile. Uncommitted working-tree edits do not satisfy the plan or this review.

Resolution: Added the required settings, secret, and configuration error APIs in commit 8b4580a.

### 2. Frozen tests changed after the test-writing baseline

- **Category:** plan deviation
- **Severity:** critical
- **Location:** `tests/storage.test.ts:315-316,359-361`
- **Status:** resolved
- **Fix:** Restore the frozen tests and place any contract changes in the approved test-writing phase.

The final verification commit changes existing test expectations after the `pre-test-write-commit` baseline. Step 12 requires approved contract tests to remain unchanged and requires implementation fixes when they fail.

### 3. A successful sync can delete a concurrent edit or requeued capture

- **Category:** code correctness
- **Severity:** critical
- **Location:** `client/mobile/lib/src/sync/sync_engine.dart:58-99`; `client/mobile/lib/src/persistence/capture_outbox_repository.dart:39-56,70-83`
- **Status:** resolved
- **Fix:** Make acceptance conditional on the sent key and text, and retain the row when the sent version no longer matches.

The engine reads an entry, sends it, and then deletes by ID. An edit or requeue during the request changes the row, but the later `200` response still deletes it. Capture starts delivery immediately, so this race can silently lose user data.

### 4. A cached gateway keeps using old credentials after an address update

- **Category:** code correctness
- **Severity:** critical
- **Location:** `client/mobile/lib/src/mobile_workflow.dart:60-62,145-189`
- **Status:** resolved
- **Fix:** Resolve the gateway for each operation, or invalidate cached controllers when a profile address or credential changes.

Explore controllers retain the gateway created on first visit for the rest of the workflow. After an address update, Explore and offline graph-link fallback can still send requests to the old URL with credentials captured before the update.

### 5. Whitespace-only search returns `503` instead of `400`

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `src/http/schemas.ts:38`; `src/application/composition.ts:124-130`; `packages/pi-second-brain/lib/graph.ts:41-43,112-115`; `src/http/server.ts:7-12`
- **Status:** resolved
- **Fix:** Reject `query.trim().isEmpty` as invalid input and map it to `400`.

The schema accepts a whitespace-only query because `minLength: 1` counts spaces. `searchMemory` then throws a generic error, which the HTTP boundary maps to `503`. The plan requires invalid search input to return `400`.

### 6. Editing a conflict makes it eligible for automatic resubmission

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `client/mobile/lib/src/persistence/capture_outbox_repository.dart:39-48`; `client/mobile/lib/src/sync/sync_engine.dart:49`
- **Status:** resolved
- **Fix:** Preserve `OutboxState.conflict` when editing a conflicted entry; only `requeueAsNew` can return it to `pending`.

`updateText` always changes the state to `edited`. The next foreground sync then resubmits the already-accepted idempotency key, violating the rule to skip retained conflicts until deliberate requeue.

### 7. Explore does not rebuild after the automatic refresh

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `client/mobile/lib/src/explore/explore_controller.dart:28-45,95`; `client/mobile/lib/src/screens/explore_screen.dart:72-79,374-385`; `client/mobile/lib/src/mobile_workflow.dart:165-189`
- **Status:** resolved
- **Fix:** Subscribe the screen to controller changes or await `refreshCompleted` and rebuild when the scheduled refresh settles.

`visitExplore` starts a background refresh, but the screen only rebuilds when the controller future resolves. Updated, missing, or new graph items remain invisible until another user action, contrary to the cached-first refresh flow.

### 8. Answer graph links bypass the Explore workspace

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `client/mobile/lib/src/mobile_application.dart:662-711`; `client/mobile/lib/src/mobile_workflow.dart:139-143`; `client/mobile/lib/src/screens/graph_node_detail_screen.dart:172-180`
- **Status:** resolved
- **Fix:** Open answer links through the source Brain's Explore controller, merge the node and connections, and pass that controller to the detail screen.

Online answer links push a detail screen with raw node data and no workspace controller. The node is not persisted in Explore, and connection taps are no-ops because the detail screen has no controller.

### 9. Following an edge keeps the first detail node selected

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/lib/src/screens/graph_node_detail_screen.dart:44-66,157-200`; caller `client/mobile/lib/src/screens/explore_screen.dart:443-452`
- **Status:** resolved
- **Fix:** Use the fixed `nodeId` only for initial selection, then render `state.selectedNodeId` after `followEdge`.

The detail screen gives `widget.nodeId` priority over the controller selection. Following an edge changes controller state but leaves the first node on screen. A later edge action then calculates direction from the wrong node.

### 10. Answer history search removes its own text field on every keystroke

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/lib/src/screens/answer_history_screen.dart:97-98,157-187`
- **Status:** resolved
- **Fix:** Keep the search field mounted while loading and show progress inline, or debounce queries without replacing the field.

Each keystroke sets `_loading`, and the loading branch replaces the widget tree containing the `TextField`. The field loses focus and the keyboard closes after the first character on Android.

### 11. Workspace transitions can overwrite clears and resurrect a cleared workspace

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/lib/src/explore/explore_controller.dart:98-110,127-233`
- **Status:** resolved
- **Fix:** Serialize state transitions and invalidate in-flight refreshes after `clearWorkspace`.

`_persistAndSet` awaits persistence before assigning memory state. Concurrent selection or clearing can be overwritten, leaving memory and disk inconsistent. A refresh that completes after `clearWorkspace` can also merge data back into the empty workspace.

### 12. Profile address changes can leave old credentials attached

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/lib/src/persistence/brain_profile_repository.dart:63-86`
- **Status:** resolved
- **Fix:** Delete old credentials before committing the new address, or roll back the address when credential deletion fails.

`updateAddress` commits the URL before deleting old credentials. If secret-store deletion fails, the profile retains old credentials and can send them to the new host.

### 13. Migration can mark completion before credentials are durable

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/lib/src/persistence/mobile_store.dart:196-256`
- **Status:** resolved
- **Fix:** Write credentials before committing the migration marker, or retry credential migration when the marker exists without credentials.

The migration transaction commits before `_saveCredentials` runs. A secret-store failure leaves a profile without credentials while the marker prevents a later migration retry.

### 14. Batch graph refresh performs hundreds of full edge scans

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/application/composition.ts:74-80,131-137`; `src/storage/embedded.ts:39,103-104`
- **Status:** resolved
- **Fix:** Load and index edges once per batch, or at minimum bound refresh concurrency.

Each requested ID invokes `allEdges()` for incoming and outgoing edges. A 200-ID refresh starts up to 400 concurrent full scans, and each phone launch can trigger this work.

### 15. Conflict entries have no discard path

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `client/mobile/lib/src/screens/outbox_screen.dart:104-113,184-219`; `client/mobile/lib/src/persistence/repositories.dart:26-47`; `client/mobile/lib/src/persistence/capture_outbox_repository.dart:39-48`
- **Status:** resolved
- **Fix:** Add a confirmed discard operation for retained conflicts and keep conflict state when editing.

A conflict can only be requeued as a new capture. Users cannot discard an unwanted conflict, so it remains in the combined outbox and keeps its badge indefinitely.

### 16. Canvas positions do not preserve distinct unloaded and parallel edges

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/lib/src/explore/graph_canvas.dart:128-180,327-379,464-471`
- **Status:** resolved
- **Fix:** Allocate one position per unloaded endpoint outside the loaded grid and offset parallel edges by their pair-local rank.

Unloaded endpoints use a fixed slot while edge lines use a different index. The unloaded column overlaps loaded nodes, only three slots exist, and global modulo offsets place some parallel edges together. This breaks readable and distinct edge selection.

### 17. Older controller and search responses can overwrite newer state

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/lib/src/screens/explore_screen.dart:81-104,374-414`
- **Status:** resolved
- **Fix:** Ignore responses that do not belong to the current controller or search generation, and clear search results when the Brain changes.

A prior controller load or search can finish after a newer request and overwrite current state. Profile changes also retain the previous search result.

### 18. Production code imports FFI and can store host secrets in plaintext

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/lib/src/persistence/mobile_store.dart:1-8,65-69,88-93`; `client/mobile/lib/src/persistence/host_secret_store.dart:11-14,61-73`
- **Status:** resolved
- **Fix:** Inject the database factory and secret store from host/test entry points, and create any host secret file with mode `0600`.

The production library imports the dev-only FFI adapter, and the non-mobile fallback writes Access credentials to a plaintext JSON file with default permissions. This expands the release surface and exposes credentials on host builds.

### 19. Multiple aliases and legacy shells make the client interface shallow

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/lib/src/mobile_application.dart:29-95,160-292,733-872`; `client/mobile/lib/src/screens/explore_screen.dart:21-53`; `client/mobile/lib/src/screens/graph_node_detail_screen.dart:12-33`; `client/mobile/lib/src/screens/answer_history_screen.dart:17-45`; `client/mobile/lib/src/screens/recall_result_screen.dart:20-41`; `client/mobile/lib/src/widgets/evidence_cards.dart:7-22`; `client/mobile/lib/src/explore/graph_canvas.dart:16-43`
- **Status:** resolved
- **Fix:** Keep one name for each input and delete unreachable legacy construction paths.

The same concepts use several parameter names, and production retains SharedPreferences-era shells beside the durable workflow. These wide, shallow interfaces obscure the real seam and leave unreachable behavior that can drift from the supported contract.

Resolution: Keep the compatibility aliases. Main and existing tests construct through them. Retiring them needs a separate interface-deprecation pass.

### 20. Public stubs and aliases remain after implementation

- **Category:** code correctness
- **Severity:** nit
- **Location:** `client/mobile/lib/src/sync/sync_engine.dart:108-121`; `client/mobile/lib/src/persistence/repositories.dart:65-154`; `client/mobile/lib/src/explore/explore_controller.dart:235-246,674-706`; persistence typedefs and codec aliases at `client/mobile/lib/src/persistence/answer_snapshot_repository.dart:77`, `brain_profile_repository.dart:199`, `capture_outbox_repository.dart:122`, `graph_workspace_repository.dart:43`, `host_secret_store.dart:83`, and `codecs.dart:121,125,226`
- **Status:** resolved
- **Fix:** Delete the unused stubs, typedef aliases, codec aliases, and the exported `syncAll` function that always throws `UnimplementedError`.

The implemented workflow leaves duplicate repository/controller stubs and aliases with no callers. The exported top-level sync function is especially misleading because it always fails at runtime.
