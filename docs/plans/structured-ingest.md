# Plan: Structured Ingest

## Context

Replace the granular ingest tool surface with a single `store_knowledge` tool to cut LLM round trips from ~8 to ~3 per ingest. See [brainstorm](../brainstorms/structured-ingest.md) for the full problem analysis and design rationale.

## Architecture

### Impacted Modules

**`tools/ingest_tools.py`** — Gets the new `store_knowledge` function. The existing `create_notes`, `create_entities`, `create_edges` stay as internal building blocks (also used by dream connect agent). `store_knowledge` composes them and adds reference resolution.

**`agents/ingest.py`** — Tool registration changes: remove the three individual create tool registrations, add one `store_knowledge` tool. System prompt updated to reflect the new workflow (search broadly → store everything in one call). `search_knowledge`, `get_node`, `update_node` unchanged.

**Tests** — `test_ingest_agent.py` tool name assertions updated. New tests for `store_knowledge` in `test_ingest_tools.py` covering reference resolution, mixed new/existing refs, and error handling.

### Interfaces

**`store_knowledge` function (`ingest_tools.py`):**

```python
async def store_knowledge(
    db: AsyncSurreal,
    entities: list[dict],    # [{name: str, type: str, description?: str}]
    notes: list[dict],       # [{content: str, source?: str, summary?: str}]
    edges: list[dict],       # [{from_ref: str, edge_table: str, to_ref: str, context?: str}]
    embed_fn: Callable[[str], Awaitable[list[float]]],
) -> dict:
    """Create entities, notes, and edges in one atomic-ish operation.
    
    Execution order:
      1. Batch-create entities via create_entities → collect IDs
      2. Batch-create notes via create_notes → collect IDs  
      3. Build ref map: {"new_entity:0": "entity:abc", "new_note:0": "note:xyz", ...}
      4. Resolve from_ref/to_ref in edges: 
         - "new_entity:N" / "new_note:N" → lookup in ref map
         - anything else → pass through as existing record ID
      5. Create edges via create_edges
    
    Returns:
      {
        "entities_created": [{"ref": "new_entity:0", "id": "entity:abc", "name": "X"}, ...],
        "notes_created": [{"ref": "new_note:0", "id": "note:xyz"}, ...],
        "edges_created": int,
        "edges_skipped": int,
        "errors": [str, ...]
      }
    """
```

Edge reference resolution rules:
- `new_entity:N` → resolved to the ID of the Nth entity in the `entities` array (0-indexed)
- `new_note:N` → resolved to the ID of the Nth note in the `notes` array (0-indexed)
- Any other string (e.g. `entity:abc123`) → passed through as-is to `create_edges`
- Invalid ref (index out of bounds, malformed) → edge skipped, error recorded

The function uses `create_entities`, `create_notes`, and `create_edges` internally. If entity or note creation fails partway through, edges referencing failed items are skipped and errors are recorded. Partial results are returned, not raised.

**Agent tool wrapper (`agents/ingest.py`):**

```python
@agent.tool
async def store_knowledge(
    ctx: RunContext[IngestDeps],
    entities: list[dict],
    notes: list[dict],
    edges: list[dict],
) -> dict:
    """Store entities, notes, and edges in one call.
    
    entities: [{name, type, description?}]
    notes: [{content, source?, summary?}]
    edges: [{from_ref, edge_table, to_ref, context?}]
      from_ref/to_ref: "new_entity:N" or "new_note:N" for items in this call,
      or an existing record ID like "entity:abc123".
    """
```

Passes through to `ingest_tools.store_knowledge`. Returns the summary dict directly — compact enough for LLM context.

## Tests

**Pre-test-write commit:** `430c9b3f892e171136e0ea828c9c7f189515cdfa`

### Interface Files

- `src/second_brain/tools/ingest_tools.py` — Added `store_knowledge` stub (raises `NotImplementedError`)

### Test Files

- `tests/test_store_knowledge.py` — Behavioral tests for `store_knowledge` reference resolution, edge creation, error handling
- `tests/test_ingest_agent.py` — Updated tool name assertions for new tool surface

### Behaviors Covered

#### store_knowledge (ingest_tools)

- Creates entities and returns refs with assigned IDs
- Creates notes and returns refs with assigned IDs
- Resolves `new_entity:N` references in edges to created entity IDs
- Resolves `new_note:N` references in edges to created note IDs
- Passes through existing record IDs in edge refs unchanged
- Handles mixed new and existing refs in the same edge set
- Full realistic ingest scenario (multiple entities, notes, cross-referencing edges)
- Empty inputs return empty results with zero counts
- Entities-only and notes-only inputs work without edges
- Out-of-bounds entity ref index → edge skipped, error recorded
- Out-of-bounds note ref index → edge skipped, error recorded
- Malformed ref (not a valid record ID or new_* ref) → edge skipped, error recorded
- Valid edges still created when other edges in the same call fail
- Self-edges (same entity on both sides via refs) are skipped

#### Ingest Agent (agents/ingest)

