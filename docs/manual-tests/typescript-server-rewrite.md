# Manual Testing — typescript-server-rewrite

## Smoke Suite

- Bun server health and fresh startup, because startup and reopen prove the
  replacement service owns its fresh schema.
- HTTP intake, queue, recall, and graph journeys, because these are the
  non-conversation HTTP contract.
- Restart and shutdown, because workers and storage must settle in order.
- Go CLI journey is noted but not run in this phase because this phase focuses
  on the fresh Bun server and no client changes are allowed.
- Android journey remains deferred because no physical device or emulator is
  available.

## Topic-Specific Tests

- Intake idempotency and pipeline pause/resume/discard controls.
- Recall and graph routes with locally available configuration.
- Dream job submission, polling, and terminal-state behavior.
- Removed conversation and MCP routes return ordinary missing-route responses.
- Direct and Codemode tool boundaries remain closed to filesystem, shell,
  network, MCP, and model-catalog capabilities.
- Shutdown and restart preserve the local database and do not use Python.

## Tools

- Reused: `curl` through `bash` for the HTTP API, `bun run src/main.ts` for
  the shipped Bun entry point, and the existing Bun SDK smoke tests for direct
  and Codemode boundaries.
- New: none.
- Improved: none.

## Harness Limitations

This run uses a local single-process shell harness and a local SurrealKV path.
It has no Docker daemon, live provider credentials, connected device, or
Android emulator. It cannot prove production-image startup, real model-backed
ingest/recall/dream behavior, concurrent clients, provider failures, or mobile
UI behavior. Deterministic SDK smoke tests cover tool boundaries but do not
replace live provider calls. These limits weaken provider-dependent primary
journeys, so those results are recorded as open or unavailable rather than
fabricated.

## Results

- **Bun startup, health, fresh initialization, and reopen — pass.** The shipped
  `src/main.ts` ran through the Bun 1.4.4 binary obtained with `npx`, using a
  temporary database and a wrapper that changed only the hard-coded port from
  8000 to an ephemeral port. `GET /health` returned `200 {"status":"ok"}`.
  The database created `LOCK`, manifest, and WAL files. A second process opened
  the same path and returned health `200` without migration. **Coherence:** looks
  coherent.
- **HTTP intake staging, idempotency, pipeline controls, recall, and graph —
  pass in a local stateful adapter harness; open for provider-backed staging.**
  The harness used the real embedded storage and HTTP adapter with a deterministic
  embedder. `POST /ingest` returned `{"chunks_stored":1}`, the matching retry
  returned `{"chunks_stored":0}`, and the queue snapshot exposed one ready
  chunk. Recall returned node evidence and a separate `unprocessed` chunk.
  Pause changed the queue to `paused:1`, resume restored `ready:1`, and discard
  returned `chunks_discarded:1` before the queue reached zero. Graph lookup
  returned canonical node and edge IDs; missing nodes returned `404`. The real
  shipped composition also returned `503` for `/ingest` with the dummy OpenAI
  key, so live embedding-backed staging remains unavailable without credentials.
  **Coherence:** looks coherent for the deterministic local journey.
- **Dream job lifecycle — pass for an empty local graph.** The shipped
  composition accepted `POST /dream` with `202` and a `Location` header. Polling
  returned a terminal `complete` job because the fresh graph had no work. The
  stateful adapter also exercised `pending` to `running` to `complete`, and an
  unknown job returned `404`. Provider-backed graph dreaming was not run.
  **Coherence:** looks coherent for an empty fresh database.
- **Removed conversation and MCP routes — pass.** `POST /converse`,
  `/converse/stream`, and `/mcp` each returned the framework's plain `404
  NOT_FOUND` response in the live server harness. **Coherence:** looks coherent.
- **Direct and Codemode tool boundaries — pass.** SDK-backed smoke checks passed
  for provider/model selection, direct structured tool calls, Codemode scripts
  consuming structured results, input/output schema failures, cancellation, and
  closed capabilities. Pi 1.4's Codemode proxy throws the documented
  `tools.<name> does not exist` error for unavailable filesystem, shell, network,
  MCP, and model-catalog names. The smoke script catches those guard errors and
  asserts that no unavailable direct tool is registered. **Coherence:** looks
  coherent.
- **Shutdown and restart — pass.** The local Bun process received `SIGTERM`,
  released its storage lock, and exited. A new process reopened the same path;
  health returned `200`, and the seeded graph and recall evidence persisted.
  **Coherence:** looks coherent.
- **Go CLI journey — open (not run).** This phase focused on the Bun server and
  did not change or invoke the Go client.
- **Android journey — open (unavailable).** No connected device or emulator
  exists in this environment.

## Plan Updates

Empty. The persistent plan already lists the Bun server journeys exercised by
this topic.

## Open Issues

- Live OpenAI embedding credentials are unavailable. Production `/ingest`
  returned `503` with the dummy key, so provider-backed staging and ingest-worker
  organization remain unverified.
- A separate process already occupied port 8000. The shipped entry point was
  exercised with an ephemeral-port wrapper; direct port-8000 binding remains
  unverified in this shared environment.
- Docker, Go CLI, and Android device journeys remain unexecuted by capability
  limits. No results were fabricated.
