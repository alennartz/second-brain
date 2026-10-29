# Review: Android workflows

**Plan:** `docs/plans/android-workflows.md`
**Diff range:** `2544ab3e8f924e0228844a2025b2517d0b61bbdf..1fd564ed517d1b1268b6405800b58532fcb67704`
**Date:** 2026-10-29

## Summary

The fix commits resolve most prior findings, including the compile gap, sync data-loss race, stale credentials, Explore lifecycle, and graph-link navigation. The fixes leave one critical test-baseline violation and several residual or newly introduced contract and reliability issues. This review covers only the changes after the previous review.

## Prior Findings Verification

| # | Prior finding | Status | Verification |
|---:|---|---|---|
| 1 | Required settings and error APIs were missing | Resolved | The required settings, secret-store, and configuration error APIs now exist in the reviewed range. |
| 2 | Frozen tests changed after the test-writing baseline | **Open** | `tests/storage.test.ts` remains changed after the frozen baseline. The fix commits also change existing mobile tests. |
| 3 | Sync could delete a concurrent edit or requeued capture | Resolved | Acceptance now checks the sent key and text before deleting the row. |
| 4 | Cached gateways kept old credentials | Resolved | Explore operations resolve the current profile gateway for each operation. |
| 5 | Whitespace search returned `503` | Resolved | Blank-after-trimming queries now map to `400`. |
| 6 | Editing a conflict enabled automatic resubmission | Resolved | Editing preserves the conflict state. |
| 7 | Explore missed automatic refresh updates | Resolved | The screen now rebuilds after `refreshCompleted`. |
| 8 | Answer graph links bypassed the workspace | Resolved | Links now open through the source Brain's Explore controller. |
| 9 | Following an edge kept the old detail node selected | Resolved | Detail rendering now prefers the controller's selected node. |
| 10 | Answer history search removed its text field | Resolved | Loading progress is inline while the field remains mounted. |
| 11 | Workspace transitions could resurrect cleared data | Resolved | State transitions are ordered and refresh generations invalidate stale work. |
| 12 | Address changes could retain old credentials | Resolved | Credential deletion precedes the address update. |
| 13 | Migration could mark completion before credentials persisted | Resolved | Credentials are saved before the migration transaction and marker. |
| 14 | Batch refresh ran unbounded concurrent scans | Resolved, deferred | Refresh reads are sequential now. Full edge scans remain a storage optimization for a separate change. |
| 15 | Conflicts had no discard path | Resolved | A confirmed conflict-discard operation and UI affordance now exist. |
| 16 | Canvas did not keep unloaded and parallel edges distinct | **Partly open** | Endpoint placement and pair-local offsets are fixed, but parallel-edge tap labels still overlap. |
| 17 | Older controller or search responses overwrote newer state | Resolved | Controller identity and search generations are checked, and Brain changes clear search state. |
| 18 | Production imported FFI and stored host secrets insecurely | Resolved, with a new default issue below | FFI is injected and host files receive mode `0600`. The host fallback is no longer selected by the default store construction. |
| 19 | Aliases and legacy shells made interfaces shallow | Resolved by compatibility decision | Compatibility aliases remain deliberate transitional interfaces. Retirement belongs in a separate interface-deprecation pass. |
| 20 | Public stubs and aliases remained | **Partly open** | Most stubs were removed, but the Explore loader, `FileSecretStore`, and codec aliases remain. |

## Findings

### 1. Frozen contract tests remain mutable

- **Category:** plan deviation
- **Severity:** critical
- **Location:** `tests/storage.test.ts:315-316,359-361`; existing mobile test files changed by `e28c59e`
- **Status:** open
- **Fix:** Restore the frozen tests and place contract changes in the approved test-writing phase.

The fix range still changes tests after the test-writing baseline. Step 12 requires approved contract tests to remain unchanged and requires implementation fixes when they fail.

