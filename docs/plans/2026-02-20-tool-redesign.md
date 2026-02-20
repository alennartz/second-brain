# Tool Redesign: Auto-Embed + Hybrid Search — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the pointless `embed` agent tool, auto-embed inside create operations, and replace separate FTS/vector search tools with a single hybrid search using SurrealDB's `search::rrf()`.

**Architecture:** Two changes at the tool layer: (1) `create_note`/`create_entity` call `embed_fn` internally so vectors never pass through the LLM, (2) a new `hybrid_search` function in `recall_tools.py` replaces `full_text_search` and `vector_search` with a single SurrealQL query using `search::rrf()`. Both agent wrappers (ingest + recall) and the converse agent are updated to match.

**Tech Stack:** Python, SurrealDB (`search::rrf()`, HNSW, BM25), PydanticAI, pytest

**Design doc:** `docs/plans/2026-02-19-tool-redesign-design.md`

---

### Task 1: Add `hybrid_search` to `recall_tools.py`

**Files:**
- Modify: `src/second_brain/tools/recall_tools.py`
- Modify: `tests/test_recall_tools.py`

**Step 1: Write the failing test**

Add to `tests/test_recall_tools.py`:

```python
from second_brain.embedding import init_vector_indexes
from second_brain.tools.recall_tools import hybrid_search


@pytest.fixture
async def hybrid_db(db):
    """DB with schema, vector indexes, and sample data for hybrid search."""
    await init_schema(db)
    await init_vector_indexes(db, dimensions=3)
    await db.query("""
        CREATE note:1 SET content = 'Spaced repetition improves long-term memory',
            summary = 'spaced repetition for memory', source = 'cli',
            embedding = [0.1, 0.2, 0.3];
        CREATE note:2 SET content = 'GTD is a productivity methodology',
            summary = 'GTD methodology', source = 'cli',
            embedding = [0.4, 0.5, 0.6];
        CREATE entity:sr SET name = 'spaced repetition', type = 'concept',
            embedding = [0.1, 0.2, 0.3];
        CREATE entity:gtd SET name = 'GTD', type = 'concept',
            embedding = [0.4, 0.5, 0.6];
    """)
    return db


async def test_hybrid_search_notes(hybrid_db):
    """hybrid_search combines BM25 + vector results via RRF."""
    results = await hybrid_search(
        hybrid_db, "note", "repetition", [0.1, 0.2, 0.3], k=5
    )
    assert len(results) >= 1
    # The spaced repetition note should rank highly (matches both keyword and vector)


async def test_hybrid_search_entities(hybrid_db):
    """hybrid_search works on the entity table."""
    results = await hybrid_search(
        hybrid_db, "entity", "spaced repetition", [0.1, 0.2, 0.3], k=5
    )
    assert len(results) >= 1


async def test_hybrid_search_no_results(hybrid_db):
    """hybrid_search returns empty list when nothing matches."""
    results = await hybrid_search(
        hybrid_db, "note", "xyznonexistent", [0.9, 0.9, 0.9], k=5
    )
    assert isinstance(results, list)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_recall_tools.py::test_hybrid_search_notes tests/test_recall_tools.py::test_hybrid_search_entities tests/test_recall_tools.py::test_hybrid_search_no_results -v`

Expected: `ImportError` — `hybrid_search` does not exist yet.

**Step 3: Implement `hybrid_search` in `recall_tools.py`**

Add to `src/second_brain/tools/recall_tools.py`:

```python
async def hybrid_search(
    db: AsyncSurreal,
    table: str,
    query_text: str,
    query_embedding: list[float],
    k: int = 5,
) -> list[dict]:
    """Hybrid BM25 + vector search fused with SurrealDB's search::rrf()."""
    field = "content" if table == "note" else "name"
    result = await db.query(
        f"LET $vs = SELECT id FROM {table} "
        f"WHERE embedding <|{k},100|> $vec; "
        f"LET $ft = SELECT id, search::score(1) AS score "
        f"FROM {table} WHERE {field} @1@ $query "
        f"ORDER BY score DESC LIMIT {k}; "
        f"RETURN search::rrf([$vs, $ft], {k});",
        {"vec": query_embedding, "query": query_text},
    )
    return result
```

Note: The SurrealQL `<|k,ef|>` operator is the HNSW nearest-neighbor syntax. `ef` is the search expansion factor (100 is a reasonable default). `search::rrf()` merges results by reciprocal rank fusion.

If `search::rrf()` returns nested structure, you may need to flatten. Test output and adjust. The raw result from `db.query()` on a multi-statement query returns a list — the last element is the `RETURN` result. You may need:

```python
    # db.query() returns list of statement results; last one is the RETURN
    if result and isinstance(result[-1], list):
        return result[-1]
    return result if isinstance(result, list) else []
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recall_tools.py::test_hybrid_search_notes tests/test_recall_tools.py::test_hybrid_search_entities tests/test_recall_tools.py::test_hybrid_search_no_results -v`

