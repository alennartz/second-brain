# Dreaming Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a background dreaming agent that merges duplicates and discovers missing connections when the server is idle.

**Architecture:** Two-phase pipeline (dedup then connect) orchestrated by a Python async scheduler. Each phase is a PydanticAI agent with focused tools. The scheduler handles idle detection, wake-up interruption, batch selection by `dream_age`, and phase handoff. New dream-specific tools live in `dream_tools.py`.

**Tech Stack:** PydanticAI agents, SurrealDB (async), asyncio background tasks, FastAPI lifespan integration.

**Design doc:** `docs/plans/2026-03-02-dreaming-agent-design.md`

---

### Task 1: Add dream config settings

**Files:**
- Modify: `src/second_brain/config.py`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

In `tests/test_config.py`, add:

```python
def test_dream_defaults():
    """Dream settings have sensible defaults."""
    from second_brain.config import Settings
    s = Settings(test_mode=True)
    assert s.dream_enabled is True
    assert s.dream_idle_timeout == 10
    assert s.dream_batch_size == 10
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_dream_defaults -v`
Expected: FAIL — `Settings` has no `dream_enabled` attribute.

**Step 3: Write minimal implementation**

Add to `Settings` in `src/second_brain/config.py`:

```python
dream_enabled: bool = True
dream_idle_timeout: int = 10
dream_batch_size: int = 10
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py::test_dream_defaults -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/second_brain/config.py tests/test_config.py
git commit -m "feat(config): add dream scheduler settings"
```

---

### Task 2: Add `dream_age` to schema

**Files:**
- Modify: `src/second_brain/db.py`
- Test: `tests/test_db.py`

**Step 1: Write the failing test**

In `tests/test_db.py`, add:

```python
from second_brain.db import init_schema

async def test_dream_age_defaults(db):
    """Nodes and edges get dream_age=0 by default."""
    await init_schema(db)
    await db.query("""
        CREATE note:1 SET content = 'test', source = 'cli';
        CREATE entity:a SET name = 'A', type = 'concept';
        CREATE note:2 SET content = 'test2', source = 'cli';
        RELATE note:1->references->entity:a;
        RELATE entity:a->relates_to->entity:a SET context = 'self';
        RELATE note:1->derived_from->note:2;
    """)
    note = (await db.query("SELECT dream_age FROM note:1"))[0]
    entity = (await db.query("SELECT dream_age FROM entity:a"))[0]
    ref_edges = await db.query("SELECT dream_age FROM references")
    rel_edges = await db.query("SELECT dream_age FROM relates_to")
    der_edges = await db.query("SELECT dream_age FROM derived_from")

    assert note["dream_age"] == 0
    assert entity["dream_age"] == 0
    assert ref_edges[0]["dream_age"] == 0
    assert rel_edges[0]["dream_age"] == 0
    assert der_edges[0]["dream_age"] == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_dream_age_defaults -v`
Expected: FAIL — `dream_age` field does not exist.

**Step 3: Write minimal implementation**

In `src/second_brain/db.py`, add `dream_age` fields to the schema in `init_schema`:

```sql
-- After existing note fields:
DEFINE FIELD IF NOT EXISTS dream_age ON note TYPE int DEFAULT 0;

-- After existing entity fields:
DEFINE FIELD IF NOT EXISTS dream_age ON entity TYPE int DEFAULT 0;

-- On edge tables:
DEFINE FIELD IF NOT EXISTS dream_age ON references TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS dream_age ON relates_to TYPE int DEFAULT 0;
DEFINE FIELD IF NOT EXISTS dream_age ON derived_from TYPE int DEFAULT 0;
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py::test_dream_age_defaults -v`
Expected: PASS

**Step 5: Run all existing tests to check nothing broke**

Run: `uv run pytest -v`
Expected: All pass.

**Step 6: Commit**

```bash
git add src/second_brain/db.py tests/test_db.py
git commit -m "feat(db): add dream_age field to all node and edge tables"
```

---

### Task 3: Implement `find_similar` tool

**Files:**
- Create: `src/second_brain/tools/dream_tools.py`
- Test: `tests/test_dream_tools.py`

**Step 1: Write the failing test**

Create `tests/test_dream_tools.py`:

```python
import pytest
from second_brain.db import init_schema, init_vector_indexes


@pytest.fixture
async def dream_db(db):
    """DB with schema, vector indexes, and sample entities with embeddings."""
    await init_schema(db)
    await init_vector_indexes(db, dimensions=3)
    await db.query("""
        CREATE entity:py SET name = 'Python', type = 'language',
            embedding = [0.9, 0.1, 0.0];
        CREATE entity:py3 SET name = 'Python 3', type = 'language',
            embedding = [0.85, 0.15, 0.0];
        CREATE entity:rust SET name = 'Rust', type = 'language',
            embedding = [0.0, 0.1, 0.9];
    """)
    return db


async def test_find_similar_returns_nearest_neighbors(dream_db):
    from second_brain.tools.dream_tools import find_similar

    results = await find_similar(dream_db, "entity:py", k=2)
    assert len(results) >= 1
    # Python 3 should be more similar to Python than Rust is
    ids = [str(r["id"]) for r in results]
    assert any("entity:py3" in rid for rid in ids)
    # Should not include the source node itself
    assert not any("entity:py" == rid for rid in ids)


async def test_find_similar_includes_similarity_score(dream_db):
    from second_brain.tools.dream_tools import find_similar

    results = await find_similar(dream_db, "entity:py", k=2)
    assert all("similarity" in r for r in results)
    assert all(isinstance(r["similarity"], float) for r in results)


async def test_find_similar_strips_embeddings(dream_db):
    from second_brain.tools.dream_tools import find_similar

    results = await find_similar(dream_db, "entity:py", k=2)
    assert all("embedding" not in r for r in results)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dream_tools.py -v`
Expected: FAIL — module `dream_tools` does not exist.

**Step 3: Write minimal implementation**

Create `src/second_brain/tools/dream_tools.py`:

