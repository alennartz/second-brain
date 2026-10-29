# Manual Testing — android-workflows

## Smoke Suite

- **Bun server health and fresh startup:** verify the isolated current image
  starts on a fresh database and reports health and pipeline state.
- **HTTP intake, queue, recall, and graph:** exercise ingest, pipeline pause,
  resume, discard, recall, search, graph refresh, and graph lookup through the
  mobile HTTP boundary.
- **Go CLI:** build the client and run ingest, recall, and graph commands
  against the same HTTP boundary.
- **Restart and shutdown:** restart the isolated server with its same database,
  verify health and idempotency persistence, then stop it.
- **Android Flutter client:** record the device journey as deferred because no
  phone or emulator is connected.

## Topic-Specific Tests

- **Search route:** send valid, boundary, empty-result, invalid, and transport
  requests to `POST /search`; verify node and unprocessed chunk projections.
- **Graph refresh route:** send ordered, repeated, missing, bounded, invalid,
  and transport requests to `POST /graph/refresh`; verify found and missing
  results preserve request order.
- **Ingest idempotency replay:** stage a keyed intake, replay the same key and
  content, replay with changed content for `409`, discard its chunks, restart
  the server, and replay again. Cross-check permanent-key behavior after
  processing with the deterministic contract test.
- **Pipeline health:** inspect `GET /ingest/pipeline` while staging, pausing,
  resuming, discarding, retrying, and replaying to verify worker and queue
  counters remain coherent.

## Tools

- **Reused:** `curl` through `bash` against an isolated Bun HTTP server,
  Docker, `make build-client`, and the existing deterministic test suite.
- **New:** none.
- **Improved:** none.

## Harness Limitations

The Android UI itself cannot run here because no connected phone or emulator is
available. This run drives the real server boundary from the host, as the
existing mobile smoke journeys do. It does not cover Flutter rendering,
platform networking, app lifecycle timing, or client persistence. The live
configured model repeatedly returned `Field does not belong to node kind` while
processing manual intakes. This weakens completed-graph and graceful worker
shutdown coverage. The changed HTTP route contracts and intake-key behavior are
also covered by deterministic tests, including permanent keys after cleanup.

## Results

- **Bun server health and fresh startup — pass.** Built the current image,
  started it with a fresh isolated volume on `127.0.0.1:8101`, and received
  `GET /health` `200 {"status":"ok"}`. Initial pipeline health reported one
  worker with zero queued, leased, or retrying intakes. **Coherence:** looks
  coherent.
- **HTTP intake, queue, recall, and graph — pass.** `POST /ingest` returned
  `200` with `chunks_stored: 1`. Pause, resume, and discard each returned `200`
  with the expected intake projection. `POST /recall` returned a validated
  answer with node evidence. `GET /graph/:record_id` returned a found node and
  `404` for a missing node. **Coherence:** looks coherent.
- **Go CLI — pass.** `make build-client` succeeded. `brain ingest` reported
  one queued chunk, `brain recall` returned the marker answer, and `brain graph`
  rendered the selected entity and its empty connection list. **Coherence:**
  looks coherent.
- **Restart and shutdown — pass.** Restarted the isolated server with the same
  volume. Health returned `200`; replaying the old key returned the original
  `chunks_stored: 1`, and changed content returned `409`. The container stopped
  after the test. **Coherence:** looks coherent for health and persistence;
  provider retries limit proof of fully drained worker shutdown.
- **Android Flutter client — open.** No connected phone or emulator exists in
  this environment. The host HTTP boundary is covered, but Flutter rendering,
  local persistence, and device-network behavior remain untested. **Coherence:**
  not assessed without the UI.
- **Search route — pass.** Live `POST /search` returned `200` with separate
  `nodes` and `unprocessed` arrays for empty and populated results. Omitted,
  `1`, and `100` limits returned `200`; blank query and limit `0` returned
  `400`. The deterministic suite also passed transport failures and projection
  checks. **Coherence:** looks coherent.
- **Graph refresh route — pass.** Live refresh returned found, missing, and
  repeated results in request order. An empty list returned `200`; empty-string
  IDs, invalid IDs, and a 201-item batch returned `400` where required. Deterministic
  tests passed transport failures, found projections, missing records, and the
  200-ID bound. **Coherence:** looks coherent.
- **Ingest idempotency replay — pass.** The first keyed ingest and immediate
  same-content replay returned `200` with `chunks_stored: 1`; changed content
  returned `409`. After discard cleanup and after a server restart, the same key
  still returned `1`, and changed content still returned `409`. The deterministic
  contract test passed permanent-key behavior after processing and reopening.
  **Coherence:** looks coherent.
- **Pipeline health — open.** Counters, pause/resume state, leases, retries,
  stuck intake details, and recent errors reflected live transitions without
  fabricated records. The configured model repeatedly failed with
  `Field does not belong to node kind`, leaving retrying and leased work. The
  retry path also created duplicate graph notes for one marker before discard.
  This is a provider/workflow-coherence issue outside the route and key changes;
  no inline fix was attempted. **Coherence:** looks off because the pipeline
  remains stuck under the configured provider.
- **Dream job smoke — open.** `POST /dream` returned `202` and a job location,
  but polling stayed `running` for 60 seconds under the same provider. The
  route lifecycle is reachable; terminal completion was not established.
  **Coherence:** looks off because the provider did not settle the job.

Deterministic `bun test tests/android-workflows.test.ts` ran in the pinned Bun
container: 16 tests passed, including production search and graph operations,
HTTP validation and transport failures, replay conflict handling, and permanent
intake keys after cleanup and reopening.

## Plan Updates

Empty. No primary journey changed.

## Open Issues

- The configured local model returns `Field does not belong to node kind` during
  intake retries and leaves pipeline work in retry or leased states. Retries
  can create duplicate graph notes for one marker before cleanup. This is a
  pre-existing provider/workflow-coherence issue, not an HTTP route or
  idempotency-key failure. Dream jobs can remain `running` for the same reason.
- The Android UI journey remains unexecuted without a phone or emulator.