Expected: PASS. If `search::rrf()` isn't supported in the in-memory SurrealDB test backend, you'll need to investigate — try running the raw query in a test to see the error. Fallback: compose the RRF manually in Python using the two separate query results.

**Step 5: Remove `full_text_search` and `vector_search`**

Delete the `full_text_search` and `vector_search` functions from `src/second_brain/tools/recall_tools.py`.

Remove or replace their tests in `tests/test_recall_tools.py`:
- Delete `test_full_text_search`

Update imports in `tests/test_recall_tools.py` — remove `full_text_search` from the import block.

**Step 6: Run full recall_tools test suite**

Run: `uv run pytest tests/test_recall_tools.py -v`

Expected: All pass.

**Step 7: Commit**

```
git add src/second_brain/tools/recall_tools.py tests/test_recall_tools.py
git commit -m "feat: add hybrid_search with search::rrf(), remove separate FTS/vector"
```

---

### Task 2: Refactor ingest agent — auto-embed, remove `embed` tool

**Files:**
- Modify: `src/second_brain/agents/ingest.py`
- Modify: `tests/test_ingest_agent.py`

**Step 1: Update the tool-check test**

In `tests/test_ingest_agent.py`, update `test_ingest_agent_has_tools`:

```python
async def test_ingest_agent_has_tools():
    agent = create_ingest_agent()
    tool_names = set(agent._function_toolset.tools)
    assert "create_note" in tool_names
    assert "create_entity" in tool_names
    assert "create_edge" in tool_names
    assert "update_node" in tool_names
    assert "search_knowledge" in tool_names
    # embed tool should NOT exist
    assert "embed" not in tool_names
    # search_existing replaced by search_knowledge
    assert "search_existing" not in tool_names
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ingest_agent.py::test_ingest_agent_has_tools -v`

Expected: FAIL — `embed` still in tools, `search_knowledge` missing, `search_existing` still present.

**Step 3: Refactor `ingest.py`**

Replace the full body of `create_ingest_agent()` in `src/second_brain/agents/ingest.py`:

1. **Update system prompt** — remove "Use the embed tool to generate vectors for each new note and entity" and replace with noting that embedding happens automatically.

2. **`create_note` tool** — call `ctx.deps.embed_fn(content)` inside, pass embedding to `ingest_tools.create_note`:

```python
    @agent.tool
    async def create_note(
        ctx: RunContext[IngestDeps],
        content: str,
        source: str = "api",
        summary: str | None = None,
    ) -> dict:
        """Create a new note. Embedding is generated automatically."""
        try:
            embedding = await ctx.deps.embed_fn(content)
            result = await ingest_tools.create_note(
                ctx.deps.db,
                content=content,
                source=source,
                summary=summary,
                embedding=embedding,
            )
            return make_serializable(result)
        except Exception as e:
            return {"error": str(e)}
```

3. **`create_entity` tool** — embed description (fallback to name):

```python
    @agent.tool
    async def create_entity(
        ctx: RunContext[IngestDeps],
        name: str,
        type: str,
        description: str | None = None,
    ) -> dict:
        """Create a new entity (concept, person, project, tool, etc.). Embedding is generated automatically."""
        try:
            text_to_embed = description or name
            embedding = await ctx.deps.embed_fn(text_to_embed)
            result = await ingest_tools.create_entity(
                ctx.deps.db,
                name=name,
                type=type,
                description=description,
                embedding=embedding,
            )
            return make_serializable(result)
        except Exception as e:
            return {"error": str(e)}
```

4. **Replace `search_existing` with `search_knowledge`** — hybrid search:

```python
    @agent.tool
    async def search_knowledge(
        ctx: RunContext[IngestDeps], tables: list[str], query: str, k: int = 5
    ) -> list[dict]:
        """Search existing notes/entities using hybrid keyword + semantic search.
        tables: list containing 'note', 'entity', or both."""
        query_embedding = await ctx.deps.embed_fn(query)
        all_results = []
        for table in tables:
            results = await recall_tools.hybrid_search(
                ctx.deps.db, table, query, query_embedding, k
            )
            all_results.extend(results)
        return all_results
```

5. **Delete the `embed` tool** entirely (the `async def embed(...)` function at the bottom).

6. Add import for `recall_tools` (already imported at top of file).

**Step 4: Run tests**

Run: `uv run pytest tests/test_ingest_agent.py -v`

Expected: All pass.

**Step 5: Commit**

```
git add src/second_brain/agents/ingest.py tests/test_ingest_agent.py
git commit -m "feat: ingest auto-embeds on create, replace search_existing with hybrid search_knowledge"
```

---

### Task 3: Refactor recall agent — hybrid `search_knowledge`, add `embed_fn` to deps

**Files:**
- Modify: `src/second_brain/agents/recall.py`
- Modify: `tests/test_recall_agent.py`

**Step 1: Update the tool-check test**