- Agent tool surface includes `store_knowledge`, `search_knowledge`, `get_node`, `update_node`
- Old granular create tools (`create_notes`, `create_entities`, `create_edges`) are absent

**Review status:** approved

## Steps

### Step 1: Implement `store_knowledge` in `ingest_tools.py`

Replace the `NotImplementedError` stub in `src/second_brain/tools/ingest_tools.py` with the full implementation. The function already has the correct signature. Implementation:

1. **Create entities** — call the existing `create_entities(db, entities, embed_fn)`. Collect the returned list of dicts; each has an `"id"` field (a `RecordID` or string). Build `entities_created` list: `[{"ref": "new_entity:0", "id": <serialized_id>, "name": <name>}, ...]`.

2. **Create notes** — call the existing `create_notes(db, notes, embed_fn)`. Build `notes_created` list: `[{"ref": "new_note:0", "id": <serialized_id>}, ...]`.

3. **Build ref map** — a `dict[str, str]` mapping `"new_entity:0"` → `"entity:abc"`, `"new_note:0"` → `"note:xyz"`, etc. IDs come back as `RecordID` objects from SurrealDB — use `make_serializable` (from `second_brain.models`) to convert each to a `"table:id"` string before storing in the ref map.

4. **Resolve and filter edges** — for each edge in `edges`:
   - Resolve `from_ref` and `to_ref`: if it matches `new_entity:N` or `new_note:N`, look up in the ref map. If the ref isn't in the map (out-of-bounds index), record an error in `errors` and increment `edges_skipped`. If it doesn't match a `new_*` pattern, validate it as a record ID using `validate_record_id` — if invalid, record an error and skip. If valid, pass through as-is.
   - After resolving both sides, check for self-edges (resolved `from_id == to_id`) — skip with increment to `edges_skipped`.
   - Build the resolved edge dict with `from_id`, `edge_table`, `to_id`, and optional `context`.

5. **Create edges** — pass the resolved edge list to the existing `create_edges(db, resolved_edges)`. Count results: edges where `"skipped"` is truthy go to `edges_skipped`, others to `edges_created`.

6. **Return** the summary dict: `{"entities_created": [...], "notes_created": [...], "edges_created": int, "edges_skipped": int, "errors": [...]}`.

Import `make_serializable` from `second_brain.models` at the top of the file.

The `new_entity:N` / `new_note:N` pattern matching should use a simple prefix check and integer parse — no regex needed. A helper like `_resolve_ref(ref: str, ref_map: dict[str, str]) -> str` that returns the resolved ID or raises `ValueError` keeps the edge loop clean.

**Verify:** `uv run pytest -v tests/test_store_knowledge.py` — all 14 tests pass.
**Status:** not started

### Step 2: Add `store_knowledge` agent tool wrapper and remove old create tools in `ingest.py`

In `src/second_brain/agents/ingest.py`:

1. **Remove** the three `@agent.tool` functions: `create_notes`, `create_entities`, `create_edges`. These are the inner functions defined inside `create_ingest_agent()`, not the `ingest_tools` module-level functions (those stay).

2. **Add** a new `@agent.tool` function `store_knowledge` that wraps `ingest_tools.store_knowledge`:

```python
@agent.tool
async def store_knowledge(
    ctx: RunContext[IngestDeps],
    entities: list[dict],
    notes: list[dict],
    edges: list[dict],
) -> dict:
    """Store entities, notes, and edges in one call.

    entities: [{name, type, description?}]
    notes: [{content, source?, summary?}]
    edges: [{from_ref, edge_table, to_ref, context?}]
      from_ref/to_ref: "new_entity:N" or "new_note:N" for items in this call,
      or an existing record ID like "entity:abc123".
    """
    logger.info(
        "ingest: store_knowledge (%d entities, %d notes, %d edges)",
        len(entities), len(notes), len(edges),
    )
    try:
        result = await ingest_tools.store_knowledge(
            ctx.deps.db, entities, notes, edges, ctx.deps.embed_fn,
        )
        return make_serializable(result)
    except Exception as e:
        logger.error("ingest: store_knowledge failed: %s", e)
        return {"error": str(e)}
```

3. **Update the system prompt** — replace the numbered instructions that tell the LLM to create notes, entities, and edges in separate calls. The new workflow is: (1) parse input, (2) search broadly for dedup, (3) call `store_knowledge` once with all entities, notes, and edges. Keep the guidance about deduplication, entity-entity edges being most valuable, and descriptive edge names.

**Verify:** `uv run pytest -v tests/test_ingest_agent.py` — both tests pass (tool surface check and agent run).
**Status:** not started

### Step 3: Run full test suite to confirm no regressions

Run the complete Python test suite to verify nothing else broke — particularly `test_ingest_tools.py` (existing create functions still work), `test_dream_connect_agent.py` (still uses `create_edges` via `ingest_tools`), and `test_converse_agent.py` (delegates to ingest agent).

**Verify:** `uv run pytest -v` — all tests pass. No new test failures beyond the targeted changes.
**Status:** not started