```python
import logging
import math

from surrealdb import AsyncSurreal, RecordID

from second_brain.models import make_serializable, strip_embeddings

logger = logging.getLogger(__name__)


def _to_str(val) -> str:
    if isinstance(val, RecordID):
        return f"{val.table_name}:{val.id}"
    return str(val)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def find_similar(
    db: AsyncSurreal,
    record_id: str,
    k: int = 5,
) -> list[dict]:
    """Find the k nearest same-table neighbors by embedding similarity.

    Returns results with similarity scores, embeddings stripped.
    Excludes the source node itself.
    """
    table = record_id.split(":")[0]

    # Fetch the source node's embedding
    source = await db.query(f"SELECT embedding FROM {record_id}")
    if not source or not source[0].get("embedding"):
        logger.warning("find_similar: no embedding for %s", record_id)
        return []
    source_embedding = source[0]["embedding"]

    # Vector search for nearest neighbors (fetch k+1 to account for self-match)
    results = await db.query(
        f"SELECT * FROM {table} WHERE embedding <|{k + 1},100|> $vec",
        {"vec": source_embedding},
    )
    if isinstance(results, str):
        raise RuntimeError(f"Vector search on {table} failed: {results}")

    # Filter out the source node, compute similarity, strip embeddings
    filtered = []
    for rec in results:
        rid = _to_str(rec["id"])
        if rid == record_id:
            continue
        sim = _cosine_similarity(source_embedding, rec.get("embedding", []))
        cleaned = strip_embeddings(make_serializable(rec))
        cleaned["similarity"] = round(sim, 4)
        filtered.append(cleaned)

    filtered.sort(key=lambda r: r["similarity"], reverse=True)
    return filtered[:k]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dream_tools.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/second_brain/tools/dream_tools.py tests/test_dream_tools.py
git commit -m "feat(tools): add find_similar for dream agent duplicate detection"
```

---

### Task 4: Implement `merge_nodes` tool

**Files:**
- Modify: `src/second_brain/tools/dream_tools.py`
- Modify: `tests/test_dream_tools.py`

**Step 1: Write the failing tests**

Add to `tests/test_dream_tools.py`:

```python
from unittest.mock import AsyncMock

dummy_embed = AsyncMock(return_value=[0.5, 0.5, 0.0])


@pytest.fixture
async def merge_db(db):
    """DB with schema and nodes ready for merging."""
    await init_schema(db)
    await db.query("""
        CREATE entity:py SET name = 'Python', type = 'language',
            description = 'A programming language', dream_age = 1;
        CREATE entity:py3 SET name = 'Python 3', type = 'language',
            description = 'Latest version of Python', dream_age = 3;
        CREATE entity:fa SET name = 'FastAPI', type = 'framework';
        CREATE note:1 SET content = 'test note', source = 'cli';
        RELATE note:1->references->entity:py SET dream_age = 2;
        RELATE note:1->references->entity:py3 SET dream_age = 5;
        RELATE entity:py->built_with->entity:fa SET dream_age = 1;
        RELATE entity:py3->built_with->entity:fa SET dream_age = 4;
    """)
    return db


async def test_merge_nodes_fuses_into_first(merge_db):
    from second_brain.tools.dream_tools import merge_nodes

    result = await merge_nodes(
        merge_db,
        ids=["entity:py", "entity:py3"],
        new_fields={"name": "Python", "description": "A versatile programming language"},
        embed_fn=dummy_embed,
    )
    # Survivor should have fused fields
    assert result["survivor"]["name"] == "Python"
    assert result["survivor"]["description"] == "A versatile programming language"
    # Loser should be deleted
    gone = await merge_db.query("SELECT * FROM entity:py3")
    assert gone == [] or gone is None or (isinstance(gone, list) and len(gone) == 0)


async def test_merge_nodes_repoints_edges(merge_db):
    from second_brain.tools.dream_tools import merge_nodes

    await merge_nodes(
        merge_db,
        ids=["entity:py", "entity:py3"],
        new_fields={"name": "Python"},
        embed_fn=dummy_embed,
    )
    # note:1 should reference entity:py (repointed from py3)
    refs = await merge_db.query("SELECT * FROM note:1->references")
    ref_targets = [str(r.get("out") or r.get("id", "")) for r in refs] if refs else []
    # There should be exactly one references edge to entity:py (deduped)
    assert len(refs) == 1


async def test_merge_nodes_deduplicates_edges(merge_db):
    from second_brain.tools.dream_tools import merge_nodes

    await merge_nodes(
        merge_db,
        ids=["entity:py", "entity:py3"],
        new_fields={"name": "Python"},
        embed_fn=dummy_embed,
    )
    # Both had built_with->entity:fa, should be deduped to one
    edges = await merge_db.query("SELECT * FROM built_with WHERE out = entity:fa")
    assert len(edges) == 1


async def test_merge_nodes_dream_age_takes_max(merge_db):
    from second_brain.tools.dream_tools import merge_nodes

    result = await merge_nodes(
        merge_db,
        ids=["entity:py", "entity:py3"],
        new_fields={"name": "Python"},
        embed_fn=dummy_embed,
    )
    # dream_age should be max(1, 3) = 3
    survivor = (await merge_db.query("SELECT dream_age FROM entity:py"))[0]
    assert survivor["dream_age"] == 3


async def test_merge_nodes_edge_dream_age_takes_max(merge_db):
    from second_brain.tools.dream_tools import merge_nodes

    await merge_nodes(
        merge_db,
        ids=["entity:py", "entity:py3"],
        new_fields={"name": "Python"},
        embed_fn=dummy_embed,
    )
    # Surviving built_with edge should have dream_age = max(1, 4) = 4
    edges = await merge_db.query("SELECT dream_age FROM built_with WHERE out = entity:fa")
    assert edges[0]["dream_age"] == 4

    # Surviving references edge should have dream_age = max(2, 5) = 5
    refs = await merge_db.query("SELECT dream_age FROM references WHERE out = entity:py")
    assert refs[0]["dream_age"] == 5
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dream_tools.py::test_merge_nodes_fuses_into_first -v`
Expected: FAIL — `merge_nodes` not defined.

**Step 3: Write minimal implementation**

Add to `src/second_brain/tools/dream_tools.py`:

