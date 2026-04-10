# Review: Structured Ingest

**Plan:** `docs/plans/structured-ingest.md`
**Diff range:** `430c9b3..05f1823`
**Date:** 2026-04-10

## Summary

The plan was implemented faithfully — all three steps are done correctly with no meaningful deviations. Two code correctness warnings exist around error handling in `store_knowledge`: invalid `edge_table` names bypass the per-edge error recovery, and exceptions during note/edge creation discard the record of already-persisted entities.

## Findings

### 1. Invalid `edge_table` bypasses per-edge error handling

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/second_brain/tools/ingest_tools.py:209-233`
- **Status:** resolved

In `store_knowledge` step 4, `from_ref` and `to_ref` are validated inside a try/except that gracefully skips bad edges and records errors. However, `edge["edge_table"]` is passed through without validation at line 228. The actual validation happens later inside `create_edges` at line 93 (`validate_identifier`), where a `ValueError` propagates out of `create_edges`, out of `store_knowledge`, and into the agent wrapper — aborting all remaining edge creation.

If the LLM generates one edge with an invalid table name (e.g., `"part-of"` instead of `"part_of"`), all remaining edges are lost. Entities and notes are already persisted, but the return summary is never reached — the agent wrapper returns `{"error": "..."}` with no context about what was already created. Adding `validate_identifier(edge["edge_table"])` inside the existing try/except block at lines 213-218 would make the behavior consistent with ref validation.

### 2. Partial creation summary lost on mid-operation exceptions

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/second_brain/tools/ingest_tools.py:183-252`
- **Status:** resolved

`store_knowledge` performs three sequential write phases: entities (line 183), notes (line 193), edges (line 238). If entities succeed but an exception occurs during note creation (e.g., embedding API failure) or edge creation (e.g., the `validate_identifier` issue from Finding 1, or a `RuntimeError` from `check_query_result`), the exception escapes `store_knowledge`. The agent wrapper catches it and returns `{"error": str(e)}`.

The LLM receives no information about what was already persisted. Since writes are non-transactional (`db.create()` commits immediately), entities/notes remain in the database. The LLM may retry the entire call, creating duplicates. This is a new failure mode — previously the LLM called tools individually, so a successful call's results were visible before proceeding. Wrapping note and edge phases in try/except within `store_knowledge` itself, always returning the summary dict with partial results plus errors, would preserve the partial-success information.

## No Issues

Plan adherence: no significant deviations found. All three steps implemented as specified — `store_knowledge` function, agent wrapper and prompt update, and test suite confirmation. Test immutability confirmed (zero diff between pre-implementation commit and HEAD for test files). No unplanned changes detected.
