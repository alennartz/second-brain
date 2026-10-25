# Review: TypeScript server rewrite

**Plan:** `docs/plans/typescript-server-rewrite.md`
**Diff range:** `babef48d9b6b4eed0ea649bc0899133a54fd600a..3a508e6`
**Date:** 2026-10-25

## Summary

The TypeScript server implements most planned modules, but the review found two critical correctness defects and one critical test-process deviation. Intake staging can drop source text, and node merging can delete relationships. Several lifecycle, retry, citation, schema, and deployment-gate gaps remain before this replacement is safe to ship.

## Findings

### 1. Implementation changed immutable test contracts

- **Category:** plan deviation
- **Severity:** critical
- **Location:** `tests/agent-runtime/sdk-smoke.test.ts:222-247`, `tests/surrealdb-compatibility.test.ts`, `tests/surrealdb-latest.test.ts:1-158`
- **Status:** open
- **Fix:** Restore the test files to the pre-implementation baseline and move contract changes into the test-writing commit.

The plan requires listed tests to remain immutable between `ddb100c491484ad904de355657e23081bfffdabd` and implementation. The implementation modifies the SDK smoke test and replaces the compatibility test with a latest-engine test. This makes the implementation able to change its own acceptance contract.

### 2. Intake splitting drops source text

- **Category:** code correctness
- **Severity:** critical
- **Location:** `src/workflows/intake-pipeline.ts:58-74`
- **Status:** open
- **Fix:** Port the Python index-based splitter and preserve every character and its whitespace.

The sentence regex skips text when punctuation is not followed by whitespace. It drops prefixes from decimals, URLs, versions, filenames, abbreviations, and leading ellipses. Joining units with a space also destroys paragraph newlines, so staged evidence no longer matches the submitted source.

### 3. Node merges delete the loser's relationships

- **Category:** code correctness
- **Severity:** critical
- **Location:** `src/storage/embedded.ts:70`, `src/knowledge/index.ts:145-148`
- **Status:** open
- **Fix:** Re-relate an edge with changed endpoints, then delete the old relation record.

SurrealDB ignores the attempted `in` and `out` update on relation records. `mergeNodes` then deletes the loser and cascades its edges, instead of moving them to the survivor. Graph structure disappears during deduplication.

### 4. The legacy Python service remains after the replacement gate

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `src/second_brain/**`, `pyproject.toml:1-38`, `uv.lock`, `test_scenario.py`, Python files under `tests/`
- **Status:** open
- **Fix:** Delete the legacy server, Python dependencies, compatibility fixtures, and migration-only inputs as required by Step 16.

Step 16 marks the cutover complete but requires deleting the old server and dependencies after the gate. The repository still carries them. This leaves the old runtime and its maintenance surface in the production source tree, contrary to the approved replacement scope.

### 5. Manual dream jobs can outlive storage shutdown

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `src/application/composition.ts:83-90`, `src/application/runtime.ts:40-47`
- **Status:** open
- **Fix:** Track every manual dream promise and await its settlement before closing storage.

`startDream` queues `runCycle` without recording it. Runtime shutdown stops workers and closes storage without awaiting those jobs. A pending cycle can access closed storage after shutdown, violating the planned lifecycle guarantee.

### 6. HTTP routes omit required response schemas and error mapping

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `src/http/server.ts:5-10,17-41`
- **Status:** open
- **Fix:** Attach the shared response schemas and map application failures for pipeline controls, dream jobs, and graph lookup.

The plan requires shared response schemas on every route and existing `{ detail }` status mapping. Pause, resume, discard, dream-job lookup, and graph lookup have no response schema. Their direct failures bypass `HttpApplicationError` handling and can become framework 500 responses.

### 7. The replacement gate is documented as passed while live checks remain pending

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `docs/manual-tests/typescript-server.md:3,13-24`
- **Status:** open
- **Fix:** Run and record the Docker and live-provider journeys before marking Step 16 done.

The plan requires manual HTTP journeys and a production-image startup check. The manual-test record says the automated gate passed but leaves live provider and Docker checks pending. The cutover status therefore overstates verification.

### 8. Exact node edits expand `$` replacement sequences

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/knowledge/index.ts:92`
- **Status:** open
- **Fix:** Pass a replacement function to `String.replace` so `newText` is inserted literally.

String replacement interprets `$$`, `$&`, ``$` ``, and `$'`. Editing a field to contain money or other literal dollar sequences stores different text than requested, violating the exact-edit contract.