```python
from collections.abc import Awaitable, Callable


async def merge_nodes(
    db: AsyncSurreal,
    ids: list[str],
    new_fields: dict,
    embed_fn: Callable[[str], Awaitable[list[float]]],
) -> dict:
    """Fuse N nodes into one. First ID is the survivor.

    - Updates survivor with new_fields and re-embeds
    - Re-points all edges from losers to survivor
    - Auto-merges duplicate edges (same table + direction + target)
      with dream_age = max(inputs)
    - Survivor gets dream_age = max(all input nodes)
    - Deletes loser nodes
    - Returns {"survivor": {...}, "touched_ids": [...]}
    """
    if len(ids) < 2:
        raise ValueError("merge_nodes requires at least 2 IDs")

    survivor_id = ids[0]
    loser_ids = ids[1:]

    # Compute max dream_age across all input nodes
    all_ages = []
    for nid in ids:
        rec = await db.query(f"SELECT dream_age FROM {nid}")
        if rec:
            all_ages.append(rec[0].get("dream_age", 0))
    max_age = max(all_ages) if all_ages else 0

    # Re-embed based on new fields
    text_to_embed = new_fields.get("content") or new_fields.get("description") or new_fields.get("name", "")
    new_embedding = await embed_fn(text_to_embed)

    # Update survivor with new fields + embedding + dream_age
    set_clauses = ", ".join(f"{k} = ${k}" for k in new_fields)
    await db.query(
        f"UPDATE {survivor_id} SET {set_clauses}, embedding = $emb, dream_age = $age, updated_at = time::now()",
        {**new_fields, "emb": new_embedding, "age": max_age},
    )

    touched_ids = list(ids)

    # Re-point edges from each loser to survivor
    for loser_id in loser_ids:
        # Outgoing edges: loser->X becomes survivor->X
        out_edges = await db.query(f"SELECT * FROM {loser_id}->?")
        if isinstance(out_edges, list):
            for edge in out_edges:
                edge_id = _to_str(edge["id"])
                edge_table = edge_id.split(":")[0]
                target_id = _to_str(edge["out"])
                edge_age = edge.get("dream_age", 0)
                context = edge.get("context")
                touched_ids.append(edge_id)

                # Check if survivor already has same edge
                existing = await db.query(
                    f"SELECT * FROM {survivor_id}->{edge_table} WHERE out = {target_id}"
                )
                if existing:
                    # Duplicate: merge dream_age, delete the loser edge
                    existing_age = existing[0].get("dream_age", 0)
                    existing_eid = _to_str(existing[0]["id"])
                    new_age = max(edge_age, existing_age)
                    await db.query(f"UPDATE {existing_eid} SET dream_age = {new_age}")
                    await db.query(f"DELETE {edge_id}")
                    touched_ids.append(existing_eid)
                else:
                    # Re-point: delete old, create new
                    ctx_clause = " SET context = $ctx, dream_age = $age" if context else f" SET dream_age = $age"
                    params = {"age": edge_age}
                    if context:
                        params["ctx"] = context
                    await db.query(f"DELETE {edge_id}")
                    await db.query(
                        f"RELATE {survivor_id}->{edge_table}->{target_id}{ctx_clause}",
                        params,
                    )

        # Incoming edges: X->loser becomes X->survivor
        in_edges = await db.query(f"SELECT * FROM {loser_id}<-?")
        if isinstance(in_edges, list):
            for edge in in_edges:
                edge_id = _to_str(edge["id"])
                edge_table = edge_id.split(":")[0]
                source_id = _to_str(edge["in"])
                edge_age = edge.get("dream_age", 0)
                context = edge.get("context")
                touched_ids.append(edge_id)

                # Check if survivor already has same incoming edge
                existing = await db.query(
                    f"SELECT * FROM {source_id}->{edge_table} WHERE out = {survivor_id}"
                )
                if existing:
                    existing_age = existing[0].get("dream_age", 0)
                    existing_eid = _to_str(existing[0]["id"])
                    new_age = max(edge_age, existing_age)
                    await db.query(f"UPDATE {existing_eid} SET dream_age = {new_age}")
                    await db.query(f"DELETE {edge_id}")
                    touched_ids.append(existing_eid)
                else:
                    ctx_clause = " SET context = $ctx, dream_age = $age" if context else f" SET dream_age = $age"
                    params = {"age": edge_age}
                    if context:
                        params["ctx"] = context
                    await db.query(f"DELETE {edge_id}")
                    await db.query(
                        f"RELATE {source_id}->{edge_table}->{survivor_id}{ctx_clause}",
                        params,
                    )

        # Delete the loser node
        await db.query(f"DELETE {loser_id}")

    survivor = await db.query(f"SELECT * FROM {survivor_id}")
    return {
        "survivor": strip_embeddings(make_serializable(survivor[0])) if survivor else {},
        "touched_ids": list(set(touched_ids)),
    }
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dream_tools.py -k merge_nodes -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/second_brain/tools/dream_tools.py tests/test_dream_tools.py
git commit -m "feat(tools): add merge_nodes for dream agent deduplication"
```

---

### Task 5: Implement `merge_edges` tool

**Files:**
- Modify: `src/second_brain/tools/dream_tools.py`
- Modify: `tests/test_dream_tools.py`

**Step 1: Write the failing tests**

Add to `tests/test_dream_tools.py`:

```python
@pytest.fixture
async def edge_merge_db(db):
    """DB with duplicate edges between same nodes."""
    await init_schema(db)
    await db.query("""
        CREATE entity:a SET name = 'A', type = 'concept';
        CREATE entity:b SET name = 'B', type = 'concept';
        RELATE entity:a->relates_to->entity:b SET context = 'first relationship', dream_age = 2;
        RELATE entity:a->relates_to->entity:b SET context = 'second relationship', dream_age = 5;
    """)
    return db


async def test_merge_edges_fuses(edge_merge_db):
    from second_brain.tools.dream_tools import merge_edges

    edges = await edge_merge_db.query(
        "SELECT * FROM relates_to WHERE in = entity:a AND out = entity:b"
    )
    edge_ids = [_to_str(e["id"]) for e in edges]
    assert len(edge_ids) == 2

    result = await merge_edges(
        edge_merge_db,
        ids=edge_ids,
        new_context="combined relationship",
    )

    # Should have one surviving edge
    remaining = await edge_merge_db.query(
        "SELECT * FROM relates_to WHERE in = entity:a AND out = entity:b"
    )
    assert len(remaining) == 1
    assert remaining[0]["context"] == "combined relationship"


async def test_merge_edges_dream_age_takes_max(edge_merge_db):
    from second_brain.tools.dream_tools import merge_edges

    edges = await edge_merge_db.query(
        "SELECT * FROM relates_to WHERE in = entity:a AND out = entity:b"
    )
    edge_ids = [_to_str(e["id"]) for e in edges]

    await merge_edges(edge_merge_db, ids=edge_ids, new_context="merged")

    remaining = await edge_merge_db.query(
        "SELECT * FROM relates_to WHERE in = entity:a AND out = entity:b"
    )
    assert remaining[0]["dream_age"] == 5
```

