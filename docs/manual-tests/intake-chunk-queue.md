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

To be filled after execution. Every smoke and topic-specific item will include
an observed result, structural verdict (`pass`, `fixed-inline`, or `open`), and
coherence verdict for user-facing output.

## Plan Updates

None planned.

## Open Issues

To be filled after execution. Known Jev failures will be listed as scope or
harness limitations, not intake defects.
