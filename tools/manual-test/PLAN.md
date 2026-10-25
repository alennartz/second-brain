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

1. First-launch server setup.
2. Capture success and stored chunk acknowledgement.
3. Failed Capture retention and explicit retry.
4. Ask recall and grouped evidence.
5. Capture and Ask submission while the keyboard is open.