Note: the test file will need `from second_brain.tools.dream_tools import _to_str` or use a local helper.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dream_tools.py -k merge_edges -v`
Expected: FAIL — `merge_edges` not defined.

**Step 3: Write minimal implementation**

Add to `src/second_brain/tools/dream_tools.py`:

```python
async def merge_edges(
    db: AsyncSurreal,
    ids: list[str],
    new_context: str | None = None,
) -> dict:
    """Fuse N edges into one. First ID is the survivor.

    - Survivor gets new_context and dream_age = max(all inputs)
    - Losers are deleted
    - Returns {"survivor": {...}, "deleted_ids": [...]}
    """
    if len(ids) < 2:
        raise ValueError("merge_edges requires at least 2 IDs")

    survivor_id = ids[0]
    loser_ids = ids[1:]

    # Get max dream_age
    all_ages = []
    for eid in ids:
        rec = await db.query(f"SELECT dream_age FROM {eid}")
        if rec:
            all_ages.append(rec[0].get("dream_age", 0))
    max_age = max(all_ages) if all_ages else 0

    # Update survivor
    if new_context is not None:
        await db.query(
            f"UPDATE {survivor_id} SET context = $ctx, dream_age = $age",
            {"ctx": new_context, "age": max_age},
        )
    else:
        await db.query(f"UPDATE {survivor_id} SET dream_age = {max_age}")

    # Delete losers
    for lid in loser_ids:
        await db.query(f"DELETE {lid}")

    survivor = await db.query(f"SELECT * FROM {survivor_id}")
    return {
        "survivor": make_serializable(survivor[0]) if survivor else {},
        "deleted_ids": loser_ids,
    }
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dream_tools.py -k merge_edges -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/second_brain/tools/dream_tools.py tests/test_dream_tools.py
git commit -m "feat(tools): add merge_edges for dream agent edge deduplication"
```

---

### Task 6: Implement `explore` tool

**Files:**
- Modify: `src/second_brain/tools/dream_tools.py`
- Modify: `tests/test_dream_tools.py`

**Step 1: Write the failing tests**

Add to `tests/test_dream_tools.py`:

```python
@pytest.fixture
async def graph_db(db):
    """DB with a small graph for exploration tests."""
    await init_schema(db)
    await db.query("""
        CREATE entity:py SET name = 'Python', type = 'language';
        CREATE entity:fa SET name = 'FastAPI', type = 'framework';
        CREATE entity:sr SET name = 'SurrealDB', type = 'database';
        CREATE note:1 SET content = 'FastAPI is built with Python', source = 'cli';
        CREATE note:2 SET content = 'SurrealDB has a Python SDK', source = 'cli';
        RELATE note:1->references->entity:py;
        RELATE note:1->references->entity:fa;
        RELATE note:2->references->entity:py;
        RELATE note:2->references->entity:sr;
        RELATE entity:fa->built_with->entity:py;
    """)
    return db


async def test_explore_outgoing_entities(graph_db):
    from second_brain.tools.dream_tools import explore

    result = await explore(graph_db, "entity:fa", direction="out", node_types=["entity"], depth=2)
    # entity:fa -> built_with -> entity:py
    target_ids = [str(t["node"]["id"]) for t in result["targets"]]
    assert any("entity:py" in tid for tid in target_ids)


async def test_explore_incoming_notes(graph_db):
    from second_brain.tools.dream_tools import explore

    result = await explore(graph_db, "entity:py", direction="in", node_types=["note"], depth=1)
    # note:1 and note:2 both reference entity:py
    target_ids = [str(t["node"]["id"]) for t in result["targets"]]
    assert len(target_ids) >= 2


async def test_explore_both_directions(graph_db):
    from second_brain.tools.dream_tools import explore

    result = await explore(graph_db, "entity:py", direction="both", node_types=["entity"], depth=2)
    # Should find entity:fa (via built_with incoming) and entity:sr (via note:2 path)
    target_ids = [str(t["node"]["id"]) for t in result["targets"]]
    assert any("entity:fa" in tid for tid in target_ids)


async def test_explore_returns_paths(graph_db):
    from second_brain.tools.dream_tools import explore

    result = await explore(graph_db, "entity:fa", direction="out", node_types=["entity"], depth=2)
    # Each target should have a path showing how it was reached
    for target in result["targets"]:
        assert "path" in target
        assert isinstance(target["path"], list)


async def test_explore_depth_bounded(graph_db):
    from second_brain.tools.dream_tools import explore

    result = await explore(graph_db, "entity:sr", direction="out", node_types=["entity"], depth=1)
    # entity:sr has no outgoing edges to entities at depth 1
    assert len(result["targets"]) == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dream_tools.py -k explore -v`
Expected: FAIL — `explore` not defined.

**Step 3: Write minimal implementation**

Add to `src/second_brain/tools/dream_tools.py`:

```python
async def explore(
    db: AsyncSurreal,
    record_id: str,
    direction: str = "both",
    node_types: list[str] | None = None,
    depth: int = 2,
) -> dict:
    """Explore graph neighborhood from a node.

    Args:
        record_id: Starting node.
        direction: "out", "in", or "both".
        node_types: Filter target nodes by table (e.g., ["entity", "note"]).
        depth: Max hops (bounded to 3).

    Returns:
        {"targets": [{"node": {...}, "path": [{"edge_label": ..., "node_id": ...}, ...]}]}
        Target nodes have full content (embeddings stripped).
        Paths show intermediate node IDs and edge labels.
    """
    depth = min(depth, 3)
    node_types = node_types or ["entity", "note"]

    visited = {record_id}
    # BFS: each entry is (node_id, path_so_far)
    queue: list[tuple[str, list[dict]]] = [(record_id, [])]
    targets: list[dict] = []

    for _ in range(depth):
        next_queue: list[tuple[str, list[dict]]] = []
        for current_id, path in queue:
            neighbors = []

            if direction in ("out", "both"):
                out_edges = await db.query(f"SELECT * FROM {current_id}->?")
                if isinstance(out_edges, list):
                    for edge in out_edges:
                        eid = _to_str(edge["id"])
                        label = eid.split(":")[0]
                        neighbor_id = _to_str(edge["out"])
                        neighbors.append((neighbor_id, label))

            if direction in ("in", "both"):
                in_edges = await db.query(f"SELECT * FROM {current_id}<-?")
                if isinstance(in_edges, list):
                    for edge in in_edges:
                        eid = _to_str(edge["id"])
                        label = eid.split(":")[0]
                        neighbor_id = _to_str(edge["in"])
                        neighbors.append((neighbor_id, label))

            for neighbor_id, label in neighbors:
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                new_path = path + [{"edge_label": label, "node_id": neighbor_id}]
                neighbor_table = neighbor_id.split(":")[0]

                if neighbor_table in node_types:
                    # Fetch full node content
                    node = await db.query(f"SELECT * FROM {neighbor_id}")
                    if node:
                        targets.append({
                            "node": strip_embeddings(make_serializable(node[0])),
                            "path": new_path,
                        })

                # Continue traversal regardless of whether this node matched filter
                next_queue.append((neighbor_id, new_path))

        queue = next_queue

    return {"targets": targets}
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dream_tools.py -k explore -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/second_brain/tools/dream_tools.py tests/test_dream_tools.py
git commit -m "feat(tools): add explore for dream agent graph traversal"
```

---

### Task 7: Implement `find_unlinked_cooccurrences` tool

**Files:**
- Modify: `src/second_brain/tools/dream_tools.py`
- Modify: `tests/test_dream_tools.py`

**Step 1: Write the failing tests**

Add to `tests/test_dream_tools.py` (reuse `graph_db` fixture):

```python
async def test_find_unlinked_cooccurrences(graph_db):
    from second_brain.tools.dream_tools import find_unlinked_cooccurrences

    # entity:py and entity:fa share note:1 and fa->built_with->py exists,
    # but entity:py and entity:sr share note:2 and have no direct edge
    results = await find_unlinked_cooccurrences(graph_db, "entity:py")
    # Should find entity:sr as an unlinked cooccurrence
    other_ids = [str(r["entity"]["id"]) for r in results]
    assert any("entity:sr" in oid for oid in other_ids)


