# Manual Testing — android-workflows

## Smoke Suite

- **Bun server health and fresh startup:** verify the live HTTP service is
  reachable and the pipeline reports a healthy worker state.
- **HTTP intake, queue, recall, and graph:** exercise ingest, pipeline health,
  search, graph refresh, and graph lookup through the mobile HTTP boundary.
- **Restart and shutdown:** verify health and intake-key persistence across the
  running service lifecycle when the available local service permits it.

The Go CLI and connected Android UI journeys remain outside this run because
this phase focuses on the changed mobile HTTP routes and no phone or emulator
is connected.

## Topic-Specific Tests

- **Search route:** send valid, boundary, empty-result, invalid, and transport
  requests to `POST /search`; verify node and unprocessed chunk projections.
- **Graph refresh route:** send ordered, repeated, missing, bounded, invalid,
  and transport requests to `POST /graph/refresh`; verify found and missing
  results preserve request order.
- **Ingest idempotency replay:** stage a keyed intake, replay the same key and
  content after processing, replay with changed content for `409`, and verify
  the key remains permanent after cleanup and reopening.
- **Pipeline health:** inspect `GET /ingest/pipeline` while staging and after
  replay to verify worker and queue counters remain coherent.

## Tools

- **Reused:** `curl` through `bash` against the local Bun/mobile HTTP server;
  existing route and storage contract tests for deterministic edge cases.
- **New:** none.
- **Improved:** none.

## Harness Limitations

The Android UI itself cannot run here because no connected phone or emulator is
available. This run drives the real server boundary from the host, as the
existing mobile smoke journeys do. It does not cover Flutter rendering,
platform networking, app lifecycle timing, or client persistence. Provider and
worker timing can also leave intake unprocessed, so the idempotency replay is
run against the live HTTP boundary and cross-checked with deterministic storage
contracts where needed. These limits weaken UI and device-network coverage but
not the changed HTTP route contracts.

## Results

_To be filled after execution._

## Plan Updates

Empty until execution identifies a primary journey change.

## Open Issues

_To be filled after execution._
