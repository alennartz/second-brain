# DR-009: Durable Multi-Profile Flutter Workflows and Graph Exploration

## Status
Accepted

## Context

Supersedes DR-004 (Android-First Flutter Client with a Typed Gateway Seam), deleted at commit `53d4108371ef96a9a7ce4251c4bd28429fc33150`.

The mobile client grew from Capture and one-shot Ask into three offline-capable journeys: reliable Capture, repeatable Answer snapshots, and read-only graph exploration. The original shared-preferences draft store could not safely represent named Brain profiles, per-profile outboxes, self-contained answer evidence, or growing graph workspaces. The server also needed a way to provide graph search and bounded refresh without invoking an answer model.

The client still needed to remain Android-first but portable and testable without a live server or device. Native Android would create a second implementation for later iOS packaging. A broad state-management or networking stack would add concepts before the client required them. SharedPreferences was a poor fit for related, transactional records; Drift added typed query code generation and another dependency set; GraphQL added schema and runtime overhead for one-hop REST access. `graphview` and `flutter_force_directed_graph` could not preserve directed parallel edges and unloaded endpoints reliably. Background scheduling was unnecessary for the required app-open and resume retries, and would add lifecycle and platform complexity.

## Decision

Keep the valid parts of DR-004: build an Android-first Flutter client with portable Dart, expose an injected typed `BrainGateway`, use `HttpBrainGateway` for REST transport and typed errors, keep focused packages (`http`, `flutter_markdown`, and `uuid`), and provide explicit mobile Makefile targets outside `check-all`.

Replace the single-draft local store with a versioned sqflite database. Persist Brain profiles, Capture outbox entries, Answer snapshots, and one graph workspace per Brain. Keep Access credentials in a profile-keyed secure secret store, and inject database and secret-store implementations for host tests and non-mobile callers. Migrate the legacy server configuration and pending draft once, preserving their Brain association, idempotency key, credentials, and capture time.

Deliver queued Captures in the foreground on app open and resume for every profile. Reuse each entry's idempotency key and capture time. Remove accepted entries, retain edited text after a conflict for deliberate recovery, and leave entries pending after transport failure. Do not add background scheduling.

Save each successful Ask as a self-contained local snapshot containing the question, answer, time, and displayed evidence. Keep graph record IDs only as links into the current graph. Reopen and search snapshots locally without a model call or live graph read.

Add REST `POST /search` and `POST /graph/refresh` operations. Search delegates to the existing hybrid `searchMemory` operation and returns graph nodes separately from unprocessed chunks. Batch refresh returns found node details or confirmed missing results in request order, with bounded input. Keep exploration read-only and persist one workspace per Brain. Render it with a custom canvas inside `InteractiveViewer` so directed edge identity, parallel edges, unloaded endpoints, selection, and dimmed missing records remain distinct. Show cached workspaces before a foreground refresh of expanded nodes; failed refreshes leave cached state unchanged.

## Consequences

- Captures, snapshots, and graph links remain isolated when users switch Brains, including while offline.
- The client gains durable schema, migration, repository, and conflict-recovery code. Local data needs retention and migration maintenance.
- Credentials never enter SQLite, but every host or non-mobile integration must inject compatible database and secret-store implementations.
- Foreground-only sync is predictable and testable, but queued work waits until the app opens or resumes.
- The server exposes more stable REST contracts and bounded refresh work without extra answer-model latency. Search and graph refresh now need validation, projection, and transport-error handling at both boundaries.
- A custom graph canvas preserves interaction semantics that generic layout packages lose, but the project owns layout, hit testing, and performance as the workspace grows.
- Flutter rendering and device networking remain separate from the server smoke suite; Android device coverage requires a connected device or emulator.
