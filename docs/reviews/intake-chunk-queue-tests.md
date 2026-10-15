# Test Review: Intake chunk queue

**Plan:** `docs/plans/intake-chunk-queue.md`
**Brainstorm:** `docs/brainstorms/intake-chunk-queue.md`
**Date:** 2026-10-15

## Summary

The revised tests cover synchronous searchable staging, durable workers, cross-layer recall, and all ingest entry points. Tests exercise public interfaces with injected dependencies and deterministic lease/retry clocks. The user approved all six correction groups, including the missing search interface and final-total search limit.

## Findings

### 1. Durable worker behavior lacked coverage

- **Category:** missing coverage
- **Severity:** critical
- **Location:** `tests/test_ingestion_pipeline.py:482-978`, `tests/test_intake_storage.py:127-468`
- **Status:** resolved

The brainstorm requires capped retries, recoverable leases, independent processing batches, and concurrent intakes. Earlier tests inspected only one failed attempt and one successful call. Added raised and recorded failures, repeated capped retries, deterministic expiry, stale-token protection, in-flight idempotency, batch independence, per-intake exclusion, cross-intake concurrency, retained graph records, graceful shutdown, and activity-free retry waiting. The user approved this expansion and UTC clock injection into Storage and the pipeline.

### 2. Recall tests could not verify the search architecture

- **Category:** missing coverage
- **Severity:** critical
- **Location:** `tests/test_intake_recall.py:69-341`, `tests/test_intake_storage.py:470-532`
- **Status:** resolved

Per-table mocks did not cover one embedding or global layer-balanced ranking. Materialized ranked BM25/vector candidate interfaces and a Storage candidate operation. Added adversarial caps, consensus ranking, layer normalization, total result limits, empty results, and graph-only enrichment. The user approved final-total `k` and equal layer contribution. The plan specifies RRF offset 60, note/entity path weight 0.5, and intake path weight 1.

### 3. Entry points and citation lifecycle lacked coverage

- **Category:** missing coverage
- **Severity:** critical
- **Location:** `tests/test_intake_converse.py:65-217`, `tests/test_intake_recall_http.py:67-199`, `client/internal/api/intake_test.go:1-144`
- **Status:** resolved

The brainstorm requires queued evidence to remain separate and disappear after processing. The architecture routes HTTP, converse, and MCP through staging. Added converse dependency injection and staging tests, citation separation and disappearance tests, HTTP/SSE unprocessed-only context, and Go decoding and graph-separation tests. Added the missing Storage citation-fetch stub. The user approved the interface and coverage additions.

### 4. Lease and completion checks depended on elapsed time

- **Category:** non-deterministic
- **Severity:** critical
- **Location:** `tests/test_intake_storage.py:127-193`, `tests/test_ingestion_pipeline.py:15-139`
- **Status:** resolved

A one-millisecond lease depended on database latency. Runner entry also acted as proof of queue acknowledgement. Replaced elapsed-time eligibility with injected UTC clocks. Gated runner completion and observed queue snapshots before assertions. Event waits have bounds to detect stalled implementations, not to define lease or retry behavior. The user approved these changes.

### 5. Tests prescribed chunk layout, IDs, and queue ordering

- **Category:** over-specified
- **Severity:** warning
- **Location:** `tests/test_ingestion_pipeline.py:255-481`, `tests/test_ingestion_pipeline.py:627-837`
- **Status:** resolved

Short paragraphs required exactly two rows, controls assumed generated `intake-1`, and failure tests assumed FIFO. The architecture defines natural-boundary preferences, internal IDs, and no queue ordering. Replaced these expectations with bounded disjoint source evidence, public IDs from search results, and input-identified outcomes. Added sentence and oversized-text coverage. The user approved the correction.

### 6. HTTP and MCP tests used broken integration seams

- **Category:** wrong abstraction
- **Severity:** warning
- **Location:** `tests/test_intake_http.py:19-286`, `tests/test_intake_mcp.py:42-96`
- **Status:** resolved

HTTP tests lacked initialized pipeline resources and mocked the old agent symbol. MCP tests called an unmounted transport path. Replaced them with an injected staging pipeline and direct configured MCP tool calls. Added metadata, errors, validation, controls, and removed-job-route coverage. MCP count assertions accept structured values or acknowledgement text without prescribing serialization. The user approved the replacement.

### 7. Discard required an unspecified response field

- **Category:** over-specified
- **Severity:** warning
- **Location:** `tests/test_intake_http.py:254-275`, `tests/test_ingestion_pipeline.py:779-837`
- **Status:** resolved

The earlier test required `graph_records_rolled_back: false`. The architecture promises no rollback, not that field. Removed the field requirement and asserted that existing graph records remain after discard. The user approved this correction. The plan now states control identity and discarded-count response fields explicitly.

### 8. Embedding failure tests reached into Storage internals

- **Category:** wrong abstraction
- **Severity:** warning
- **Location:** `tests/test_intake_storage.py:17-124`
- **Status:** resolved

The earlier test mutated private `Storage._embedder`. Replaced this mutation with constructor injection of a failing embedder. Search tests no longer assume a unique result when the fixture gives every text the same vector direction. These unambiguous fixes preserve the staging contract.

## Validation

- Python contract: 104 collected, 98 expected failures, 6 passes.
- Full Python suite: 265 passed, 157 failed. The same 59 baseline failures remain outside this contract.
- Passing contract cases cover existing FastAPI validation and MCP callback forwarding.
- Go suite: one expected count-propagation failure. Other packages pass.
- Queue, pipeline, search, and missing integration behavior remains red. No implementation was added.
- Ruff, Basedpyright, formatting, and git hooks validate the changes before commit.

## Intent Coverage

All eight brainstorm decisions now map to interface tests: canonical ordered chunks, atomic staging, natural disjoint chunking, independent batches, continuous durable workers, at-least-once replay, separate searchable evidence, and aggregate controls. Provider timeout policy and production multi-instance wiring remain implementation concerns behind these interfaces. Tests use in-memory storage, local HTTP test transports, deterministic adapters, and no live models or external network state.
