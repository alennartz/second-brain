# Test Review: TypeScript server rewrite

**Plan:** `docs/plans/typescript-server-rewrite.md`
**Brainstorm:** `docs/brainstorms/typescript-server-rewrite.md`
**Date:** 2026-10-25

## Summary

The original tests covered the main module boundaries but missed several acceptance contracts. The approved changes replace canned assertions and add fresh-database, runtime, queue, convergence, and live citation checks. Production interfaces remain unimplemented, so this review approves the behavioral contract, not implementation correctness.

## Findings

### 1. Canned storage and embedding expectations

- **Category:** wrong abstraction
- **Severity:** critical
- **Location:** `tests/storage.test.ts:1-110`, `tests/embedding.test.ts:1-33` before review
- **Status:** resolved

The tests demanded fixed vectors, record IDs, search rows, and lease results without arranging their inputs. These assertions could only validate canned responses. The user approved stateful storage tests with isolated databases and deterministic embedding injection. The revised tests cover graph records, search, re-embedding, transactions, and queue state through public interfaces.

### 2. Fresh database coverage was missing

- **Category:** missing coverage
- **Severity:** critical
- **Location:** `tests/surrealdb-latest.test.ts:1-20`
- **Status:** resolved

The original test opened a shared path and demanded `note:1`. The user approved an isolated fresh database with the TypeScript-owned schema. Fresh-schema coverage now checks records, vectors, relations, indexes, queue state, reopen persistence, and plain domain serialization. No Python fixture or migration provenance is required.

### 3. Runtime tests did not execute Pi or Codemode

- **Category:** missing coverage
- **Severity:** critical
- **Location:** `tests/agent-runtime.test.ts:29-35`, `tests/knowledge.test.ts:162-179` before review
- **Status:** resolved

Session-option assertions and a direct tool call did not prove SDK or Codemode behavior. The user approved an SDK-backed smoke seam with deterministic model transport. Runtime coverage now includes provider/model selection, actual direct and Codemode invocation, and schema validation. Knowledge tools also validate direct arguments and structured output.

### 4. Queue and scheduler reliability gaps

- **Category:** missing coverage
- **Severity:** critical
- **Location:** `tests/intake-pipeline.test.ts:116-162`, `tests/dream-scheduler.test.ts:100-166` before review
- **Status:** resolved

The tests omitted heartbeat ownership loss, capped retry delays, lease expiry, and per-idle-period convergence. The user approved these additions. Storage tests cover lease ownership and expiry. Pipeline tests cancel work after failed renewal and verify retry metadata. Scheduler tests observe the preserved convergence limit and activity reset with controlled clocks.

### 5. Missing application and storage seams

- **Category:** missing coverage
- **Severity:** critical
- **Location:** `src/workflows/workflows.ts:35-37`, `src/storage/storage.ts:17-70`, `src/http/contracts.ts:29-39` before review
- **Status:** resolved

Recall dropped caller hints, and live citation resolution lacked an application seam. Composite graph transactions, atomic idempotency fingerprints, and configured embedding adapters also lacked explicit contracts. The user approved interface and architecture changes. Tests now exercise these boundaries, including transaction rollback and failure propagation. A final interface check found missing edge-type enumeration and cooccurrence discovery primitives. The user approved both storage seams and their boundary tests. The knowledge test now follows the existing `references` relation for cooccurrence discovery.

### 6. Assertions constrained unspecified details

- **Category:** over-specified
- **Severity:** warning
- **Location:** `tests/agent-runtime.test.ts:62`, `tests/config.test.ts:24-28`, `tests/http.test.ts:125`, `tests/knowledge.test.ts:30` before review
- **Status:** resolved

Exact abort counts, parser message fragments, framework response text, and a fixed edge-table prefix exceeded the contract. The user approved relaxing these assertions. Tests retain observable cancellation, validation failure, missing-route status, and canonical record identities.
