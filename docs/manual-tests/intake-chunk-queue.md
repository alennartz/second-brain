# Manual Testing — intake-chunk-queue

## Smoke Suite

- **HTTP intake and recall:** Stage representative text through `POST /ingest`,
  verify the synchronous chunk count, inspect queued evidence in recall, and
  observe the worker drain. This is the primary shipped intake journey.
- **Pipeline operations:** Read the aggregate pipeline snapshot and exercise
  pause, resume, and discard against a staged intake document.
- **MCP intake and recall:** Use configured MCP staging and recall when a local
  transport exposes those tools. Verify queued counts and separate unprocessed
  citations.
- **Go CLI ingest:** Run `brain ingest` against the test-mode server and verify
  the synchronous chunk-count output.
- **Converse staging:** Exercise the non-Jev converse intake path when exposed.
  Jev routing remains owned by `jev-converse-routing` and its known failures are
  recorded as scope limitations.

## Topic-Specific Tests

- **Synchronous staging visibility:** Submit text with source metadata and an
  idempotency key. Confirm the response arrives before worker completion and
  the pipeline exposes queue state.
- **Hybrid recall of unprocessed evidence:** Recall a distinctive phrase while
  its chunks remain queued. Confirm the response labels evidence as unprocessed
  and does not present chunk IDs as graph nodes or edges.
- **Background drain and introspection:** Wait for the worker to settle. Confirm
  ready, leased, retry, and paused counts change coherently and queued evidence
  disappears after successful processing.
- **Intake controls:** Pause a staged intake, verify it remains visible without
  processing, resume it, then discard a separate staged intake and verify the
  discarded count and absence from recall.
- **MCP parity:** Compare MCP staging and recall acknowledgement shapes with the
  HTTP path when the harness provides an MCP transport.
- **CLI acknowledgement:** Confirm the Go command reports the stored chunk count
  and does not poll a removed ingest-job endpoint.

## Tools

- Reused: `curl` and `bash` for HTTP; direct `bash` invocation for the Go CLI.
- New: none.
- Improved: none.

## Harness Limitations

The test-mode server uses stub reasoning and embedding models plus an in-memory
SurrealDB. This exercises real HTTP routing, queue persistence, worker lifecycle,
and recall shaping, but it cannot expose provider latency, realistic model write
quality, production load races, or cross-process lease behavior. MCP transport
availability depends on the local app wiring. The Jev fast routing path is an
approved out-of-scope dependency and its known failures cannot be treated as
intake regressions. These limits weaken model-quality and deployment-concurrency
coverage, not the primary synchronous staging and queue-control behavior.

## Results

### Smoke Suite

- **HTTP intake and recall — pass.** Started a test-mode Uvicorn server and
  called `GET /health`, `POST /ingest`, `GET /ingest/pipeline`, and `POST
  /recall` with `curl`. Health returned `200`. Synchronous staging returned
  `200 {"chunks_stored":1}` before worker processing. The immediate snapshot
  showed one ready chunk and one worker. The recall agent's search tool found one
  unprocessed chunk in the server log, but the synthetic model emitted no
  citation, so HTTP context was null. Coherence: **looks coherent for staging;
  looks off for recall because the synthetic model does not cite tool results**.
- **Pipeline operations — pass.** Used the intake identifier surfaced by the
  retry snapshot. Pause changed one row to `paused`; resume returned it to
  `ready`; discard returned `chunks_discarded: 1`. Unknown identifiers returned
  `404`. The final snapshot had zero queued rows and zero recent errors.
  Coherence: **looks coherent**.
- **MCP intake and recall — pass.** Connected with `fastmcp.Client` to
  `/mcp`, listed `ingest`, `recall`, and `graph_lookup`, and called `ingest`.
  It returned the expected queued-count acknowledgement. MCP recall returned
  the synthetic answer without citations for the same model limitation.
  Coherence: **looks coherent for ingest; looks off for recall because no
  citation was emitted by the synthetic model**.
- **Go CLI ingest — pass.** Built `client/cmd/brain` and ran `brain ingest`
  against the test-mode server. The command printed `Queued 1 chunks for
  background ingestion.` and exited zero. Coherence: **looks coherent**.
- **Converse staging — pass.** `POST /converse` returned a response containing
  the shared staging acknowledgement. `POST /converse/stream` emitted staging,
  queue, search, and done events. Jev routing assertions were not exercised.
  Coherence: **looks coherent for the staging message and SSE sequence**.

### Topic-Specific Tests

- **Synchronous staging visibility — pass.** Submitted source and hints with an
  idempotency key. The response returned one stored chunk while the snapshot
  still showed it ready. A same-content retry returned `chunks_stored: 0`; a
  different body with the same key returned `409`. After discard, the key was
  accepted again. Empty and 100001-character requests returned `400` before
  queue writes. Coherence: **looks coherent**.
- **Hybrid recall of unprocessed evidence — pass.** In a direct in-memory
  Storage and `recall_tools.search_memory` check, one organized note and one
  queued chunk returned in separate `nodes` and `unprocessed` collections.
  The chunk had `unprocessed: true`, no graph connections, and no lease or
  worker metadata. HTTP recall remained harness-limited as described above.
  Coherence: **looks coherent in the direct recall result**.
- **Background drain and introspection — pass.** A direct in-memory pipeline
  with a deterministic runner paused and resumed an intake, then drained it
  through a real worker. Runner calls completed, and the final snapshot had
  zero ready, leased, retry-wait, and paused rows. A second intake discarded
  through the pipeline disappeared from search. The live HTTP worker could not
  drain with `TestModel`: its synthetic tool arguments caused the expected
  retry error (`Invalid identifier: 'additionalProperty'`). Coherence:
  **looks coherent in the deterministic worker result; live test-mode drain
  looks off because the model harness emits invalid ingest calls**.
- **Intake controls — pass.** HTTP pause, resume, discard, unknown-target 404,
  and final empty snapshot all behaved as specified. The direct pipeline check
  confirmed pause before worker start prevents claims. Coherence: **looks
  coherent**.
- **MCP parity — pass.** MCP staging used source `mcp`, preserved hints through
  the configured callback, and reported the queued count. MCP recall citation
  separation could not be observed with `TestModel`; direct recall-tool checks
  covered the same shape. Coherence: **looks coherent for the acknowledgement**.
- **CLI acknowledgement — pass.** The rebuilt Go CLI performed one synchronous
  request and printed the chunk count. It did not use a removed job-polling
  route. Coherence: **looks coherent**.

## Plan Updates

None. The persistent plan already lists HTTP intake, pipeline controls, MCP,
CLI, and converse staging journeys.

## Open Issues

- The `TestModel` used by `BRAIN_TEST_MODE=true` emits placeholder tool
  arguments. The production ingest adapter therefore records retry errors and
  the live test-mode worker does not reach a clean delete. Deterministic direct
  pipeline checks pass. This is a harness limitation, not evidence of a queue
  contract failure.
- The test-mode recall agent executes the search tool but returns no cited IDs,
  so HTTP and MCP responses cannot show unprocessed citations. Direct Storage
  and recall-tool checks pass. A live model or a citation-capable test adapter
  is required for that user-facing assertion.
- The approved Jev scope remains unchanged. The known 60 Jev-related failures,
  including the fast converse intake case and routing HTTP expectations, belong
  to `jev-converse-routing`, not this topic.
