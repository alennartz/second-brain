# Tool Surface Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce LLM round trips by enriching node results with edge neighborhoods, converting to bulk creation tools, and removing redundant graph tools.

**Architecture:** Shared `enrich_with_connections` helper in `recall_tools.py` attaches edge neighborhoods to every node returned to the LLM. Bulk `create_notes/create_entities/create_edges` replace single-item variants. `get_connections` and `graph_traverse` are deleted — graph exploration now happens via `get_node` which always shows the neighborhood.

**Tech Stack:** Python, SurrealDB, PydanticAI, pytest-asyncio

---

### Task 1: Add `enrich_with_connections` to recall_tools.py

**Files:**
- Modify: `src/second_brain/tools/recall_tools.py`
- Test: `tests/test_recall_tools.py`

**Step 1: Write the failing test**

Add to `tests/test_recall_tools.py`:

```python
from second_brain.tools.recall_tools import enrich_with_connections

async def test_enrich_with_connections_outgoing(seeded_db):
    """enrich_with_connections attaches outgoing edges."""
    node = (await seeded_db.query("SELECT * FROM entity:sr"))[0]
    enriched = await enrich_with_connections(seeded_db, node)
    # entity:sr has an outgoing relates_to edge to entity:gtd
    assert "connections" in enriched
    out_conns = [c for c in enriched["connections"] if c["direction"] == "out"]
    assert len(out_conns) >= 1
    assert out_conns[0]["edge_label"] == "relates_to"
    assert "entity:gtd" in out_conns[0]["adjacent_id"]


async def test_enrich_with_connections_incoming(seeded_db):
    """enrich_with_connections attaches incoming edges."""
    node = (await seeded_db.query("SELECT * FROM entity:sr"))[0]
    enriched = await enrich_with_connections(seeded_db, node)
    # entity:sr has an incoming references edge from note:1
    in_conns = [c for c in enriched["connections"] if c["direction"] == "in"]
    assert len(in_conns) >= 1
    assert in_conns[0]["edge_label"] == "references"
    assert "note:1" in in_conns[0]["adjacent_id"]


async def test_enrich_with_connections_no_edges(seeded_db):
    """enrich_with_connections returns empty connections for isolated node."""
    await seeded_db.query("CREATE entity:lonely SET name = 'lonely', type = 'test'")
    node = (await seeded_db.query("SELECT * FROM entity:lonely"))[0]
    enriched = await enrich_with_connections(seeded_db, node)
    assert enriched["connections"] == []
```

Also update the import block at the top to add `enrich_with_connections`.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_recall_tools.py::test_enrich_with_connections_outgoing -v`
Expected: FAIL with `ImportError` (function doesn't exist yet)

**Step 3: Implement `enrich_with_connections`**

Add to `src/second_brain/tools/recall_tools.py` after the existing imports:

```python
from surrealdb import AsyncSurreal, RecordID


def _to_str(val) -> str:
    """Convert a RecordID or other value to a plain string like 'table:id'."""
    if isinstance(val, RecordID):
        return f"{val.table_name}:{val.id}"
    return str(val)


async def enrich_with_connections(db: AsyncSurreal, record: dict) -> dict:
    """Attach edge neighborhood summary to a node record.

    Each connection has: edge_label (edge table name), direction (in/out),
    and adjacent_id (the node on the other side).
    """
    rid = _to_str(record["id"])
    outgoing = await db.query(f"SELECT * FROM {rid}->?")
    incoming = await db.query(f"SELECT * FROM {rid}<-?")

    connections = []
    for edge in (outgoing if isinstance(outgoing, list) else []):
        connections.append({
            "edge_label": _to_str(edge["id"]).split(":")[0],
            "direction": "out",
            "adjacent_id": _to_str(edge["out"]),
        })
    for edge in (incoming if isinstance(incoming, list) else []):
        connections.append({
            "edge_label": _to_str(edge["id"]).split(":")[0],
            "direction": "in",
            "adjacent_id": _to_str(edge["in"]),
        })

    enriched = dict(record)
    enriched["connections"] = connections
    return enriched
```

Note: Update the existing import line from `from surrealdb import AsyncSurreal` to `from surrealdb import AsyncSurreal, RecordID`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recall_tools.py::test_enrich_with_connections_outgoing tests/test_recall_tools.py::test_enrich_with_connections_incoming tests/test_recall_tools.py::test_enrich_with_connections_no_edges -v`
Expected: 3 PASSED

