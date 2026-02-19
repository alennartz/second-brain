# Tool Redesign: Auto-Embed + Hybrid Search

## Problem

Two design flaws in the agent tool layer:

1. **Ingest `embed` tool is wasteful.** The LLM calls `embed(text)` to get a 1536-float
   vector, then passes that vector back to `create_note(..., embedding=vec)`. This shuttles
   raw vectors through LLM context for no reason. Embedding is a deterministic programmatic
   operation that should happen automatically inside create operations.

2. **Recall search is split when it should be hybrid.** `full_text_search` and
   `vector_search` are separate tools, but the whole point of choosing SurrealDB was its
   native hybrid search support (`search::rrf()`). The recall agent can't even use vector
   search properly since it has no way to produce query embeddings.

## Design

### Ingest Agent

**Remove** the `embed` tool entirely.

**`create_note`** auto-embeds: calls `embed_fn(content)` internally before storing.

**`create_entity`** auto-embeds: calls `embed_fn(description)` if description is provided,
otherwise `embed_fn(name)`.

**`search_existing`** becomes **`search_knowledge`**: uses the same hybrid search as recall
(BM25 + vector via `search::rrf()`).

**System prompt** updated to remove references to the embed tool. Notes that embedding
happens automatically.

**`IngestDeps`** unchanged (already has `embed_fn`).

### Recall Agent

**Remove** `full_text_search` and `vector_search` as separate agent tools.

**Add `search_knowledge`**: single tool that accepts a natural language query string and a
list of tables (`["note"]`, `["entity"]`, or `["note", "entity"]`). Internally:
1. Embeds the query text via `embed_fn`
2. Runs a SurrealQL query per table: BM25 FTS + HNSW vector search fused with `search::rrf()`
3. When multiple tables are specified, merges results across tables

**`RecallDeps`** gains `embed_fn: Callable[[str], Awaitable[list[float]]]`.

**Keep unchanged**: `get_node`, `get_connections`, `graph_traverse` (graph exploration tools).

### Implementation Layer (`recall_tools.py`)

New `hybrid_search()` function using SurrealDB's native `search::rrf()`:

```python
async def hybrid_search(
    db, table: str, query_text: str, query_embedding: list[float], k: int = 5
) -> list[dict]:
    field = "content" if table == "note" else "name"
    result = await db.query(
        f"""
        LET $vs = SELECT id FROM {table}
            WHERE embedding <|{k},100|> $vec;
        LET $ft = SELECT id, search::score(1) AS score
            FROM {table} WHERE {field} @1@ $query
            ORDER BY score DESC LIMIT {k};
        RETURN search::rrf([$vs, $ft], {k});
        """,
        {"vec": query_embedding, "query": query_text},
    )
    return result
```

Remove `vector_search()` and `full_text_search()` as public API (or keep as internal
utilities if needed for testing).

### Converse Agent

`converse.py` line 53 creates `RecallDeps(db=ctx.deps.db)` — must also pass
`embed_fn=ctx.deps.embed_fn`.

### `app.py`

`run_recall_agent` must pass `embed_fn=embed_text` to `RecallDeps`.

### Embedding Layer

No changes to `embedding.py`.

### Database Schema

No changes to `db.py`. Existing BM25 and HNSW indexes are already defined.

## Files Changed

| File | Change |
|---|---|
| `tools/recall_tools.py` | Add `hybrid_search()`. Remove `vector_search()`, `full_text_search()`. |
| `agents/ingest.py` | Remove `embed` tool. Auto-embed in `create_note`/`create_entity`. `search_existing` -> `search_knowledge` (hybrid). Update system prompt. |
| `agents/recall.py` | Replace `full_text_search`/`vector_search` with `search_knowledge` (hybrid). `RecallDeps` gains `embed_fn`. |
| `agents/converse.py` | Pass `embed_fn` when constructing `RecallDeps`. |
| `app.py` | Pass `embed_fn=embed_text` to `RecallDeps`. |
| `tests/test_recall_tools.py` | Remove FTS/vector-only tests. Add `hybrid_search` test. |
| Agent tests | Update to reflect new tool surface. |

## Decisions

- **Fusion method**: `search::rrf()` (reciprocal rank fusion). Simple, no weights to tune.
- **Entity embedding**: embed description when available, fall back to name.
- **Query embedding**: done inside the tool. LLM passes text, tool handles embedding.
- **Table selection**: LLM specifies a list of tables. Can pass one or both.