### 2. Parallel-edge tap labels still overlap

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/lib/src/explore/graph_canvas.dart:254-307,358-379`
- **Status:** open
- **Fix:** Size and position each edge action target from its pair-local rank so parallel targets do not overlap.

The fix gives parallel edges pair-local offsets, but each action label remains about 160 pixels wide while adjacent edges differ by only 24 pixels. Vertical and diagonal parallel edges therefore still hit the same target, so the approved distinct-edge interaction remains unreliable.

### 3. Leftover public stubs and aliases remain

- **Category:** code correctness
- **Severity:** nit
- **Location:** `client/mobile/lib/src/explore/explore_controller.dart:249-253`; `client/mobile/lib/src/persistence/host_secret_store.dart:94`; `client/mobile/lib/src/persistence/codecs.dart:121,125,226`; `client/mobile/lib/src/persistence/brain_profile_repository.dart:201`
- **Status:** open
- **Fix:** Delete the unused Explore loader, `FileSecretStore`, codec aliases, and the stray doc comment.

The fix removes most dead construction paths, but these remaining exported or reachable aliases and the loader duplicate the implemented seams. The unused `FileSecretStore` also keeps the host-only implementation in the public library surface.

### 4. Host and non-mobile store defaults no longer use the planned fallback

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `client/mobile/lib/src/persistence/mobile_store.dart:39-53`; `client/mobile/lib/src/persistence/host_secret_store.dart:63-67`
- **Status:** open
- **Fix:** Select the platform sqflite and secure store on mobile, and the injected FFI and durable file-backed store on host and non-mobile targets.

`openMobileStore` now defaults to the platform database plugin and `FlutterSecureSecretStore` on every platform. Host and non-mobile callers no longer receive the durable FFI and file-backed fallback required by the plan. `HostSecretStore` explicitly throws on Windows.

### 5. Conditional acceptance changed the approved repository contract

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `client/mobile/lib/src/persistence/repositories.dart:40`; `client/mobile/lib/src/persistence/capture_outbox_repository.dart:50-68`
- **Status:** open
- **Fix:** Keep `Future<void> markAccepted(String id)` and add a separate conditional-acceptance operation, or update the approved contract and every adapter together.

The race fix changes `markAccepted` to return `Future<bool>` and requires sent-version parameters. This breaks the repository interface recorded in the approved plan.

### 6. Existing one-argument settings construction no longer compiles

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `client/mobile/lib/src/persistence/settings_store.dart:93-104`
- **Status:** open
- **Fix:** Make `secretStore` optional with a secure default, or update the documented compatibility contract and all callers.

`SharedPreferencesSettingsStore` now requires a named `secretStore`. Existing one-argument construction from the original shell is no longer source-compatible.

### 7. Workspace state survives a failed persistence write

- **Category:** code correctness
- **Severity:** nit
- **Location:** `client/mobile/lib/src/explore/explore_controller.dart:223-230,232-245`
- **Status:** open
- **Fix:** Roll back in-memory state when persistence fails, or mark the workspace dirty and retry the write.

`_persistAndSet` assigns the new state before awaiting the save. When the save fails, the caller sees an error but the screen keeps showing data that disappears after the next launch.

### 8. Empty Explore search can leave the progress indicator stuck

- **Category:** code correctness
- **Severity:** nit
- **Location:** `client/mobile/lib/src/screens/explore_screen.dart:413-445`
- **Status:** open
- **Fix:** Check for an empty query before incrementing the generation, or reset `_searching` on the empty-query path.

The search generation increments before the empty-query return. If the keyboard submits an empty query while another search is active, the active result is invalidated and `_searching` is not cleared.

### 9. The host secret implementation remains in the production library

- **Category:** code correctness
- **Severity:** nit
- **Location:** `client/mobile/lib/src/persistence/host_secret_store.dart:13-91,94`; exported by `client/mobile/lib/second_brain_mobile.dart:10`
- **Status:** open
- **Fix:** Move `HostSecretStore` into host/test code, or make its platform behavior complete and clean up temporary files on write failure.

The class now runs only in tests but remains exported from `lib/`. It starts a POSIX `chmod` process for every write, throws before its Windows rename fallback, and can leave a temporary file when writing fails.