In `tests/test_recall_agent.py`, update `test_recall_agent_has_tools`:

```python
async def test_recall_agent_has_tools():
    agent = create_recall_agent()
    tool_names = set(agent._function_toolset.tools)
    assert "search_knowledge" in tool_names
    assert "get_node" in tool_names
    assert "get_connections" in tool_names
    assert "graph_traverse" in tool_names
    # Old tools should NOT exist
    assert "full_text_search" not in tool_names
    assert "vector_search" not in tool_names
```

Update `recall_deps` fixture to include `embed_fn`:

```python
from unittest.mock import AsyncMock

@pytest.fixture
async def recall_deps(db):
    await init_schema(db)
    await db.query("""
        CREATE note:1 SET content = 'Spaced repetition improves memory',
            summary = 'spaced rep', source = 'cli';
        CREATE entity:sr SET name = 'spaced repetition', type = 'concept';
        RELATE note:1->references->entity:sr;
    """)
    return RecallDeps(db=db, embed_fn=AsyncMock(return_value=[0.1, 0.2, 0.3]))
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_recall_agent.py -v`

Expected: FAIL — `search_knowledge` not in tools, `RecallDeps` doesn't accept `embed_fn`.

**Step 3: Refactor `recall.py`**

1. **Add `embed_fn` to `RecallDeps`:**

```python
from collections.abc import Awaitable, Callable

@dataclass
class RecallDeps:
    db: AsyncSurreal
    embed_fn: Callable[[str], Awaitable[list[float]]]
```

2. **Replace `full_text_search` and `vector_search` tools with `search_knowledge`:**

```python
    @agent.tool
    async def search_knowledge(
        ctx: RunContext[RecallDeps], tables: list[str], query: str, k: int = 5
    ) -> list[dict]:
        """Search the knowledge base using hybrid keyword + semantic search.
        tables: list containing 'note', 'entity', or both."""
        query_embedding = await ctx.deps.embed_fn(query)
        all_results = []
        for table in tables:
            results = await recall_tools.hybrid_search(
                ctx.deps.db, table, query, query_embedding, k
            )
            all_results.extend(results)
        return all_results
```

3. **Delete** the `full_text_search` and `vector_search` tool functions.

4. **Update system prompt** — replace "Use search tools to find relevant notes and entities" with something like "Use search_knowledge to search for notes and entities by keyword and meaning."

**Step 4: Run tests**

Run: `uv run pytest tests/test_recall_agent.py -v`

Expected: All pass.

**Step 5: Commit**

```
git add src/second_brain/agents/recall.py tests/test_recall_agent.py
git commit -m "feat: recall uses hybrid search_knowledge, RecallDeps gains embed_fn"
```

---

### Task 4: Update converse agent and app.py

**Files:**
- Modify: `src/second_brain/agents/converse.py:53` — pass `embed_fn`
- Modify: `src/second_brain/app.py:114` — pass `embed_fn` to `RecallDeps`
- Modify: `tests/test_converse_agent.py` — no structural changes expected, but verify

**Step 1: Update `converse.py`**

In `src/second_brain/agents/converse.py`, line 53, change:

```python
            deps=RecallDeps(db=ctx.deps.db),
```

to:

```python
            deps=RecallDeps(db=ctx.deps.db, embed_fn=ctx.deps.embed_fn),
```

**Step 2: Update `app.py`**

In `src/second_brain/app.py`, in `run_recall_agent` (around line 114), change:

```python
        deps=RecallDeps(db=_db),
```

to:

```python
        deps=RecallDeps(db=_db, embed_fn=embed_text),
```

**Step 3: Run all tests**

Run: `uv run pytest -v`

Expected: All pass.

**Step 4: Run linting and type checking**

Run: `uv run ruff check src/ tests/ && uv run basedpyright src/`

Fix any issues.

**Step 5: Commit**

```
git add src/second_brain/agents/converse.py src/second_brain/app.py
git commit -m "feat: pass embed_fn to RecallDeps in converse agent and app"
```

---

### Task 5: Clean up dead code and run full verification

**Files:**
- Verify: `src/second_brain/tools/recall_tools.py` — no remaining references to deleted functions
- Verify: `src/second_brain/tools/ingest_tools.py` — unchanged, embedding param still accepted
- Verify: all imports across the codebase

**Step 1: Search for stale references**

Grep for `full_text_search`, `vector_search`, `search_existing`, and `embed` tool references across `src/` and `tests/`. Remove any dead imports or references.

The `ingest.py` `search_existing` usage in `search_knowledge` should use `recall_tools.hybrid_search` — verify.

**Step 2: Run full test suite**

Run: `uv run pytest -v`

Expected: All pass.

**Step 3: Run all pre-commit hooks**

Run: `uv run pre-commit run --all-files`

Fix any issues.

**Step 4: Commit any cleanup**

```
git add -A
git commit -m "chore: remove stale references to old search/embed tools"
```
