# Test Review: Local Production Server

**Plan:** `docs/plans/local-production-server.md`
**Brainstorm:** `docs/brainstorms/local-production-server.md`
**Date:** 2026-10-24

## Summary

The tests exercise public deployment commands and observable files, permissions, and service operations. Missing archive, recovery, and installation paths now have coverage. A manual contract covers the one-time reset and live runtime verification.

## Findings

### 1. Incomplete archive and update safety coverage

- **Category:** missing coverage
- **Severity:** critical
- **Location:** `tests/test_local_production_server.py:467-600`
- **Status:** resolved

Added all non-idle pipeline fields, paused-only intake, request and parsing errors, independent retention sets, service failures, inactive-state recovery, and update abort coverage. The user approved these additions. The architecture now defines active processing and fail-closed behavior explicitly.

### 2. Reset and live persistence lacked verification contracts

- **Category:** missing coverage
- **Severity:** critical
- **Location:** `docs/manual-tests/local-production-server.md:1-64`
- **Status:** resolved

The brainstorm requires a fresh active database, unchanged experiment data, health, persistence, and restart verification. The user approved a manual contract for these operator actions. Added checks for loopback listeners, image identity, mounted data, journal lifecycle, lingering, and timer behavior. These journeys remain unexecuted.

### 3. Restore and installer error paths lacked coverage

- **Category:** missing coverage
- **Severity:** warning
- **Location:** `tests/test_local_production_server.py:603-704`
- **Status:** resolved

Added invalid archive entries, missing archive arguments, restore startup failure, required installer values, persistent mounts, and stop timeouts above configured ingestion grace. The user approved these additions. Existing tests cover extraction failure and experiment preservation.

### 4. Diagnostic assertions exceeded the interface

- **Category:** over-specified
- **Severity:** warning
- **Location:** `tests/test_local_production_server.py:240-433`
- **Status:** resolved

Removed required diagnostic words for archive, intake, restore, image, build, and backup-directory failures. The interface defines failure status and observable state, not those words. Retained daily deferred logging, which the architecture requires. The user approved the changes.

### 5. Parser and fault substitutes did not model their boundaries

- **Category:** wrong abstraction
- **Severity:** warning
- **Location:** `tests/test_local_production_server.py:31-110`
- **Status:** resolved

Removed the echo-only `jq` substitute. Tests now use the host parser specified by the approved architecture. Restricted tar fault injection to operation arguments so database paths do not trigger unrelated failures. Added cross-command event observations for the required build-before-archive-before-restart sequence.
