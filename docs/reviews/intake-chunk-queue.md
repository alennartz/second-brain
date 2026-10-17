# Review: Intake chunk queue

**Plan:** `docs/plans/intake-chunk-queue.md`
**Scope:** Fix re-review. Diff range `012a91a..15aba05` (commits `56673fb`, `91f95d8`).
**Baseline review HEAD:** `012a91a`
**Date:** 2026-10-16

## Summary

The fix commits resolve the prior critical findings. Pause now holds an in-flight batch. Worker errors no longer end a worker. Retry delay no longer overflows. Leases renew during a run. Recall evidence omits queue metadata. Orphan idempotency keys are reclaimed.

The fixes add new risks. The benchmark runner no longer waits for background processing, so its recall and graph phases run against an unprocessed queue. A transient renewal error cancels a healthy run. Two prior low findings and one new leak path stay open.

A storage probe against `mem://` confirmed the pause, resume, renewal, projection, duplicate, conflict, and orphan-reclaim behavior. This re-review did not run the test suite.

## Prior Findings

| # | Finding | Status | Evidence |
|---|---------|--------|----------|
| 1 | Recovered tool errors make every replay unclean | resolved | `IngestDeps.record_write_attempt` keeps errors per operation. A later clean `store_knowledge` or `update_node:<id>` clears them. See residual finding N4. |
| 2 | Pause does not hold an in-flight batch | resolved | A `paused` flag marks every row. Claim selection and the claim transaction skip flagged intakes. Release moves flagged leased rows to `paused`. Probe: pause, release, then claim returns `None`. Resume claims rows 0 and 1. |
| 3 | A processing exception can end the worker | resolved | `_worker_loop` catches `_process_batch` errors and re-raises only `CancelledError`. `retry_delay` saturates at the cap with `log2` and `ldexp`. See finding N6 for a related gap. |
| 4 | Slow runs lose their lease and run twice | resolved | `_renew_lease_loop` renews every `lease_seconds / 3`. A short renewal cancels the runner and skips acknowledgement. Delete logs a short count. See finding N2. |
| 5 | Idempotency keys become permanent tombstones | resolved | Staging deletes a key with no remaining rows and stages again. Probe: an orphan key stores 1 chunk. Cleanup errors now raise. See finding N5. |
| 6 | Queue metadata leaks into recall | resolved | `_project_intake_evidence` keeps `id`, `intake_id`, `chunk_index`, `total_chunks`, `content`, `source`, `created_at`, and `table`. Search candidates and `get_intake_chunks` use it. See finding N3. |
| 7 | Duplicate staging reports a successful zero | dismissed | The approved contract keeps `chunks_stored=0` for duplicates. A reused key with different content now returns HTTP 409 through `IdempotencyConflict`. |
| 8 | Shutdown can wait forever on a provider call | resolved | `stop()` waits `intake_shutdown_grace_seconds`, cancels, then waits once more. See finding N7. |
| 9 | Experiment scenario targets the removed job API | partially resolved | The runner accepts `chunks_stored` and sends idempotency keys. It does not wait for the queue to drain. See finding N1. |
| 10 | Controls hide no-op targets, and `since` uses creation time | resolved | Pause, resume, and discard return 404 for an unknown intake. `since` uses the earliest `updated_at` of stuck rows. |
| 11 | Codemap and comments describe removed jobs | resolved | The codemap, converse prompt, MCP recall docstring, and app comment describe staging and background processing. |
| 12 | Retry attempts reset the dream scheduler | open | The first-pass report raised this finding. The consolidated review omitted it. `_process_batch` still calls `activity_callback` for every attempt. An intake that retries hourly cancels dream cycles and resets the convergence cutoff each hour. |
| 13 | Over-limit converse ingest fails the whole turn | open | `stage_converse_ingest` lets `ValueError` from `enqueue` propagate. One over-limit message fails the converse request or SSE stream instead of returning a tool message. |

## New Findings

### N1. Benchmark phases no longer wait for organized memory

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `experiments/run_experiment.py:803-824`, `experiments/run_experiment.py:827-876`, `test_scenario.py:647-669`
- **Status:** open
- **Fix:** After staging, poll `GET /ingest/pipeline` until `ready`, `leased`, `retry_wait`, and `paused` are zero, or until a deadline. Record the drain time as the ingest latency.