**Step 5: Delete `get_connections` and `graph_traverse` from recall_tools.py**

Remove the `get_connections` function (lines 80-84) and `graph_traverse` function (lines 87-93) from `src/second_brain/tools/recall_tools.py`.

**Step 6: Delete their tests from test_recall_tools.py**

Remove `test_get_connections` and `test_graph_traverse` from `tests/test_recall_tools.py`. Also remove `get_connections` and `graph_traverse` from the import block.

**Step 7: Run all recall_tools tests**

Run: `uv run pytest tests/test_recall_tools.py -v`
Expected: All remaining tests PASS

**Step 8: Commit**

```bash
git add src/second_brain/tools/recall_tools.py tests/test_recall_tools.py
git commit -m "feat(recall_tools): add enrich_with_connections, remove get_connections/graph_traverse"
```

---

### Task 2: Convert ingest_tools.py to bulk APIs

**Files:**
- Modify: `src/second_brain/tools/ingest_tools.py`
- Modify: `tests/test_ingest_tools.py`

**Step 1: Write failing tests for bulk functions**

Replace the contents of `tests/test_ingest_tools.py` with:

```python
import pytest
from unittest.mock import AsyncMock

from second_brain.db import init_schema
from second_brain.tools.ingest_tools import (
    create_edges,
    create_entities,
    create_notes,
    update_node,
)


@pytest.fixture
async def schema_db(db):
    await init_schema(db)
    return db


dummy_embed = AsyncMock(return_value=[0.1, 0.2, 0.3])


async def test_create_notes_bulk(schema_db):
    notes = [
        {"content": "Note one", "source": "cli"},
        {"content": "Note two", "source": "api", "summary": "second note"},
    ]
    results = await create_notes(schema_db, notes, dummy_embed)
    assert len(results) == 2
    assert results[0]["content"] == "Note one"
    assert results[1]["content"] == "Note two"
    assert results[1]["summary"] == "second note"
    assert all("id" in r for r in results)


async def test_create_notes_default_source(schema_db):
    notes = [{"content": "No source specified"}]
    results = await create_notes(schema_db, notes, dummy_embed)
    assert results[0]["source"] == "api"


async def test_create_entities_bulk(schema_db):
    entities = [
        {"name": "Python", "type": "language"},
        {"name": "FastAPI", "type": "framework", "description": "Web framework for Python"},
    ]
    results = await create_entities(schema_db, entities, dummy_embed)
    assert len(results) == 2
    assert results[0]["name"] == "Python"
    assert results[1]["description"] == "Web framework for Python"
    assert all("id" in r for r in results)


async def test_create_edges_bulk(schema_db):
    await schema_db.query("""
        CREATE note:1 SET content = 'test', source = 'cli';
        CREATE entity:py SET name = 'Python', type = 'language';
        CREATE entity:fa SET name = 'FastAPI', type = 'framework';
    """)
    edges = [
        {"from_id": "note:1", "edge_table": "mentions", "to_id": "entity:py"},
        {"from_id": "entity:fa", "edge_table": "built_with", "to_id": "entity:py", "context": "FastAPI uses Python"},
    ]
    results = await create_edges(schema_db, edges)
    assert len(results) == 2
    assert all("id" in r for r in results)


async def test_update_node(schema_db):
    await schema_db.query("CREATE note:1 SET content = 'old', source = 'cli'")
    updated = await update_node(
        schema_db, record_id="note:1", fields={"summary": "new summary"}
    )
    assert updated["summary"] == "new summary"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ingest_tools.py -v`
