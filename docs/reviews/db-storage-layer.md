# Review: DB Storage Layer

**Plan:** `docs/plans/db-storage-layer.md`
**Diff range:** `50a19820e7099ee7eafb258e506a68be72f614bb..f678b58aab727a4c777151676a29e4bf46cddae6`
**Date:** 2026-04-14

## Summary

The plan was implemented faithfully across all 9 steps — every step is reflected in the diff with correct intent, and no unplanned work was introduced. Test immutability is preserved (no changes to `test_storage.py` or `conftest.py` between pre-implementation and HEAD). All 236 tests pass. The code correctness pass found several issues: a pre-existing data corruption risk in the scheduler that the refactor didn't address, validation regressions where `validate_record_id`/`validate_identifier` calls were removed without replacement in Storage, an error-handling regression where empty-result guards were dropped, and a behavioral change where `updated_at` is now polluted by dream cycle operations.

## Findings

### 1. Validation regression — `create_edges` direct path bypasses input sanitization

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/second_brain/tools/ingest_tools.py:19-21`
- **Status:** resolved

The old `create_edges` validated all inputs: `validate_record_id(edge["from_id"])`, `validate_record_id(edge["to_id"])`, `validate_identifier(edge["edge_table"])`. The new version reads them directly from the dict without validation and passes them to `Storage.create_edge`, which interpolates them into SurrealQL via f-strings (`f"RELATE {from_id}->{edge_table}->{to_id}"`). The `store_knowledge` flow still validates upstream via `_resolve_ref` and `validate_identifier`, but the direct `create_edges` path — used by the dream_connect agent — has no validation. This is a regression from the pre-refactor code. While the blast radius is limited (embedded SurrealDB, semi-trusted LLM agents), a confused agent output like an edge_table containing spaces or special characters would cause query parse errors or unexpected behavior.

### 2. `update_node` field keys interpolated into query without validation

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/second_brain/db.py:253-254`
- **Status:** resolved

Field keys are interpolated directly into the SET clause: `", ".join(f"{k} = ${k}" for k in fields)`. While field *values* are properly parameterized, the keys are not. The old `ingest_tools.update_node` called `validate_identifier(k)` for each field key before interpolation — that validation was removed in the refactor. Callers include the ingest agent's `update_node` tool (keys from LLM output) and the dedup agent's `merge_nodes` (keys from LLM `new_fields`). A malformed key could produce unexpected SurrealQL. Same blast-radius caveat as Finding 1.

### 3. `update_node` and `create_edge` crash with `IndexError` on empty result

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/second_brain/db.py:257`, `src/second_brain/db.py:280`
- **Status:** resolved

Both methods access `result[0]` after `_check` without guarding for an empty list. The old code had `rec = result[0] if result else {}` as a fallback. The new code:

```python
# update_node
result = self._check(result, f"update_node({record_id})")
return self._normalize(result[0])  # IndexError if UPDATE returns empty list

# create_edge
result = self._check(result, f"create_edge(...)")
return self._normalize(result[0])  # IndexError if RELATE returns empty list
```

SurrealDB's UPDATE may return an empty list for non-existent records rather than upserting. If any caller passes a stale or typo'd ID (e.g., the LLM outputs a wrong record_id to the ingest agent's `update_node` tool), this crashes with an unhandled `IndexError` instead of returning an error or empty dict.

### 4. `_increment_dream_age` runs `update_node` on deleted edge IDs

- **Category:** code correctness
- **Severity:** warning
- **Location:** `src/second_brain/scheduler.py:106-109` (run_cycle final_ids) + `src/second_brain/scheduler.py:98-100` (_increment_dream_age)
- **Status:** resolved

`dedup_deps.touched_ids` and `connect_deps.touched_ids` accumulate both node *and* edge IDs during merge operations. Many of these edge IDs are for edges that were deleted during merging (delete-recreate pattern). The scheduler passes all of them to `_increment_dream_age`:

```python
final_ids = list(set(result_set_ids + connect_deps.touched_ids))
await self._increment_dream_age(final_ids)
```

`_increment_dream_age` calls `update_node(rid, {"dream_age": ...})` for each ID. For a deleted edge ID, SurrealDB's UPDATE may upsert — recreating an orphaned edge record with only `dream_age` and `updated_at` fields but no `in`/`out` endpoints. These broken records accumulate over dream cycles. Note: this issue is pre-existing (the old code had `await self.db.query(f"UPDATE {rid} SET dream_age = dream_age + 1")` with the same problem), but the refactor didn't address it and it's still a live data corruption risk.

### 5. `updated_at` polluted by dream cycle `dream_age` increments

- **Category:** code correctness
- **Severity:** nit
- **Location:** `src/second_brain/db.py:255`
- **Status:** resolved

`update_node` unconditionally appends `updated_at = time::now()` to every update. When `_increment_dream_age` calls `update_node(rid, {"dream_age": N})`, it changes `updated_at` as a side effect. The old scheduler code (`UPDATE {rid} SET dream_age = dream_age + 1`) did not touch `updated_at`. This means every dream cycle now changes the `updated_at` timestamp on every processed node, even though no content changed. If anything uses `updated_at` for "last meaningful edit" semantics, dream cycles will pollute it.

### 6. `merge_edges` return value: `deleted_ids` omits the original survivor

- **Category:** code correctness
- **Severity:** nit
- **Location:** `src/second_brain/tools/dream_tools.py:451-460`
- **Status:** resolved

`merge_edges` deletes the original survivor edge and recreates it with new fields and a new ID, but `deleted_ids` only includes the loser IDs:

```python
await storage.delete_edge(survivor_id)          # survivor_id IS deleted
new_survivor = await storage.create_edge(...)   # gets a new ID
return {"survivor": new_survivor, "deleted_ids": loser_ids}
```

The original `survivor_id` (from `ids[0]`) is deleted but not tracked in `deleted_ids`. Any consumer that expects `deleted_ids` to enumerate all IDs that were removed from the database will miss this one. Similarly, `merge_nodes`'s `edges_auto_merged` entries label `existing_eid` as `"kept"` but that edge is actually deleted and recreated — the label is misleading given the delete-recreate pattern.

## No Issues

Plan adherence: no significant deviations found. All 9 plan steps were implemented faithfully, all test files remain unmodified since the test-write phase, and no unplanned changes were detected.