async def test_find_unlinked_cooccurrences_excludes_linked(graph_db):
    from second_brain.tools.dream_tools import find_unlinked_cooccurrences

    # entity:fa is linked to entity:py via built_with, should not appear
    results = await find_unlinked_cooccurrences(graph_db, "entity:py")
    other_ids = [str(r["entity"]["id"]) for r in results]
    assert not any("entity:fa" in oid for oid in other_ids)


async def test_find_unlinked_cooccurrences_includes_shared_notes(graph_db):
    from second_brain.tools.dream_tools import find_unlinked_cooccurrences

    results = await find_unlinked_cooccurrences(graph_db, "entity:py")
    # Results should include the shared note IDs
    for r in results:
        assert "shared_notes" in r
        assert len(r["shared_notes"]) >= 1


async def test_find_unlinked_cooccurrences_no_results(graph_db):
    from second_brain.tools.dream_tools import find_unlinked_cooccurrences

    # entity:sr only shares notes with entity:py, and they aren't linked,
    # but from entity:sr's perspective entity:py should show up
    await graph_db.query("RELATE entity:sr->relates_to->entity:py")
    results = await find_unlinked_cooccurrences(graph_db, "entity:sr")
    # Now they are linked, so no results
    assert len(results) == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dream_tools.py -k cooccurrences -v`
Expected: FAIL — `find_unlinked_cooccurrences` not defined.

**Step 3: Write minimal implementation**

Add to `src/second_brain/tools/dream_tools.py`:

```python
async def find_unlinked_cooccurrences(
    db: AsyncSurreal,
    record_id: str,
) -> list[dict]:
    """Find entities that share notes with this entity but have no direct edge.

    Follows: entity <-references- note -references-> other_entity
    Filters out pairs that already have any direct edge between them.

    Returns: [{"entity": {...}, "shared_notes": ["note:x", ...]}, ...]
    """
    table = record_id.split(":")[0]
    if table != "entity":
        return []

    # Find all notes that reference this entity
    notes = await db.query(f"SELECT * FROM {record_id}<-references")
    if not isinstance(notes, list) or not notes:
        return []

    note_ids = [_to_str(n["in"]) for n in notes]

    # For each note, find other entities it references
    cooccurrences: dict[str, list[str]] = {}  # other_entity_id -> [note_ids]
    for note_id in note_ids:
        refs = await db.query(f"SELECT * FROM {note_id}->references")
        if not isinstance(refs, list):
            continue
        for ref in refs:
            other_id = _to_str(ref["out"])
            if other_id == record_id:
                continue
            other_table = other_id.split(":")[0]
            if other_table != "entity":
                continue
            cooccurrences.setdefault(other_id, []).append(note_id)

    # Filter out entities that already have a direct edge (either direction)
    results = []
    for other_id, shared_notes in cooccurrences.items():
        # Check for any direct edge in either direction
        out_edges = await db.query(f"SELECT * FROM {record_id}->? WHERE out = {other_id}")
        in_edges = await db.query(f"SELECT * FROM {other_id}->? WHERE out = {record_id}")
        has_out = isinstance(out_edges, list) and len(out_edges) > 0
        has_in = isinstance(in_edges, list) and len(in_edges) > 0
        if has_out or has_in:
            continue

        # Fetch the other entity's content
        other = await db.query(f"SELECT * FROM {other_id}")
        if other:
            results.append({
                "entity": strip_embeddings(make_serializable(other[0])),
                "shared_notes": list(set(shared_notes)),
            })

    return results
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dream_tools.py -k cooccurrences -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/second_brain/tools/dream_tools.py tests/test_dream_tools.py
git commit -m "feat(tools): add find_unlinked_cooccurrences for dream agent connection discovery"
```

---

### Task 8: Implement dedup agent

**Files:**
- Create: `src/second_brain/agents/dream_dedup.py`
- Create: `tests/test_dream_dedup_agent.py`

**Step 1: Write the failing test**

Create `tests/test_dream_dedup_agent.py`:

```python
import asyncio

import pytest
from pydantic_ai.models.test import TestModel
from unittest.mock import AsyncMock

from second_brain.db import init_schema, init_vector_indexes
from second_brain.agents.dream_dedup import DedupDeps, create_dedup_agent


dummy_embed = AsyncMock(return_value=[0.5, 0.5, 0.0])


@pytest.fixture
async def dedup_db(db):
    await init_schema(db)
    await init_vector_indexes(db, dimensions=3)
    await db.query("""
        CREATE entity:py SET name = 'Python', type = 'language',
            description = 'A programming language', embedding = [0.9, 0.1, 0.0], dream_age = 0;
        CREATE entity:py3 SET name = 'Python 3', type = 'language',
            description = 'Third version of Python', embedding = [0.85, 0.15, 0.0], dream_age = 0;
    """)
    return db


async def test_dedup_agent_runs(dedup_db):
    """Dedup agent can run without crashing."""
    cancel = asyncio.Event()
    agent = create_dedup_agent()
    deps = DedupDeps(db=dedup_db, embed_fn=dummy_embed, cancel=cancel)
    result = await agent.run(
        "Process this batch of nodes for deduplication: entity:py, entity:py3",
        deps=deps,
        model=TestModel(),
    )
    assert isinstance(result.output, str)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dream_dedup_agent.py -v`
Expected: FAIL — module not found.

**Step 3: Write minimal implementation**

Create `src/second_brain/agents/dream_dedup.py`:

```python
import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal

from second_brain.models import make_serializable, strip_embeddings
from second_brain.tools import dream_tools, recall_tools

logger = logging.getLogger(__name__)


@dataclass
class DedupDeps:
    db: AsyncSurreal  # pyright: ignore[reportGeneralTypeIssues]
    embed_fn: Callable[[str], Awaitable[list[float]]]
    cancel: asyncio.Event
    touched_ids: list[str] = field(default_factory=list)