Expected: FAIL with `ImportError` (new functions don't exist yet)

**Step 3: Implement bulk functions**

Replace `src/second_brain/tools/ingest_tools.py` with:

```python
# pyright: reportGeneralTypeIssues=false
# AsyncSurreal is typed as a factory function in the surrealdb SDK, not a class.
import logging
from collections.abc import Awaitable, Callable

from surrealdb import AsyncSurreal

logger = logging.getLogger(__name__)


async def create_notes(
    db: AsyncSurreal,
    notes: list[dict],
    embed_fn: Callable[[str], Awaitable[list[float]]],
) -> list[dict]:
    """Create multiple notes. Each dict needs 'content', optional 'source' and 'summary'."""
    results = []
    for note in notes:
        content = note["content"]
        source = note.get("source", "api")
        embedding = await embed_fn(content)
        data: dict = {"content": content, "source": source, "embedding": embedding}
        if note.get("summary"):
            data["summary"] = note["summary"]
        result = await db.create("note", data)
        rec = result if isinstance(result, dict) else result[0]
        logger.info("db: created note id=%s (%d chars)", rec.get("id"), len(content))
        results.append(rec)
    return results


async def create_entities(
    db: AsyncSurreal,
    entities: list[dict],
    embed_fn: Callable[[str], Awaitable[list[float]]],
) -> list[dict]:
    """Create multiple entities. Each dict needs 'name', 'type', optional 'description'."""
    results = []
    for entity in entities:
        name = entity["name"]
        etype = entity["type"]
        description = entity.get("description")
        text_to_embed = description or name
        embedding = await embed_fn(text_to_embed)
        data: dict = {"name": name, "type": etype, "embedding": embedding}
        if description:
            data["description"] = description
        result = await db.create("entity", data)
        rec = result if isinstance(result, dict) else result[0]
        logger.info("db: created entity id=%s name='%s' type=%s", rec.get("id"), name, etype)
        results.append(rec)
    return results


async def create_edges(
    db: AsyncSurreal,
    edges: list[dict],
) -> list[dict]:
    """Create multiple relationship edges. Each dict needs 'from_id', 'edge_table', 'to_id', optional 'context'."""
    results = []
    for edge in edges:
        from_id = edge["from_id"]
        edge_table = edge["edge_table"]
        to_id = edge["to_id"]
        context = edge.get("context")
        ctx_clause = " SET context = $context" if context else ""
        query = f"RELATE {from_id}->{edge_table}->{to_id}{ctx_clause}"
        result = await db.query(query, {"context": context} if context else None)
        rec = result[0] if result else {}
        logger.info("db: created edge %s -[%s]-> %s id=%s", from_id, edge_table, to_id, rec.get("id"))
        results.append(rec)
    return results


async def update_node(db: AsyncSurreal, record_id: str, fields: dict) -> dict:
    """Update fields on an existing node."""
    set_clauses = ", ".join(f"{k} = ${k}" for k in fields)
    result = await db.query(
        f"UPDATE {record_id} SET {set_clauses}, updated_at = time::now()",
        fields,
    )
    rec = result[0] if result else {}
    logger.info("db: updated node id=%s fields=%s", record_id, list(fields.keys()))
    return rec
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ingest_tools.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add src/second_brain/tools/ingest_tools.py tests/test_ingest_tools.py
git commit -m "feat(ingest_tools): convert to bulk create_notes/create_entities/create_edges"
```

---

### Task 3: Update recall agent

**Files:**
- Modify: `src/second_brain/agents/recall.py`
- Modify: `tests/test_recall_agent.py`

**Step 1: Update the test for new tool surface**

In `tests/test_recall_agent.py`, update `test_recall_agent_has_tools`:

```python
async def test_recall_agent_has_tools():
    agent = create_recall_agent()
    tool_names = set(agent._function_toolset.tools)
    assert "search_knowledge" in tool_names
    assert "get_node" in tool_names
    # Removed tools should NOT exist
    assert "get_connections" not in tool_names
    assert "graph_traverse" not in tool_names
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_recall_agent.py::test_recall_agent_has_tools -v`
Expected: FAIL (get_connections and graph_traverse still registered)

**Step 3: Update recall.py**

Replace `src/second_brain/agents/recall.py` with:

```python
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal

from second_brain.models import make_serializable, strip_embeddings
from second_brain.tools import recall_tools

logger = logging.getLogger(__name__)


class RecallOutput(BaseModel):
    answer: str
    cited_node_ids: list[str] = []
    cited_edge_ids: list[str] = []


@dataclass
class RecallDeps:
    db: AsyncSurreal  # pyright: ignore[reportGeneralTypeIssues] - SDK types AsyncSurreal as function
    embed_fn: Callable[[str], Awaitable[list[float]]]


def create_recall_agent() -> Agent[RecallDeps, RecallOutput]:
    """Create a recall agent with search and graph exploration tools.

    The agent is created without a default model so it can be used in tests
    with TestModel(). In production, pass ``settings.reasoning_model`` to
    ``agent.run(..., model=...)``, or override using
    ``PYDANTIC_AI_MODEL`` env var.
    """
    agent = Agent(
        deps_type=RecallDeps,
        output_type=RecallOutput,
        system_prompt=(
            "You are a personal knowledge recall agent. The user asks questions and you "
            "explore their knowledge base using the tools available to you. "
            "Use search_knowledge to search notes and entities by keyword and meaning. "
            "Each result includes its connections — edges with labels, directions, and "
            "adjacent node IDs. Use get_node to follow interesting connections and explore "
            "the graph selectively. "
            "Keep exploring until you have enough context to give a thorough answer. "
            "If you find nothing relevant, say so honestly.\n\n"
            "IMPORTANT: In your response, include the IDs of all nodes and edges you "
            "referenced in your answer in the cited_node_ids and cited_edge_ids fields."
        ),
    )

    @agent.tool
    async def search_knowledge(
        ctx: RunContext[RecallDeps], tables: list[str], query: str, k: int = 5
    ) -> list[dict]:
        """Search the knowledge base using hybrid keyword + semantic search.
        tables: list containing 'note', 'entity', or both.
        Results include a 'connections' list showing edges with labels and adjacent node IDs."""
        logger.info(
            "recall: search_knowledge tables=%s query='%.80s' k=%d", tables, query, k
        )
        try:
            query_embedding = await ctx.deps.embed_fn(query)
            all_results: list[dict] = []
            for table in tables:
                results = await recall_tools.hybrid_search(
                    ctx.deps.db, table, query, query_embedding, k
                )
                all_results.extend(results)
            enriched = []
            for r in all_results:
                e = await recall_tools.enrich_with_connections(ctx.deps.db, r)
                enriched.append(strip_embeddings(make_serializable(e)))
            logger.info("recall: search_knowledge → %d results", len(enriched))
            return enriched
        except Exception as e:
            logger.error("recall: search_knowledge failed: %s", e)
            return [{"error": str(e)}]

    @agent.tool
    async def get_node(ctx: RunContext[RecallDeps], record_id: str) -> dict:
        """Get a single node by ID, e.g. 'note:abc123' or 'entity:sr'.
        Result includes a 'connections' list showing edges with labels and adjacent node IDs."""
        logger.info("recall: get_node id=%s", record_id)
        node = await recall_tools.get_node(ctx.deps.db, record_id)
        if not node:
            return {"error": f"Node {record_id} not found"}
        enriched = await recall_tools.enrich_with_connections(ctx.deps.db, node)
        return strip_embeddings(make_serializable(enriched))

    return agent
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recall_agent.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/second_brain/agents/recall.py tests/test_recall_agent.py
git commit -m "feat(recall): enrich results with connections, remove get_connections/graph_traverse"
```

---

### Task 4: Update ingest agent

**Files:**
- Modify: `src/second_brain/agents/ingest.py`

**Step 1: Replace ingest.py with bulk tools + get_node**

Replace `src/second_brain/agents/ingest.py` with:

```python
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal

from second_brain.models import make_serializable, strip_embeddings
from second_brain.tools import ingest_tools, recall_tools

logger = logging.getLogger(__name__)


@dataclass
class IngestDeps:
    db: AsyncSurreal  # pyright: ignore[reportGeneralTypeIssues] - SDK types AsyncSurreal as function
    embed_fn: Callable[[str], Awaitable[list[float]]]


def create_ingest_agent() -> Agent[IngestDeps, str]:
    """Create an ingest agent with bulk write tools and knowledge search.

    The agent is created without a default model so it can be used in tests
    with TestModel(). In production, pass ``settings.reasoning_model`` to
    ``agent.run(..., model=...)``, or override using
    ``PYDANTIC_AI_MODEL`` env var.
    """
    agent = Agent(
        deps_type=IngestDeps,
        output_type=str,
        system_prompt=(
            "You are a personal knowledge ingest agent. The user provides raw input — notes, "
            "ideas, rambling thoughts — and you process them into structured knowledge.\n\n"
            "Your job:\n"
            "1. Parse the input into discrete ideas. One note per distinct idea.\n"
            "2. Extract entities (people, projects, concepts, tools) mentioned.\n"
            "3. **Deduplicate entities**: Before creating any entity, ALWAYS search the existing "
            "knowledge base first. If a matching entity already exists (same name or clearly the "
            "same concept), DO NOT create a duplicate — use the existing entity's ID when creating "
            "edges. Only create a new entity when it is genuinely absent from the knowledge base.\n"
            "4. Create notes and edges. When connecting nodes, choose a descriptive, semantically "
            "meaningful edge name that captures the nature of the relationship. Do NOT use generic "
            "labels — the edge name should read naturally and convey specific meaning.\n"
            "   Good edge names: authored_by, inspired_by, depends_on, contradicts, builds_upon, "
            "implements, learned_from, part_of, used_in, motivated_by, blocked_by, evolved_into, "
            "critiques, supports, exemplifies.\n"
            "   Bad edge names: references, relates_to, linked_to, associated_with.\n"
            "   Embeddings are generated automatically when you create notes and entities.\n"
            "5. Surface any interesting connections you found to existing knowledge.\n\n"
            "Return a summary of what you stored and any connections you discovered."
        ),
    )

    @agent.tool
    async def search_knowledge(
        ctx: RunContext[IngestDeps], tables: list[str], query: str, k: int = 5
    ) -> list[dict]:
        """Search existing notes/entities using hybrid keyword + semantic search.
        tables: list containing 'note', 'entity', or both.
        Results include a 'connections' list showing edges with labels and adjacent node IDs."""
        logger.info(
            "ingest: search_knowledge tables=%s query='%.80s' k=%d", tables, query, k
        )
        try:
            query_embedding = await ctx.deps.embed_fn(query)
            all_results: list[dict] = []
            for table in tables:
                results = await recall_tools.hybrid_search(
                    ctx.deps.db, table, query, query_embedding, k
                )
                all_results.extend(results)
            enriched = []
            for r in all_results:
                e = await recall_tools.enrich_with_connections(ctx.deps.db, r)
                enriched.append(strip_embeddings(make_serializable(e)))
            logger.info("ingest: search_knowledge → %d results", len(enriched))
            return enriched
        except Exception as e:
            logger.error("ingest: search_knowledge failed: %s", e)
            return [{"error": str(e)}]

    @agent.tool
    async def get_node(ctx: RunContext[IngestDeps], record_id: str) -> dict:
        """Get a single node by ID, e.g. 'note:abc123' or 'entity:sr'.
        Result includes a 'connections' list showing edges with labels and adjacent node IDs."""
        logger.info("ingest: get_node id=%s", record_id)
        node = await recall_tools.get_node(ctx.deps.db, record_id)
        if not node:
            return {"error": f"Node {record_id} not found"}
        enriched = await recall_tools.enrich_with_connections(ctx.deps.db, node)
        return strip_embeddings(make_serializable(enriched))

    @agent.tool
    async def create_notes(
        ctx: RunContext[IngestDeps],
        notes: list[dict],
    ) -> list[dict]:
        """Create multiple notes in bulk. Each dict needs 'content', optional 'source' (default 'api') and 'summary'.
        Embeddings are generated automatically."""
        logger.info("ingest: create_notes (%d notes)", len(notes))
        try:
            results = await ingest_tools.create_notes(
                ctx.deps.db, notes, ctx.deps.embed_fn
            )
            return [strip_embeddings(make_serializable(r)) for r in results]
        except Exception as e:
            logger.error("ingest: create_notes failed: %s", e)
            return [{"error": str(e)}]

    @agent.tool
    async def create_entities(
        ctx: RunContext[IngestDeps],
        entities: list[dict],
    ) -> list[dict]:
        """Create multiple entities in bulk. Each dict needs 'name', 'type', optional 'description'.
        Embeddings are generated automatically."""
        logger.info("ingest: create_entities (%d entities)", len(entities))
        try:
            results = await ingest_tools.create_entities(
                ctx.deps.db, entities, ctx.deps.embed_fn
            )
            return [strip_embeddings(make_serializable(r)) for r in results]
        except Exception as e:
            logger.error("ingest: create_entities failed: %s", e)
            return [{"error": str(e)}]

    @agent.tool
    async def create_edges(
        ctx: RunContext[IngestDeps],
        edges: list[dict],
    ) -> list[dict]:
        """Create multiple relationship edges in bulk. Each dict needs 'from_id', 'edge_table', 'to_id', optional 'context'.
        edge_table should be a descriptive, semantically meaningful name (e.g. authored_by, inspired_by, depends_on, part_of, builds_upon)."""
        logger.info("ingest: create_edges (%d edges)", len(edges))
        try:
            results = await ingest_tools.create_edges(ctx.deps.db, edges)
            return [make_serializable(r) for r in results]
        except Exception as e:
            logger.error("ingest: create_edges failed: %s", e)
            return [{"error": str(e)}]

    @agent.tool
    async def update_node(
        ctx: RunContext[IngestDeps], record_id: str, fields: dict
    ) -> dict:
        """Update fields on an existing note or entity."""
        logger.info(
            "ingest: update_node id=%s fields=%s", record_id, list(fields.keys())
        )
        try:
            result = await ingest_tools.update_node(
                ctx.deps.db, record_id=record_id, fields=fields
            )
            return make_serializable(result)
        except Exception as e:
            logger.error("ingest: update_node failed: %s", e)
            return {"error": str(e)}

    return agent
```

**Step 2: Run tests**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS (no ingest agent test file exists yet — tool-level tests already updated in Task 2)

**Step 3: Commit**

```bash
git add src/second_brain/agents/ingest.py
git commit -m "feat(ingest): bulk create tools, add get_node, enrich search results"
```

---

### Task 5: Update app.py graph endpoint

**Files:**
- Modify: `src/second_brain/app.py`
- Modify: `tests/test_app.py`

**Step 1: Update the graph endpoint test**

In `tests/test_app.py`, replace `test_graph_endpoint`:

```python
async def test_graph_endpoint(client):
    with patch("second_brain.app.get_node", new_callable=AsyncMock) as mock_node:
        mock_node.side_effect = [
            {"id": "note:1", "content": "test note", "source": "api"},  # main node
            {"id": "entity:sr", "name": "spaced rep", "type": "concept"},  # other node
        ]
        with patch("second_brain.app._get_raw_connections", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = [
                {"id": "references:abc", "in": "entity:sr", "out": "note:1"},
            ]
            resp = await client.get("/graph/note:1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["node"]["id"] == "note:1"
    assert len(data["connections"]) == 1
    assert data["connections"][0]["node"]["id"] == "entity:sr"
```

Also update `test_graph_endpoint_no_connections`:

```python
async def test_graph_endpoint_no_connections(client):
    with patch("second_brain.app.get_node", new_callable=AsyncMock) as mock_node:
        mock_node.return_value = {"id": "note:1", "content": "lonely node"}
        with patch("second_brain.app._get_raw_connections", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = []
            resp = await client.get("/graph/note:1")
    assert resp.status_code == 200
    assert resp.json()["connections"] == []
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_app.py::test_graph_endpoint -v`
Expected: FAIL (`_get_raw_connections` doesn't exist yet)

**Step 3: Update app.py**

In `src/second_brain/app.py`:

1. Change the import line from:
   ```python
   from second_brain.tools.recall_tools import get_connections, get_node
   ```
   to:
   ```python
   from second_brain.tools.recall_tools import get_node
   ```

2. Add a helper function after the `_dummy_embed` function:
   ```python
   async def _get_raw_connections(db, record_id: str) -> list[dict]:
       """Get all edge records connected to a node (both directions)."""
       outgoing = await db.query(f"SELECT * FROM {record_id}->?")
       incoming = await db.query(f"SELECT * FROM {record_id}<-?")
       out = outgoing if isinstance(outgoing, list) else []
       inc = incoming if isinstance(incoming, list) else []
       return out + inc
   ```

3. In the `get_graph` endpoint, replace:
   ```python
   raw_edges = await get_connections(_db, record_id)
   ```
   with:
   ```python
   raw_edges = await _get_raw_connections(_db, record_id)
   ```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_app.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/second_brain/app.py tests/test_app.py
git commit -m "fix(app): replace deleted get_connections with inline edge query"
```

---

### Task 6: Full test suite + lint

**Step 1: Run all Python tests**

Run: `uv run pytest tests/ -v`
Expected: All PASS

**Step 2: Run lint and typecheck**

Run: `make check`
Expected: All checks pass

**Step 3: Fix any issues found by lint/typecheck**

If any issues, fix them and re-run.

**Step 4: Commit any fixes**

```bash
git add -u
git commit -m "fix: address lint/typecheck issues from tool surface redesign"
```

---

### Task 7: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update the architecture section**

In `CLAUDE.md`, update the Key modules section:

- **`tools/ingest_tools.py`** — change description to: DB write operations: `create_notes` (bulk), `create_entities` (bulk), `create_edges` (bulk), `update_node`.
- **`tools/recall_tools.py`** — change description to: DB read operations: `hybrid_search` (BM25 + vector with RRF fusion), `get_node`, `enrich_with_connections` (attaches edge neighborhood to node results), `fetch_records_by_ids`.
- **`agents/ingest.py`** — update Tools list to: `search_knowledge`, `get_node`, `create_notes`, `create_entities`, `create_edges`, `update_node`.
- **`agents/recall.py`** — update Tools list to: `search_knowledge`, `get_node`. Remove mention of `get_connections` and `graph_traverse`.

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for new tool surface"
```