`_ingest_one` returns after the synchronous staging response. `ingest_phase` then moves to `recall` at once. Recall questions run against mostly unprocessed chunks. Graph probes look for entities that do not exist yet. The recorded ingest latency measures staging, not organization. Benchmark results stop being comparable with earlier runs. `test_scenario.py` has the same gap.

### N2. A transient renewal error cancels a healthy run

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/second_brain/agents/ingestion_pipeline.py:355-393`
- **Status:** open
- **Fix:** Retry a failed renewal until the current lease expiry. Declare the lease lost only when a renewal returns fewer rows or the expiry passes.

`_renew_lease_loop` treats any renewal exception as a lost lease. It cancels the runner and skips release. The lease still belongs to this worker, so the rows wait for expiry and replay. The cancelled run can leave partial graph writes, and the replay duplicates them. `renew_intake_batch` is a plain `UPDATE` outside `_transaction_lock`, so an embedded "can be retried" conflict reaches this path.

### N3. Graph lookup returns raw queue rows for cited chunk IDs

- **Category:** code correctness
- **Severity:** nit
- **Location:** `src/second_brain/app.py:528-560`, `src/second_brain/db.py` `get_node`
- **Status:** open
- **Fix:** Restrict `get_graph_data` and the recall agent `get_node` tool to `note` and `entity`, or project `intake_chunk` rows with `_project_intake_evidence`.

Recall responses now publish `intake_chunk` IDs. `GET /graph/{id}` and MCP `graph_lookup` accept any table. `get_node` returns `SELECT * OMIT embedding`. A cited chunk ID therefore exposes `lease_token`, `worker_id`, `idempotency_key`, `last_error`, and retry state. The recall agent `get_node` tool has the same path into the prompt.

### N4. Last store result can mask an unresolved write failure

- **Category:** code correctness
- **Severity:** nit
- **Location:** `src/second_brain/agents/ingest.py:15-28`, `src/second_brain/agents/ingest.py:143-196`
- **Status:** open
- **Fix:** Clear a `store_knowledge` failure only when a later call covers the failed items, or keep note and edge storage failures until the batch ends.

All `store_knowledge` calls share one key. A note-creation failure followed by an unrelated successful call clears the failure. The batch is then deleted, and the failed notes never reach the graph. The prompt asks for one call, so the usual second call is a retry. The risk stays low but causes silent loss when it occurs.

### N5. Orphan-key reclaim can delete a newer key

- **Category:** code correctness
- **Severity:** nit
- **Location:** `src/second_brain/db.py` `create_intake_chunks`, orphan cleanup branch
- **Status:** open
- **Fix:** Delete the key only when it still points to the orphan intake: `DELETE ... WHERE id = type::thing('intake_key', $key) AND intake_id = $existing_intake_id`.

Two same-key requests can both read the orphan key. The first deletes it and commits a new key with rows. The second then deletes the new key by ID and stages a second intake. One idempotency key then maps to two intakes. The window is narrow and needs concurrent duplicates after a crash.

### N6. Batch-assembly errors replay without a recorded failure

- **Category:** code correctness
- **Severity:** nit
- **Location:** `src/second_brain/agents/ingestion_pipeline.py:395-410`, `src/second_brain/agents/ingestion_pipeline.py:320-334`
- **Status:** open
- **Fix:** Release the lease with the exception message when `_process_batch` fails before the runner result.

An error before the runner result reaches the worker-loop guard. It skips release. The rows stay leased until expiry and then replay. `attempt_count` and `last_error` do not change, so the snapshot shows no stuck intake or recent error. A deterministic error repeats every lease period without visibility.

### N7. The default shutdown grace interrupts most active runs

- **Category:** code correctness
- **Severity:** nit
- **Location:** `src/second_brain/config.py:46`, `src/second_brain/agents/ingestion_pipeline.py:241-271`
- **Status:** open
- **Fix:** Set `intake_shutdown_grace_seconds` near the deployment stop timeout, or document the replay cost.

An ingest-agent run usually exceeds the 10-second default. A restart during processing cancels the run mid-write. The batch replays after lease expiry, and partial writes can duplicate. The design accepts at-least-once processing, but a short default makes the duplicates routine on each deployment.

## No Issues

The fix diff keeps the claim transaction atomic, retains stale-token safety in release and delete, and maps `IdempotencyConflict` to 409 before the generic 400. Resume restores rows that release moved to `paused`. Discard now stops an in-flight run within one renewal interval, because renewal returns zero rows.
