# Test Review: Android workflows

**Plan:** `docs/plans/android-workflows.md`
**Brainstorm:** `docs/brainstorms/android-workflows.md`
**Date:** 2026-10-29

## Summary

The original tests lacked arranged state and left core mobile journeys untested. The revised tests exercise public construction, persistence, transport, and foreground workflow contracts. The user approved all gap closures, with no exclusions.

## Findings

### 1. Missing foreground journey and migration interfaces

- **Category:** missing coverage
- **Severity:** critical
- **Location:** `client/mobile/test/android_workflow_test.dart:29-144`, `client/mobile/test/android_repositories_test.dart:124-149`
- **Status:** resolved

The brainstorm requires durable Capture before transport, a clean composer, automatic successful Ask snapshots, offline reopening, foreground retries, and legacy migration. The original architecture lacked construction and lifecycle seams to exercise these requirements. With user approval, the plan and `workflow_contract.dart` now define durable store opening, migration, injected factories, and foreground journey operations. Tests cover each requirement, including source-brain links after profile switching.

### 2. Unarranged repository, sync, and Explore tests

- **Category:** wrong abstraction
- **Severity:** critical
- **Location:** `client/mobile/test/android_repositories_test.dart:9-149`, `client/mobile/test/android_sync_engine_test.dart:9-89`, `client/mobile/test/android_explore_controller_test.dart:11-139`
- **Status:** resolved

Repository tests edited records they never created. Sync tests supplied identical inputs but required incompatible reports. Controller tests asserted refresh and failure outcomes without supplying cached state or transport outcomes. With user approval, tests now create records through repository interfaces and inject controlled gateways through production construction seams. Each test owns isolated filesystem state and cleans it up without secondary setup-failure errors.

### 3. Missing graph refresh and workspace behavior

- **Category:** missing coverage
- **Severity:** critical
- **Location:** `client/mobile/test/android_explore_controller_test.dart:30-139`, `client/mobile/test/android_workflow_test.dart:108-144`
- **Status:** resolved

The brainstorm requires cached-first opening, first-visit background refresh, shared selection, new connections without destination expansion, and distinct confirmed-missing and unavailable states. The revised tests arrange those states and control refresh completion with futures. They check removed edges, retained destination nodes, local clearing, persistent workspace clearing, and source-brain isolation. User-approved interfaces expose shared selection and awaitable refresh completion.

### 4. HTTP fixtures could not satisfy their assertions

- **Category:** wrong abstraction
- **Severity:** critical
- **Location:** `tests/android-workflows.test.ts:94-191`, `client/mobile/test/android_gateway_test.dart:10-93`
- **Status:** resolved

Search and refresh route tests expected data from application methods that threw. The ingest test supplied no idempotency key and used an application that never rejected changed content. Gateway fixtures returned empty search data for every operation. Corrected fixtures now return the declared projections and arrange keyed replay/conflict behavior. Separate production application tests protect hybrid-search parity and batch graph refresh, rather than relying only on route delegation.

### 5. Persistence assertions omitted durable evidence and identity

- **Category:** missing coverage
- **Severity:** critical
- **Location:** `client/mobile/test/android_repositories_test.dart:18-122`, `tests/android-workflows.test.ts:223-243`
- **Status:** resolved

The never-connected test checked only the later connected state. Empty snapshot evidence could not protect offline reproducibility. Receipt tests did not reopen storage. Revised tests check initial profile status, retained connection history, per-brain isolation, graph content and link IDs, capture identity through conflicts, and persisted workspace flags after reopening. The receipt test now reopens storage after pipeline cleanup. The user approved these additions.

### 6. Missing validation and failure paths

- **Category:** missing coverage
- **Severity:** warning
- **Location:** `tests/android-workflows.test.ts:195-220`, `client/mobile/test/android_gateway_test.dart:94-129`
- **Status:** resolved

Tests now cover invalid limits, both accepted limit boundaries, the refresh batch bound, empty search results, malformed payloads, HTTP failures, and transport failures. They require the plan's 400 and 503 statuses without requiring exact error messages. Search fixtures match the agent-facing projection, which omits the unprocessed marker. The gateway derives that marker from the separate collection. The user approved this coverage.

### 7. Workspace persistence required object identity

- **Category:** over-specified
- **Severity:** warning
- **Location:** `client/mobile/test/android_repositories_test.dart:97-122`
- **Status:** resolved

The original workspace test required the loaded object to be the object passed to save. A correct database adapter reconstructs values. The revised test compares required node IDs, edge IDs, expansion state, flags, and refresh time across reopening.

## Validation

- Flutter analysis passes.
- TypeScript type checking passes.
- The 34 mobile contract tests compile and remain red at unimplemented gateway or construction interfaces.
- Corrected HTTP delegation tests pass. Production search and refresh remain unimplemented.
- HTTP validation currently returns 422 instead of the planned 400.
- The permanent receipt test exposes duplicate staging after cleanup and reopening.

These failures define implementation work. No implementation was added during this review. No tests use live networks, model responses, sleeps, random expected IDs, filesystem ordering, or private implementation details.
