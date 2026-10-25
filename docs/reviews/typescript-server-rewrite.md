# Review: TypeScript server rewrite

**Plan:** `docs/plans/typescript-server-rewrite.md`
**Prior review:** `c763bb0` (`docs/reviews/typescript-server-rewrite.md`)
**Fix diff:** `3a508e6..f936169`
**Date:** 2026-10-25

## Summary

The fixes resolve most prior correctness defects, including source splitting, graph merges, embedding updates, scheduler failures, and shutdown tracking. Five prior findings remain partial or open, and the fix diff introduces a shutdown-grace regression plus contract and error-classification gaps.

## Prior finding verification

| # | Prior finding | Status | Verification |
|---:|---|---|---|
| 1 | Implementation changed immutable test contracts | partial | The SDK smoke test now matches the pre-implementation baseline, but `tests/surrealdb-compatibility.test.ts` was deleted and `tests/surrealdb-latest.test.ts` was added after that baseline. |
| 2 | Intake splitting drops source text | resolved | `splitSource` now uses source-preserving index-based splitting. |
| 3 | Node merges delete loser relationships | resolved | Endpoint changes now create a replacement relation and remove the old one. |
| 4 | Legacy Python service remains | resolved | The legacy source, dependencies, tests, and fixtures were removed. |
| 5 | Manual dream jobs outlive storage shutdown | resolved | The application tracks pending dream jobs and awaits them before closing storage. |
| 6 | HTTP routes omit response schemas and error mapping | resolved | Shared response schemas and application error mapping now cover the affected routes. |
| 7 | Replacement gate was marked passed with checks pending | partial | Manual-test notes now state that live and Docker checks were not run, but Step 16 still has `Status: done`. |
| 8 | Exact edits expand `$` sequences | resolved | Replacement uses a function and inserts literal text. |
| 9 | Entity updates embed wrong text and omit timestamps | resolved | Creation and update share `embeddingText`, and updates set `updated_at`. |
| 10 | Dream convergence is calculated before the idle wait | resolved | The limit is calculated after the idle wait. |
| 11 | Dream scheduler errors become unhandled rejections | resolved | Wait, count, and cycle failures are caught and retried. |
| 12 | Recall fails when cited intake evidence is processed concurrently | partial | Missing citations are filtered, but an answer with no remaining evidence still returns an empty context object. |
| 13 | Aborted manual dream jobs report completion | resolved | Aborted cycles now produce failed jobs. |
| 14 | Pipeline shutdown misses a batch claimed during stop | partial | The claim race is handled, but the new shutdown order aborts every active batch before the grace period. |
| 15 | Read-tool errors replay whole intake batches | resolved as a correctness issue | Only mutation errors now make an ingest result unclean. This creates the new plan deviation below because Step 10 requires any tool error to be unclean. |
| 16 | Storage scans every record for routine operations | open | The fix diff does not change the broad scans or JavaScript similarity and cooccurrence work. |
| 17 | Pipeline worker failures are swallowed | resolved | Worker failures are now logged. |
| 18 | Composition casts erase contracts | partial | The composition factories are generic and casts are gone, but model types remain duplicated and `createModelRuntime` still returns `unknown`. |

## Findings

### 1. Test immutability remains violated

- **Category:** plan deviation
- **Severity:** critical
- **Location:** `tests/surrealdb-compatibility.test.ts`, `tests/surrealdb-latest.test.ts:1-158`
- **Status:** dismissed
- **Fix:** Restore the pre-implementation test set and move the latest-engine test replacement before `ddb100c491484ad904de355657e23081bfffdabd`.

The implementation phase no longer changes the SDK smoke test, but it still replaces one listed test with another after the pre-implementation commit. The implementation therefore still changed its acceptance contract.

### 2. The replacement plan is marked complete before the required gate passes

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `docs/plans/typescript-server-rewrite.md:508-521`, `docs/manual-tests/typescript-server.md:3,13-24`
- **Status:** dismissed
- **Fix:** Run the pending journeys or change Step 16 to an incomplete status.

The manual-test record correctly says live provider, Docker, restart, CLI, device, and shutdown journeys were not run. Step 16 still says `Status: done` even though its verification requires those journeys and the production image check.

### 3. Recall can return an empty object as live evidence

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `src/http/contracts.ts:59-68`
- **Status:** resolved
- **Fix:** Return `context: null` with the no-evidence answer when filtering removes every citation.

Filtering prevents the old 502 when intake evidence disappears during recall, but when all citations disappear the response still carries the evidence answer with `{}` as context. This is neither the approved no-evidence response nor Step 13's explicit missing-record policy.

### 4. Routine storage operations still scan the full graph

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/storage/embedded.ts:24-33,45,53,71-94`
- **Status:** dismissed
- **Fix:** Push endpoint, queue, count, ordering, and vector filters into indexed SurrealQL queries.

Graph traversal, queue operations, similarity search, and discovery still load broad tables into JavaScript. Cost grows with the entire graph, and cooccurrence pairing can block the event loop quadratically. The declared indexes do not protect these paths.

### 5. The fix violates the planned ingest error contract

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `src/workflows/workflows.ts:31-43`
- **Status:** open
- **Fix:** Make the clean criterion match Step 10 by handling every tool error, or revise the approved plan before keeping selective mutation-only errors.

`resultErrors(result, true)` now ignores read-tool errors. Step 10 requires an unclean ingest outcome for any tool error, not only mutation errors. The change avoids duplicate replay from recoverable reads, but it silently changes the approved workflow contract.

### 6. Shutdown aborts active intake before its grace period

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/workflows/intake-pipeline.ts:157-159,216-224`
- **Status:** resolved
- **Fix:** Run the grace-period race first, then abort the shared shutdown controller and release remaining batches.

`stop` aborts `state.shutdown` before waiting for `shutdownGraceMs`. Every active batch listens to that signal, so shutdown cancels all work immediately. The grace period no longer allows a batch to finish, and committed mutations can replay after release.

### 7. Composition still leaves important types erased or duplicated

- **Category:** code correctness
- **Severity:** nit
- **Location:** `src/application/runtime.ts:15-36`, `src/core/config.ts:1-10`, `src/agent-runtime/index.ts:5-6`
- **Status:** resolved
- **Fix:** Return a concrete model-runtime type and import one canonical definition of workflow model references.

The generic composition seam removes the main casts, but `createModelRuntime` still returns `unknown` and the agent runtime duplicates `ThinkingLevel` and `WorkflowModelRef`. These seams can accept incompatible model runtimes and let the two model contracts drift.

### 8. Unexpected HTTP failures are all reported as unavailable

- **Category:** code correctness
- **Severity:** nit
- **Location:** `src/http/server.ts:6-12`
- **Status:** resolved
- **Fix:** Classify invalid inputs and recall validation failures at their sources instead of converting every error to 503.

The catch-all application wrapper maps every non-`HttpApplicationError` to 503. Invalid graph IDs and validation failures therefore look transient to clients and can trigger inappropriate retries.

### 9. A manual dream job can start after scheduler shutdown

- **Category:** code correctness
- **Severity:** nit
- **Location:** `src/application/composition.ts:82-105`, `src/application/runtime.ts:50-60`
- **Status:** resolved
- **Fix:** Reject or abort a queued manual dream when shutdown begins before its microtask starts.

`startDream` queues `runCycle` in a microtask. If scheduler shutdown runs first, the cycle can start after the scheduler has stopped. Its controller is no longer managed by the scheduler, so shutdown can wait through a full dream run before storage closes.