def create_dedup_agent() -> Agent[DedupDeps, str]:
    agent = Agent(
        deps_type=DedupDeps,
        output_type=str,
        system_prompt=(
            "You are a knowledge graph deduplication agent. You process a batch of nodes "
            "and find duplicates that should be merged.\n\n"
            "For each node in the batch:\n"
            "1. Use find_similar to find semantically similar nodes.\n"
            "2. Examine the results — look at names, descriptions, content, and similarity scores.\n"
            "3. If you find true duplicates (same concept, different wording), merge them using "
            "merge_nodes. Provide a fused name/description/content that combines the best of both.\n"
            "4. If edges between the same pair of nodes have different labels that mean the same thing, "
            "use merge_edges to combine them.\n\n"
            "Be conservative: only merge when you are confident the nodes represent the same concept. "
            "Different versions or aspects of a concept are NOT duplicates.\n\n"
            "Return a summary of what you merged and what you left alone."
        ),
    )

    @agent.tool
    async def find_similar(ctx: RunContext[DedupDeps], record_id: str, k: int = 5) -> list[dict]:
        """Find the k most similar nodes to the given node (same table). Returns content + similarity score."""
        logger.info("dedup: find_similar id=%s k=%d", record_id, k)
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        results = await dream_tools.find_similar(ctx.deps.db, record_id, k)
        return results

    @agent.tool
    async def merge_nodes(
        ctx: RunContext[DedupDeps], ids: list[str], new_fields: dict
    ) -> dict:
        """Merge multiple nodes into one. First ID becomes the survivor.
        new_fields: the fused content — e.g. {"name": "...", "description": "..."} for entities,
        {"content": "...", "summary": "..."} for notes. Edges are automatically re-pointed and deduped."""
        logger.info("dedup: merge_nodes ids=%s", ids)
        result = await dream_tools.merge_nodes(
            ctx.deps.db, ids, new_fields, ctx.deps.embed_fn
        )
        ctx.deps.touched_ids.extend(result.get("touched_ids", []))
        return result

    @agent.tool
    async def merge_edges(
        ctx: RunContext[DedupDeps], ids: list[str], new_context: str | None = None
    ) -> dict:
        """Merge multiple edges between the same node pair into one.
        First ID becomes the survivor. Provide new_context if the label should be updated."""
        logger.info("dedup: merge_edges ids=%s", ids)
        result = await dream_tools.merge_edges(ctx.deps.db, ids, new_context)
        ctx.deps.touched_ids.extend(result.get("deleted_ids", []))
        if result.get("survivor"):
            sid = str(result["survivor"].get("id", ""))
            if sid and sid not in ctx.deps.touched_ids:
                ctx.deps.touched_ids.append(sid)
        return result

    @agent.tool
    async def get_node(ctx: RunContext[DedupDeps], record_id: str) -> dict:
        """Get a single node by ID for closer inspection."""
        logger.info("dedup: get_node id=%s", record_id)
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        node = await recall_tools.get_node(ctx.deps.db, record_id)
        if not node:
            return {"error": f"Node {record_id} not found"}
        return strip_embeddings(make_serializable(node))

    return agent
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dream_dedup_agent.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/second_brain/agents/dream_dedup.py tests/test_dream_dedup_agent.py
git commit -m "feat(agents): add dedup agent for dream pipeline"
```

---

### Task 9: Implement connect agent

**Files:**
- Create: `src/second_brain/agents/dream_connect.py`
- Create: `tests/test_dream_connect_agent.py`

**Step 1: Write the failing test**

Create `tests/test_dream_connect_agent.py`:

```python
import asyncio

import pytest
from pydantic_ai.models.test import TestModel
from unittest.mock import AsyncMock

from second_brain.db import init_schema, init_vector_indexes
from second_brain.agents.dream_connect import ConnectDeps, create_connect_agent


dummy_embed = AsyncMock(return_value=[0.5, 0.5, 0.0])


@pytest.fixture
async def connect_db(db):
    await init_schema(db)
    await init_vector_indexes(db, dimensions=3)
    await db.query("""
        CREATE entity:py SET name = 'Python', type = 'language', embedding = [0.9, 0.1, 0.0];
        CREATE entity:fa SET name = 'FastAPI', type = 'framework', embedding = [0.8, 0.2, 0.0];
        CREATE note:1 SET content = 'FastAPI uses Python', source = 'cli', embedding = [0.85, 0.15, 0.0];
        RELATE note:1->references->entity:py;
        RELATE note:1->references->entity:fa;
    """)
    return db


async def test_connect_agent_runs(connect_db):
    """Connect agent can run without crashing."""
    cancel = asyncio.Event()
    agent = create_connect_agent()
    deps = ConnectDeps(db=connect_db, embed_fn=dummy_embed, cancel=cancel)
    result = await agent.run(
        "Explore connections for these nodes: entity:py, entity:fa",
        deps=deps,
        model=TestModel(),
    )
    assert isinstance(result.output, str)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dream_connect_agent.py -v`
Expected: FAIL — module not found.

**Step 3: Write minimal implementation**

Create `src/second_brain/agents/dream_connect.py`:

```python
import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal

from second_brain.models import make_serializable, strip_embeddings
from second_brain.tools import dream_tools, ingest_tools, recall_tools

logger = logging.getLogger(__name__)


@dataclass
class ConnectDeps:
    db: AsyncSurreal  # pyright: ignore[reportGeneralTypeIssues]
    embed_fn: Callable[[str], Awaitable[list[float]]]
    cancel: asyncio.Event
    touched_ids: list[str] = field(default_factory=list)


