# Manual Test Plan

## Bun server health and fresh startup

1. Copy `.env.example` to `.env` and set workflow models and credentials.
2. Start the server with `bun run src/main.ts` or `make dev`.
3. Request `GET /health` and verify `{"status":"ok"}`.
4. Confirm a new database directory exists at `BRAIN_DB_PATH`.
5. Stop and restart the server.
6. Request `GET /health` again and confirm the database opens without migration.

**Pass:** The Bun entry point starts, reports health, and reopens its fresh
latest-schema database.

## HTTP intake, queue, recall, and graph

1. Send `POST /ingest` with text, hints, source, and an idempotency key.
2. Confirm the response contains `chunks_stored` before organization completes.
3. Search with `POST /recall` and verify queued evidence appears separately.
4. Inspect `GET /ingest/pipeline` for ready, leased, retry, and worker counts.
5. Pause, resume, and discard one intake through the pipeline controls.
6. Poll `POST /dream` and `GET /dream/jobs/{job_id}`.
7. Read an organized node with `GET /graph/{record_id}`.
8. Retry the same ingest request with the same key and verify no duplicate
   chunks are stored.

**Pass:** Intake staging is synchronous, queue controls affect one intake,
recall keeps unprocessed evidence separate, graph lookup returns canonical IDs,
and dream jobs reach a terminal state.

## Go CLI

1. Build the client with `make build-client`.
2. Run `brain ingest` against the local server.
3. Run `brain recall` and verify grouped evidence.
4. Run `brain graph` with a canonical node ID.

**Pass:** The client uses the non-conversation HTTP contract without errors.

## Restart and shutdown

1. Stage an intake and confirm it appears in pipeline or recall output.
2. Stop the Bun process with SIGTERM.
3. Confirm the process releases workers before it closes storage.
4. Start it again and repeat the health, recall, and graph checks.

**Pass:** Shutdown settles active work and restart preserves the fresh database.

## Android Flutter client smoke journey

**Status:** deferred. The containerized toolchain supports checks and builds, but
no connected phone or Android emulator is available here.

Run this journey later in an Android emulator or real-phone environment:

1. Add a Brain profile, save it while offline, then connect and select it.
2. Capture while offline. Confirm the composer clears and the Capture appears in
   that Brain's Outbox. Reconnect and confirm sync removes the accepted entry.
3. Edit a queued Capture, then submit its original key with changed content.
   Confirm the conflict keeps the edit recoverable. Use Capture edit as new and
   confirm it creates a new entry.
4. Ask a question online. Confirm Answer history stores the question, answer,
   and displayed evidence. Restart offline and reopen the saved snapshot.
5. In Explore, search for a graph node, open its detail, and follow a connection.
   Refresh the workspace, restart offline, and confirm the cached graph opens.
   Confirm raw search chunks do not open graph records.
6. Add a second Brain and switch between profiles. Confirm each profile keeps
   its own Outbox, Answer history, and Explore workspace.

## Operational behavior

- A node-field validation failure is non-retryable. The worker pauses the intake
  before releasing its lease, so the same model error does not create unbounded
  duplicate notes. Resume the intake after correcting the model or data.
- Other provider failures retain at-least-once retry behavior. A successful graph
  mutation can replay before a later failed mutation or lease loss.
- Dream cycles have a bounded timeout. A timed-out cycle reports a failed dream
  job instead of leaving it `running`.