### 9. Entity updates embed the wrong text and omit update timestamps

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/storage/embedded.ts:35-67`
- **Status:** open
- **Fix:** Share one embedding-text helper between creation and updates, and set `updated_at` on every meaningful update.

Creation embeds `description || name`, while updates choose `content`, `description`, or `name` from only the changed fields. Renaming an entity with a description therefore changes its vector to name-only. The update path also fails to refresh `updated_at`, leaving stale metadata and search vectors.

### 10. Dream convergence is calculated before the idle wait

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/workflows/dream-scheduler.ts:72-74`
- **Status:** open
- **Fix:** Compute the convergence limit after the idle sleep, immediately before the first cycle.

The scheduler counts nodes before waiting for the idle period. An empty database computes a zero limit and can remain converged forever, so dreaming does not start after the first ingest unless another activity signal arrives. Non-empty databases also use a stale limit.

### 11. Dream scheduler errors become unhandled rejections

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/workflows/dream-scheduler.ts:73,91`
- **Status:** open
- **Fix:** Catch `countNodes` and cycle errors inside the loop and retry or report them on the next idle period.

A rejected `countNodes` or cycle promise rejects the stored loop promise. Nothing observes it until `stop`, so dreaming stops silently and the rejection can terminate the Bun process.

### 12. Recall fails when cited intake evidence is processed concurrently

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/http/contracts.ts:58-63`
- **Status:** open
- **Fix:** Drop citations that no longer resolve and return the answer with the remaining live evidence.

The ingest worker can delete an intake chunk while recall is still running. The service throws when an `unprocessed` citation disappears, turning a normal capture-then-ask race into a 502 instead of filtering stale evidence.

### 13. Aborted manual dream jobs report completion

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/application/composition.ts:88`
- **Status:** open
- **Fix:** Map an aborted cycle to the failed job state with an explicit cancellation error.

Activity can abort an active dream cycle. The result has `aborted: true` and no errors, but the job handler maps that result to `complete`, reporting successful work that did not finish.

### 14. Pipeline shutdown can miss a batch claimed during stop

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/workflows/intake-pipeline.ts:100-103,117-125`
- **Status:** open
- **Fix:** Use one instance-level shutdown controller and link every newly started batch to it.

A worker can be inside `claimIntakeBatch` while `stop` checks `state.active`. The batch is then started without an abort signal that shutdown controls, so shutdown can wait for a full model run and exceed its grace period.

### 15. Read-tool errors replay whole intake batches

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/workflows/workflows.ts:31-41`
- **Status:** open
- **Fix:** Count only unrecovered mutation failures when deciding whether an ingest batch is clean.

Every tool error marks the run unclean, including transient or recoverable read-tool errors. The entire batch is released and replayed, while `storeNode` is not idempotent. Repeated read errors can therefore create duplicate nodes on each retry.

### 16. Storage queries scan every record for routine operations

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/storage/embedded.ts:24-33,45,53,71-94`
- **Status:** open
- **Fix:** Push endpoint, queue, count, ordering, and vector filters into indexed SurrealQL queries.

Graph traversal, queue operations, similarity search, and discovery load broad tables into JavaScript and sort or pair them there. Query cost grows with the full graph, and cooccurrence pairing can block the event loop quadratically. The declared indexes do not provide their intended protection.

### 17. Pipeline worker failures are swallowed without an operational signal

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/workflows/intake-pipeline.ts:104`
- **Status:** open
- **Fix:** Log or expose the caught worker error before the retry sleep.

The worker catches all errors and sleeps without recording them. Queue outages and failures while releasing or deleting batches become invisible, which prevents operators from diagnosing stalled intake.

### 18. Composition casts erase the storage and knowledge contracts

- **Category:** code correctness
- **Severity:** nit
- **Location:** `src/application/runtime.ts:15-30`, `src/application/composition.ts:36-67`
- **Status:** open
- **Fix:** Type `CompositionFactories` with `Storage` and `KnowledgeGraph` instead of `unknown` and casts.

The composition seam accepts `unknown` and casts each factory result back to a domain type. This removes compile-time checking at the startup seam and permits incompatible adapters to enter the application. The runtime and agent modules also duplicate the workflow model types.