def create_connect_agent() -> Agent[ConnectDeps, str]:
    agent = Agent(
        deps_type=ConnectDeps,
        output_type=str,
        system_prompt=(
            "You are a knowledge graph connection discovery agent. You explore the graph "
            "to find meaningful relationships that are missing.\n\n"
            "Strategy (in priority order):\n"
            "1. **Structural patterns first**: Use find_unlinked_cooccurrences to find entities "
            "that share notes but aren't directly connected. This is the highest-signal source "
            "of missing connections.\n"
            "2. **Graph exploration**: Use explore to traverse the neighborhood of each node. "
            "Look for entities reachable through intermediate nodes but not directly linked. "
            "Vary direction and node_types to discover different patterns.\n"
            "3. **Similarity fallback**: For nodes with very few connections, use find_similar "
            "to find semantically related but unconnected nodes.\n\n"
            "When you find a missing connection:\n"
            "- Read the actual content of both nodes (use get_node if needed)\n"
            "- Decide if a real, meaningful relationship exists\n"
            "- Choose a descriptive edge name (e.g., built_with, inspired_by, depends_on — "
            "NOT generic labels like relates_to or references)\n"
            "- Create the edge using create_edges\n\n"
            "Be judicious: only create edges for genuine relationships. Not every pair of "
            "co-occurring entities needs a direct link.\n\n"
            "Return a summary of connections discovered and created."
        ),
    )

    @agent.tool
    async def find_unlinked_cooccurrences(
        ctx: RunContext[ConnectDeps], record_id: str
    ) -> list[dict]:
        """Find entities that share notes with this entity but have no direct edge.
        Returns entities with their shared note IDs. High-signal source of missing connections."""
        logger.info("connect: find_unlinked_cooccurrences id=%s", record_id)
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        return await dream_tools.find_unlinked_cooccurrences(ctx.deps.db, record_id)

    @agent.tool
    async def explore(
        ctx: RunContext[ConnectDeps],
        record_id: str,
        direction: str = "both",
        node_types: list[str] | None = None,
        depth: int = 2,
    ) -> dict:
        """Explore the graph neighborhood from a node.
        direction: 'out', 'in', or 'both'.
        node_types: filter targets by table, e.g. ['entity'], ['note'], ['entity', 'note'].
        depth: max hops (1-3).
        Returns target nodes with paths showing how they were reached."""
        logger.info(
            "connect: explore id=%s dir=%s types=%s depth=%d",
            record_id, direction, node_types, depth,
        )
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        return await dream_tools.explore(ctx.deps.db, record_id, direction, node_types, depth)

    @agent.tool
    async def get_node(ctx: RunContext[ConnectDeps], record_id: str) -> dict:
        """Get a single node by ID for closer inspection."""
        logger.info("connect: get_node id=%s", record_id)
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        node = await recall_tools.get_node(ctx.deps.db, record_id)
        if not node:
            return {"error": f"Node {record_id} not found"}
        return strip_embeddings(make_serializable(node))

    @agent.tool
    async def find_similar(
        ctx: RunContext[ConnectDeps], record_id: str, k: int = 5
    ) -> list[dict]:
        """Find semantically similar nodes by embedding. Fallback for structurally isolated nodes."""
        logger.info("connect: find_similar id=%s k=%d", record_id, k)
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        return await dream_tools.find_similar(ctx.deps.db, record_id, k)

    @agent.tool
    async def create_edges(ctx: RunContext[ConnectDeps], edges: list[dict]) -> list[dict]:
        """Create relationship edges. Each dict needs 'from_id', 'edge_table', 'to_id', optional 'context'.
        Use descriptive edge names: built_with, inspired_by, depends_on, etc."""
        logger.info("connect: create_edges (%d edges)", len(edges))
        try:
            results = await ingest_tools.create_edges(ctx.deps.db, edges)
            for r in results:
                rid = str(r.get("id", ""))
                if rid and rid not in ctx.deps.touched_ids:
                    ctx.deps.touched_ids.append(rid)
            return [make_serializable(r) for r in results]
        except Exception as e:
            logger.error("connect: create_edges failed: %s", e)
            return [{"error": str(e)}]

    return agent
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dream_connect_agent.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/second_brain/agents/dream_connect.py tests/test_dream_connect_agent.py
git commit -m "feat(agents): add connect agent for dream pipeline"
```

---

### Task 10: Implement dream scheduler

**Files:**
- Create: `src/second_brain/scheduler.py`
- Create: `tests/test_scheduler.py`

**Step 1: Write the failing tests**

Create `tests/test_scheduler.py`:

```python
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from second_brain.db import init_schema, init_vector_indexes
from second_brain.scheduler import DreamScheduler


dummy_embed = AsyncMock(return_value=[0.5, 0.5, 0.0])


@pytest.fixture
async def scheduler_db(db):
    await init_schema(db)
    await init_vector_indexes(db, dimensions=3)
    return db


@pytest.fixture
def scheduler(scheduler_db):
    return DreamScheduler(
        db=scheduler_db,
        embed_fn=dummy_embed,
        model=MagicMock(),
        idle_timeout=0.1,  # 0.1 seconds for fast tests
        batch_size=10,
    )


async def test_scheduler_selects_lowest_dream_age_first(scheduler_db):
    await scheduler_db.query("""
        CREATE entity:old SET name = 'old', type = 'concept',
            embedding = [0.1, 0.2, 0.3], dream_age = 5;
        CREATE entity:new SET name = 'new', type = 'concept',
            embedding = [0.4, 0.5, 0.6], dream_age = 0;
        CREATE entity:mid SET name = 'mid', type = 'concept',
            embedding = [0.7, 0.8, 0.9], dream_age = 2;
    """)
    sched = DreamScheduler(
        db=scheduler_db, embed_fn=dummy_embed, model=MagicMock(),
        idle_timeout=10, batch_size=10,
    )
    batch = await sched._select_batch()
    ids = [str(n["id"]) for n in batch]
    # Should be sorted: dream_age 0 first, then 2, then 5
    assert "new" in ids[0]
    assert "mid" in ids[1]
    assert "old" in ids[2]


async def test_scheduler_respects_batch_size(scheduler_db):
    for i in range(20):
        await scheduler_db.query(
            f"CREATE entity:e{i} SET name = 'e{i}', type = 'test', embedding = [0.1, 0.2, 0.3], dream_age = 0"
        )
    sched = DreamScheduler(
        db=scheduler_db, embed_fn=dummy_embed, model=MagicMock(),
        idle_timeout=10, batch_size=5,
    )
    batch = await sched._select_batch()
    assert len(batch) == 5


async def test_scheduler_touch_activity_resets_idle(scheduler):
    scheduler.touch_activity()
    assert not scheduler._is_idle()


async def test_scheduler_increments_dream_age(scheduler_db):
    await scheduler_db.query("""
        CREATE entity:a SET name = 'A', type = 'concept',
            embedding = [0.1, 0.2, 0.3], dream_age = 0;
    """)
    sched = DreamScheduler(
        db=scheduler_db, embed_fn=dummy_embed, model=MagicMock(),
        idle_timeout=10, batch_size=10,
    )
    await sched._increment_dream_age(["entity:a"])
    result = (await scheduler_db.query("SELECT dream_age FROM entity:a"))[0]
    assert result["dream_age"] == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: FAIL — module not found.

**Step 3: Write minimal implementation**

Create `src/second_brain/scheduler.py`:

