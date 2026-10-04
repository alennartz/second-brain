# Test Review: Jev converse routing

**Plan:** `docs/plans/jev-converse-routing.md`
**Brainstorm:** `docs/brainstorms/jev-converse-routing.md`
**Date:** 2026-10-03

## Summary

The reviewed suite covers the live confidence-gated shortcut while preserving the LLM router as the safety net. Four findings from the prior review were approved by the user and resolved here; history and context assertions were also strengthened. Tests use public routing/orchestration and HTTP/lifespan boundaries with deterministic local models and storage, not live services.

## Findings

### 1. Contradictory mixed-intent expectations

- **Category:** over-specified
- **Severity:** critical
- **Location:** `tests/test_routing.py:107-166`; `docs/plans/jev-converse-routing.md` Interfaces and Tests sections
- **Status:** resolved

Two tests and the interpretation pseudocode allowed one confident purity flag to override a second true flag. The user approved the behavioral contract as authoritative: both true always falls back, regardless of confidences. Replaced the conflicting tests with asymmetric-confidence cases and aligned the plan and interface documentation.

### 2. Missing HTTP wiring and startup failure coverage

- **Category:** missing coverage
- **Severity:** critical
- **Location:** `tests/test_converse_routing_http.py:60-192`; `src/second_brain/app.py:53-56`
- **Status:** resolved

The brainstorm makes Jev an optimization, never a single point of failure, including missing credentials. With user approval, extended the architecture to contain model construction failures at startup and materialized the optional routing-model wiring seam. Added real HTTP tests for recall, ingest, policy fallback, and runtime failure on both endpoints; lifespan tests cover test-mode/kill-switch bypass without credentials and warning-producing construction failure while health, recall, and both converse endpoints remain usable.

### 3. Decision telemetry was not asserted

- **Category:** missing coverage
- **Severity:** warning
- **Location:** `tests/test_routing.py:326-384`
- **Status:** resolved

The architecture promises telemetry for threshold tuning, but tests previously checked only that some warning existed on errors. User approved structured decision assertions on success and fallback. Specified record fields in the architecture and assert route, confidence mapping, threshold, and selected path for recall/ingest success, mixed/low-confidence fallback, and runtime failure. No exact human-readable message is pinned.

### 4. Confidence and zero-history boundaries were unspecified

- **Category:** missing coverage
- **Severity:** warning
- **Location:** `tests/test_routing.py:146-166,299-324,387-400`
- **Status:** resolved

User approved conservative fallback for missing/null/nonfinite/out-of-range confidence and current-message-only state when the window is zero. Added interpretation and model-result boundary tests, including absent provider details, and aligned interface/architecture documentation. Routing settings are explicitly reset by local fixtures rather than inherited from the environment.

### 5. Vacuous history-window and context equivalence assertions

- **Category:** missing coverage
- **Severity:** warning
- **Location:** `tests/test_converse_agent.py:152-267,345-385`
- **Status:** resolved

The history test permitted dropping all history and could count a system prompt as retained history. It now requires the precise latest two complete turns, filtering only supplied history contents. Recall equivalence now starts with existing node/edge citations and also adds a new citation, exercising actual deduplication rather than comparing empty accumulators. Ingest equivalence starts with nonempty context and requires it to remain unchanged. These are unambiguous strengthening of existing contracts.

## Validation

Full suite: **242 passed, 59 failed**. All 236 pre-existing tests pass. The 59 failures are expected against interface-only code: routing/orchestration stubs raise `NotImplementedError`, HTTP fast-path cases reveal absent endpoint wiring, and missing-credentials startup reveals absent routing construction. Six HTTP fallback/bypass cases already pass against today's behavior, correctly preserving the LLM floor. No collection errors or live network dependencies remain.
