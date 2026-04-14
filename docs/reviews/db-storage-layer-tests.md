# Test Review: DB Storage Layer

**Plan:** `docs/plans/db-storage-layer.md`
**Brainstorm:** `docs/brainstorms/db-storage-layer.md`
**Date:** 2026-04-14

## Summary

Tests cover all brainstorm intent comprehensively — every key decision (SurrealDB hiding, Storage class, Embedder protocol, fine-grained primitives, hybrid search in storage) maps to concrete test behaviors. Tests are at the correct abstraction level, exercising only the public `Storage` interface. Four findings were identified and resolved: one warning-level issue with the DummyEmbedder making re-embedding tests ineffective, and three nit-level missing-coverage gaps.

## Findings

### 1. DummyEmbedder constant output makes re-embedding tests ineffective

- **Category:** wrong abstraction
- **Severity:** warning
- **Location:** `tests/conftest.py:8-18`, `tests/test_storage.py:167-192`
- **Status:** resolved

`DummyEmbedder` returned `[0.0, 0.0, 0.0, 0.0]` for every call, making four re-embedding tests unable to verify their stated behavior. The three positive tests (`test_re_embeds_when_content_changes`, `test_re_embeds_when_name_changes`, `test_re_embeds_when_description_changes`) only checked that an embedding existed, not that it changed. The negative test (`test_does_not_re_embed_on_non_text_field`) compared old vs new embeddings, but they were always identical regardless of behavior.

**Fix:** Changed `DummyEmbedder` to counter-based (`[float(counter), 0.0, ...]`), producing unique vectors per call. Updated positive tests to compare old vs new embeddings. All vectors share direction so cosine-similarity search remains functional. Also updated `vector_search` tests to use `[1.0, 0, 0, 0]` instead of zero vectors to avoid undefined cosine similarity. User approved.

### 2. Missing delete_edge nonexistent case

- **Category:** missing coverage
- **Severity:** nit
- **Location:** `tests/test_storage.py:314-317` (added)
- **Status:** resolved

`TestDeleteNode` had `test_deleting_nonexistent_node_does_not_raise` but `TestDeleteEdge` had no equivalent. Added symmetric test `test_deleting_nonexistent_edge_does_not_raise`. User approved.

### 3. Missing vector_search empty results test

- **Category:** missing coverage
- **Severity:** nit
- **Location:** `tests/test_storage.py:383-385` (added)
- **Status:** resolved

`fulltext_search` and `hybrid_search` both had "returns empty for no matches" tests, but `vector_search` did not. Added `test_returns_empty_for_no_matches` searching an empty table. User approved.

### 4. select_batch ordering not verified

- **Category:** missing coverage
- **Severity:** nit
- **Location:** `tests/test_storage.py:475-488` (modified)
- **Status:** resolved

`test_selects_ordered_records_with_limit` only verified result count, not ordering. Updated test to set different `dream_age` values on three notes and assert ascending order in results. User approved.