```python
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from surrealdb import AsyncSurreal, RecordID

from second_brain.models import make_serializable, strip_embeddings

logger = logging.getLogger(__name__)


def _to_str(val) -> str:
    if isinstance(val, RecordID):
        return f"{val.table_name}:{val.id}"
    return str(val)


class DreamScheduler:
    def __init__(
        self,
        db: AsyncSurreal,
        embed_fn: Callable[[str], Awaitable[list[float]]],
        model: Any,
        idle_timeout: float = 600,  # seconds
        batch_size: int = 10,
    ):
        self.db = db
        self.embed_fn = embed_fn
        self.model = model
        self.idle_timeout = idle_timeout
        self.batch_size = batch_size
        self._last_activity: float = time.monotonic()
        self._cancel = asyncio.Event()
        self._task: asyncio.Task | None = None

    def touch_activity(self) -> None:
        """Record that user activity (ingest/recall) occurred. Wakes up dreaming."""
        self._last_activity = time.monotonic()
        self._cancel.set()

    def _is_idle(self) -> bool:
        return (time.monotonic() - self._last_activity) >= self.idle_timeout

    async def _select_batch(self) -> list[dict]:
        """Select nodes with lowest dream_age, breaking ties by newest created_at."""
        nodes = []
        for table in ("entity", "note"):
            result = await self.db.query(
                f"SELECT * FROM {table} ORDER BY dream_age ASC, created_at DESC LIMIT {self.batch_size}"
            )
            if isinstance(result, list):
                nodes.extend(result)

        # Sort combined results by dream_age ASC, then by created_at DESC if present
        nodes.sort(key=lambda n: (n.get("dream_age", 0), -(n.get("created_at", 0).__hash__() if n.get("created_at") else 0)))
        return nodes[: self.batch_size]

    async def _increment_dream_age(self, record_ids: list[str]) -> None:
        """Increment dream_age by 1 on all given record IDs."""
        for rid in record_ids:
            await self.db.query(f"UPDATE {rid} SET dream_age = dream_age + 1")

    async def _run_cycle(self) -> None:
        """Run one dream cycle: dedup then connect."""
        from second_brain.agents.dream_dedup import DedupDeps, create_dedup_agent
        from second_brain.agents.dream_connect import ConnectDeps, create_connect_agent

        self._cancel.clear()

        batch = await self._select_batch()
        if not batch:
            logger.info("dream: no nodes to process, skipping cycle")
            return

        batch_ids = [_to_str(n["id"]) for n in batch]
        logger.info("dream: starting cycle with %d nodes", len(batch_ids))

        # Phase 1: Dedup
        if self._cancel.is_set():
            logger.info("dream: woke up before dedup phase")
            return

        dedup_agent = create_dedup_agent()
        dedup_deps = DedupDeps(
            db=self.db, embed_fn=self.embed_fn, cancel=self._cancel
        )
        prompt = f"Process this batch of nodes for deduplication: {', '.join(batch_ids)}"
        try:
            await dedup_agent.run(prompt, deps=dedup_deps, model=self.model)
        except Exception:
            logger.exception("dream: dedup agent failed")
            return

        # Result set = everything dedup touched (minus deleted nodes which are gone)
        result_set_ids = list(set(dedup_deps.touched_ids))
        # Add batch IDs that weren't touched by dedup
        for bid in batch_ids:
            if bid not in result_set_ids:
                result_set_ids.append(bid)

        logger.info("dream: dedup complete, result set has %d IDs", len(result_set_ids))

        # Phase 2: Connect
        if self._cancel.is_set():
            logger.info("dream: woke up before connect phase")
            # Still increment dream_age on what was processed
            await self._increment_dream_age(result_set_ids)
            return

        connect_agent = create_connect_agent()
        connect_deps = ConnectDeps(
            db=self.db, embed_fn=self.embed_fn, cancel=self._cancel
        )
        prompt = f"Explore connections for these nodes: {', '.join(result_set_ids)}"
        try:
            await connect_agent.run(prompt, deps=connect_deps, model=self.model)
        except Exception:
            logger.exception("dream: connect agent failed")

        # Final: increment dream_age on the full result set
        # Include anything connect touched too
        final_ids = list(set(result_set_ids + connect_deps.touched_ids))
        await self._increment_dream_age(final_ids)
        logger.info("dream: cycle complete, incremented dream_age on %d records", len(final_ids))

    async def run_forever(self) -> None:
        """Main loop: wait for idle, run dream cycle, repeat."""
        logger.info("dream: scheduler started (idle_timeout=%.0fs, batch_size=%d)",
                     self.idle_timeout, self.batch_size)
        while True:
            # Wait until idle
            while not self._is_idle():
                await asyncio.sleep(1)

            # Check cancel wasn't set while we were checking
            if self._cancel.is_set():
                self._cancel.clear()
                continue

            logger.info("dream: server idle, starting dream cycle")
            await self._run_cycle()

    def start(self) -> None:
        """Start the scheduler as a background asyncio task."""
        self._task = asyncio.create_task(self.run_forever())
        logger.info("dream: background task started")

    def stop(self) -> None:
        """Cancel the background task."""
        if self._task:
            self._task.cancel()
            self._task = None
            logger.info("dream: background task stopped")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/second_brain/scheduler.py tests/test_scheduler.py
git commit -m "feat: add dream scheduler with idle detection and batch processing"
```

---

### Task 11: Wire scheduler into FastAPI lifespan

**Files:**
- Modify: `src/second_brain/app.py`
- Modify: `tests/test_app.py`

**Step 1: Write the failing test**

Add to `tests/test_app.py`:

```python
async def test_dream_scheduler_not_started_in_test_mode():
    """In test mode, the dream scheduler should not be running."""
    from second_brain.app import _scheduler
    # In test mode, scheduler should be None
    assert _scheduler is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_app.py::test_dream_scheduler_not_started_in_test_mode -v`
Expected: FAIL — `_scheduler` not defined.

**Step 3: Write minimal implementation**

Modify `src/second_brain/app.py`:

1. Add import at top:
```python
from second_brain.scheduler import DreamScheduler
```

2. Add module-level variable:
```python
_scheduler: DreamScheduler | None = None
```

3. In the `lifespan` function, after `logger.info("Database schema initialized")` and before `yield`, add scheduler startup for non-test mode:
```python
if not settings.test_mode and settings.dream_enabled:
    _scheduler = DreamScheduler(
        db=_db,
        embed_fn=_embed,
        model=_model,
        idle_timeout=settings.dream_idle_timeout * 60,  # convert minutes to seconds
        batch_size=settings.dream_batch_size,
    )
    _scheduler.start()
    logger.info("Dream scheduler started")
```

4. In the `lifespan` cleanup (after `yield`), before closing DB:
```python
if _scheduler:
    _scheduler.stop()
    _scheduler = None
```

5. In the `ingest` endpoint, add activity tracking:
```python
if _scheduler:
    _scheduler.touch_activity()
```

6. In the `recall` endpoint, add activity tracking:
```python
if _scheduler:
    _scheduler.touch_activity()
```

7. In the `converse` endpoint, add activity tracking (since it delegates to ingest/recall):
```python
if _scheduler:
    _scheduler.touch_activity()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_app.py::test_dream_scheduler_not_started_in_test_mode -v`
Expected: PASS

**Step 5: Run all tests**

Run: `uv run pytest -v`
Expected: All pass.

**Step 6: Commit**

```bash
git add src/second_brain/app.py tests/test_app.py
git commit -m "feat(app): wire dream scheduler into FastAPI lifespan with activity tracking"
```

---

### Task 12: Run full check suite and fix any issues

**Step 1: Run all Python checks**

Run: `make check`
Expected: lint + typecheck + tests all pass.

**Step 2: Fix any issues found**

Address linting, type errors, or test failures.

**Step 3: Final commit**

```bash
git add -A
git commit -m "chore: fix lint/type issues from dreaming agent implementation"
```
