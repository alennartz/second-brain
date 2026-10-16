# Review: Intake chunk queue

**Plan:** `docs/plans/intake-chunk-queue.md`
**Diff range:** `e7cf38a1eb13bdd1aec4f0a97e494ffb771b6575..HEAD`
**Date:** 2026-10-15

## Summary

The implementation follows the approved queue, recall, API, MCP, and client architecture. Ruff, Basedpyright, Go tests, vet, and lint pass. Python has only the approved Jev failures. The review found several correctness risks in retry handling, lease lifecycle, idempotency cleanup, and public evidence shaping that need resolution before shipment.

## Findings

### 1. Recovered tool errors make every replay unclean

- **Category:** code correctness
- **Severity:** critical
- **Location:** `src/second_brain/agents/ingest.py:159-182`, `src/second_brain/agents/ingestion_pipeline.py:307-358`
- **Status:** resolved
- **Fix:** Track unresolved write failures per final write attempt, and do not retry a batch after the agent has recovered from an earlier tool error.

Broad tool exception handlers append malformed agent arguments and transient errors to `storage_errors`. The list is never cleared. A later successful `store_knowledge` call still returns an unclean outcome, so the pipeline retries forever. Earlier entity or note writes are repeated on every replay, creating duplicates and consuming an LLM run each time.

### 2. Pausing an intake does not pause an in-flight batch

- **Category:** code correctness
- **Severity:** critical
- **Location:** `src/second_brain/db.py:1141-1157`, `src/second_brain/db.py:56-106`
- **Status:** resolved
- **Fix:** Persist an intake-level pause marker or make release and claim exclude all rows belonging to a paused intake, including expired leases.

`set_intake_paused` leaves leased rows unchanged. If that batch fails after the pause, release moves it to `retry_wait`, and the claim selector processes it again. Expired leases from the paused intake are also eligible. Operator pause therefore fails to stop the selected intake.

### 3. A processing exception can permanently kill the worker

- **Category:** code correctness
- **Severity:** critical
- **Location:** `src/second_brain/agents/ingestion_pipeline.py:146`, `src/second_brain/agents/ingestion_pipeline.py:265-358`
- **Status:** resolved
- **Fix:** Guard `_process_batch` inside `_worker_loop` and cap the exponential exponent before calculating the retry delay.

The worker loop protects claim failures but not every error from batch assembly, clock access, retry calculation, or cleanup. One unexpected exception exits the task and stops all processing. In addition, `retry_delay(1100, 5, 3600)` overflows when converting the huge exponent to a float. A permanently failing batch can reach that path after repeated capped retries.

### 4. Slow agent runs can lose their lease and run twice

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/second_brain/agents/ingestion_pipeline.py:307-358`, `src/second_brain/db.py:56-106`
- **Status:** resolved
- **Fix:** Renew the lease while the batch runner is active and report a lost lease when deletion affects zero rows.

When an agent run exceeds `lease_seconds`, another worker can claim the same rows. The first worker then writes graph records and its delete matches zero rows. The second worker writes the same batch again. This is likely when configurable concurrency is greater than one or the provider is slow.

### 5. Idempotency keys can become permanent tombstones

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/second_brain/db.py:1066-1101`
- **Status:** resolved
- **Fix:** Make orphan-key cleanup recoverable, or treat an idempotency key with no remaining chunks as available for a new request.

Batch row deletion commits before the separate `intake_key` deletion. A crash or failed cleanup leaves a key without chunks. Later requests with that key return zero forever, contrary to the in-flight-only contract.

### 6. Queue control leaks operational fields into recall

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/second_brain/db.py:1103-1139`, `src/second_brain/tools/recall_tools.py:66-95`
- **Status:** resolved
- **Fix:** Project unprocessed evidence to source fields only: ID, intake ID, chunk index, total chunks, content, source, and created time.

`get_intake_chunks` and hybrid search omit embeddings but expose lease tokens, worker IDs, idempotency keys, state, retry timing, attempts, and errors. These fields enter the recall agent prompt and public `/recall`, `/converse`, and SSE contexts. They are operational metadata, not memory evidence.

### 7. Duplicate staging reports a misleading successful zero

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/second_brain/db.py` staging path, `src/second_brain/app.py:430-466`
- **Status:** resolved
- **Fix:** Return the existing queued chunk count or an explicit duplicate result, and reject a reused key with different content.

A duplicate or same-key different-text request returns `200 {"chunks_stored": 0}`. Callers see a successful “queued zero chunks” response and cannot distinguish a collapsed duplicate from a no-op or rejected payload.

### 8. Shutdown can wait forever on a provider call

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/second_brain/agents/ingestion_pipeline.py:225-233`
- **Status:** resolved
- **Fix:** Bound worker shutdown, then cancel an in-flight runner task so lifespan shutdown cannot hang indefinitely.

`stop()` waits for every worker task without a timeout. A stuck model or network call prevents the application from closing and can delay deployment or recovery.

### 9. Experiment scenario still targets the removed job API

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `experiments/run_experiment.py:817-829`
- **Status:** resolved
- **Fix:** Update the scenario client to accept synchronous `chunks_stored` responses, or explicitly remove the obsolete scenario from supported tooling.

The implementation removed the `202` ingest job contract, but the experiment runner still rejects the new response and polls `/ingest/jobs/{id}`. This leaves a repository workflow broken outside the unit tests.

### 10. Operational controls do not report no-op targets clearly

- **Category:** code correctness
- **Severity:** nit
- **Location:** `src/second_brain/app.py` intake control routes and `src/second_brain/models.py` snapshot shapes
- **Status:** resolved
- **Fix:** Return an explicit not-found or unchanged result for unknown intake IDs, and make `stuck_intakes.since` represent the retry/pause transition rather than creation time.

Pause, resume, and discard can return success for an unknown intake. The snapshot's `since` value is derived from creation-related fields and can misstate when an intake became stuck. Operators can read a successful response that did not change any queue rows.

### 11. Codemap and comments still describe removed ingest jobs

- **Category:** plan deviation
- **Severity:** nit
- **Location:** `codemap.md:143`, `src/second_brain/app.py:67`
- **Status:** resolved
- **Fix:** Refresh the codemap and remove the stale “Ingest job store” heading after the implementation stabilizes.

The codebase map still documents `POST /ingest` as a direct agent flow and an asynchronous 202 job, omits `ingestion_pipeline.py` and the new tests, and retains the old job-oriented API description. The MCP recall docstring still documents only node citations, and the converse prompt still claims ingest is a full immediate AI pipeline. The app comment labels the remaining dream-job store as an ingest-job store. These stale descriptions mislead future work and violate the repository's living-map convention.

## No Issues

The plan-adherence pass confirmed the approved Jev failures are unchanged, the reviewed test contracts are otherwise implemented, and implementation changes did not preserve obsolete job behavior solely for tests.
