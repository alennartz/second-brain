# Plan: DB Storage Layer Abstraction

## Context

Consolidate all raw SurrealQL queries into `db.py` behind a domain-level `Storage` class. Callers work with graph concepts (nodes, edges, search, traversal) without coupling to SurrealDB SDK types or query syntax. See [brainstorm](../brainstorms/db-storage-layer.md).

## Architecture

### Impacted Modules

**Core** — `db.py` expands from schema-only to the full storage layer. `validation.py` loses `check_query_result` (moves into `db.py` as a private helper). All other Core files unchanged.

**Tools** — All three tool files drop `AsyncSurreal` imports and raw SurrealQL. Functions switch from `(db, embed_fn, ...)` signatures to `(storage, ...)`. Primitive DB operations (`create_notes`, `create_entities`, `create_edges`, `get_node`, `fetch_records_by_ids`, `hybrid_search`, `enrich_with_connections`, `update_node`) move into Storage. Tool files keep only business logic that composes Storage primitives: `store_knowledge` (reference resolution), `find_similar`, `merge_nodes`, `explore`, `find_unlinked_cooccurrences`, `merge_edges`.

**Agents** — Scheduler replaces `self.db: AsyncSurreal` + `self.embed_fn` with `self.storage: Storage`. Its `_count_nodes`, `_select_batch`, and `_increment_dream_age` methods delegate to Storage primitives instead of raw queries. Every agent Deps dataclass replaces `db: AsyncSurreal` + `embed_fn: Callable[...]` with `storage: Storage`. No other changes to agent logic or prompts.

**API** — `app.py` constructs `Storage` at startup instead of passing raw `AsyncSurreal`. Injects it into all Deps and the scheduler. `conftest.py` constructs `Storage` with `mem://` + dummy embedder.

### Interfaces

#### Embedder Protocol

```python
class Embedder(Protocol):
    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
```

Injected into `Storage` at construction. Replaces the `BatchEmbedder` protocol in `ingest_tools.py` and the bare `Callable[[str], Awaitable[list[float]]]` signatures used everywhere else. Existing embed functions must conform to this protocol (or be wrapped).

#### Storage Class

```python
class Storage:
    def __init__(self, url: str, embedder: Embedder, dimensions: int) -> None:
        """Wraps a DB connection. url is 'mem://' for tests, 'surrealkv://path' for prod."""
        ...

    async def init(self) -> None:
        """Connect, set namespace, create schema + vector indexes. Call once at startup."""
        ...

    async def close(self) -> None:
        """Close the underlying connection."""
        ...

    # ── Nodes ──

    async def get_node(self, record_id: str) -> dict:
        """Fetch a single node by record ID. Returns {} if not found. Excludes embeddings."""
        ...

    async def get_nodes(self, record_ids: list[str]) -> list[dict]:
        """Fetch multiple nodes by ID. Excludes embeddings. Skips missing."""
        ...

    async def create_note(self, content: str, source: str = "api", summary: str | None = None) -> dict:
        """Create a note, auto-embedding content. Returns the created record."""
        ...

    async def create_notes(self, notes: list[dict]) -> list[dict]:
        """Bulk create notes. Each dict: {content, source?, summary?}. Auto-embeds."""
        ...

    async def create_entity(self, name: str, type: str, description: str | None = None) -> dict:
        """Create an entity, auto-embedding description (or name). Returns the created record."""
        ...

    async def create_entities(self, entities: list[dict]) -> list[dict]:
        """Bulk create entities. Each dict: {name, type, description?}. Auto-embeds."""
        ...

    async def update_node(self, record_id: str, fields: dict) -> dict:
        """Update node fields. Auto re-embeds if text fields changed (content/name/description)."""
        ...

    async def delete_node(self, record_id: str) -> None:
        """Delete a node by record ID."""
        ...

    # ── Edges ──

    async def get_edge(self, edge_id: str) -> dict:
        """Fetch a single edge by ID. Returns {} if not found."""
        ...

    async def get_outgoing_edges(self, record_id: str) -> list[dict]:
        """All edges from this node. Each has id, in, out, and edge-specific fields."""
        ...

    async def get_incoming_edges(self, record_id: str) -> list[dict]:
        """All edges into this node."""
        ...

    async def create_edge(self, from_id: str, edge_table: str, to_id: str, fields: dict | None = None) -> dict:
        """Create a single edge. Returns the created record."""
        ...

    async def delete_edge(self, edge_id: str) -> None:
        """Delete an edge by ID."""
        ...

    async def check_edge_exists(self, from_id: str, edge_table: str, to_id: str) -> list[dict]:
        """Check if an edge exists between two nodes on a given table. Returns matching edges."""
        ...

    # ── Search ──

    async def hybrid_search(self, table: str, query_text: str, k: int = 5) -> list[dict]:
        """BM25 + vector search with RRF fusion. Auto-embeds the query text. Excludes embeddings from results."""
        ...

    async def vector_search(self, table: str, query_embedding: list[float], k: int = 5) -> list[dict]:
        """Vector similarity search with a pre-computed embedding. Excludes embeddings from results."""
        ...

    async def fulltext_search(self, table: str, query_text: str, k: int = 5) -> list[dict]:
        """BM25 full-text search. Excludes embeddings from results."""
        ...

    # ── Graph ──

    async def get_connections(self, record_id: str) -> list[dict]:
        """Edge neighborhood: [{edge_label, direction, adjacent_id}, ...] for a node."""
        ...

    # ── Low-level ──

    async def count_nodes(self, table: str) -> int:
        """Count records in a table (for scheduler)."""
        ...

    async def select_batch(self, table: str | None, order_by: str, limit: int) -> list[dict]:
        """Select nodes ordered by a field with limit (for scheduler batch selection)."""
        ...

    async def get_node_field(self, record_id: str, field: str) -> Any:
        """Fetch a single field from a node (e.g. 'embedding', 'dream_age')."""
        ...
```

**Contracts:**
- All record IDs are plain strings in `"table:id"` format. Storage normalizes `RecordID` objects internally — callers never see them.
- All returned dicts exclude embedding arrays unless the method specifically targets embeddings (e.g. `get_node_field(id, "embedding")`).
- `update_node` auto re-embeds when any of `content`, `name`, or `description` appear in the fields dict. The text to embed follows the same logic as creation: notes embed `content`, entities embed `description` (falling back to `name`).
- `hybrid_search` handles query embedding internally using the injected Embedder, then runs vector + BM25 search and fuses results with reciprocal rank fusion (k=60).
- `create_edge` does not do dedup checking — that's business logic in the callers (`create_edges` in ingest_tools, `merge_nodes` in dream_tools). The storage primitive just creates.
- Edge dicts returned by `get_outgoing_edges` / `get_incoming_edges` have `id`, `in`, `out` as plain strings, plus any edge-specific fields (`context`, `dream_age`).

#### Agent Deps (post-refactor)

```python
@dataclass
class IngestDeps:
    storage: Storage

@dataclass
class RecallDeps:
    storage: Storage

@dataclass
class ConverseDeps:
    storage: Storage
    model_setting: Model | str
    context: Context = field(default_factory=Context)
    progress_queue: asyncio.Queue | None = None

@dataclass
class DedupDeps:
    storage: Storage
    cancel: asyncio.Event
    touched_ids: list[str] = field(default_factory=list)

@dataclass
class ConnectDeps:
    storage: Storage
    cancel: asyncio.Event
    touched_ids: list[str] = field(default_factory=list)
```

#### Test Construction

```python
# conftest.py
storage = Storage(url="mem://", embedder=DummyEmbedder(dimensions=4), dimensions=4)
await storage.init()
```

`DummyEmbedder` returns zero vectors of the configured dimension. Replaces the current `_dummy_embed` closure in `app.py`.

## Tests

**Pre-test-write commit:** `50a19820e7099ee7eafb258e506a68be72f614bb`

### Interface Files

- `src/second_brain/db.py` — Added `Embedder` protocol (runtime-checkable, with `embed` and `embed_batch` methods) and `Storage` class with full method signatures and `NotImplementedError` stubs for all operations. `__init__`, `init`, and `close` are implemented as connection-management wiring.
- `tests/conftest.py` — Added `DummyEmbedder` class (zero-vector embedder conforming to `Embedder` protocol) and `storage` fixture that constructs `Storage` with `mem://` backend.

### Test Files

- `tests/test_storage.py` — 74 behavioral tests exercising the full `Storage` public interface: node CRUD, edge CRUD, search (hybrid/vector/fulltext), graph traversal, and low-level scheduler support operations.

### Behaviors Covered

#### Node Operations

- `get_node` returns a node by record ID with embeddings excluded
- `get_node` returns empty dict when node not found
- `get_node` returns record ID as a plain `"table:id"` string
- `get_nodes` returns multiple nodes, excludes embeddings, skips missing IDs
- `get_nodes` returns empty list for empty input
- `create_note` creates a note with content, auto-embeds, defaults source to `"api"`
- `create_note` accepts optional source and summary parameters
- `create_note` returns a record with plain-string ID starting with `"note:"`
- `create_notes` bulk-creates multiple notes with auto-embedding
- `create_notes` returns empty list for empty input
- `create_entity` creates an entity with name and type, auto-embeds description (or name as fallback)
- `create_entity` accepts optional description
- `create_entity` returns a record with plain-string ID starting with `"entity:"`
- `create_entities` bulk-creates multiple entities with auto-embedding
- `create_entities` returns empty list for empty input
- `update_node` updates specified fields while preserving unchanged ones
- `update_node` auto re-embeds when content, name, or description fields change
- `update_node` does not re-embed when non-text fields change (e.g. dream_age)
- `delete_node` removes a node so it is no longer retrievable
- `delete_node` does not raise for nonexistent nodes

#### Edge Operations

- `get_edge` returns an edge by ID
- `get_edge` returns empty dict when edge not found
- `get_outgoing_edges` returns all outgoing edges from a node with `id`, `in`, `out` as plain strings
- `get_outgoing_edges` includes edge-specific fields (e.g. context)
- `get_outgoing_edges` returns empty list for nodes with no outgoing edges
- `get_incoming_edges` returns all incoming edges to a node
- `get_incoming_edges` returns empty list for nodes with no incoming edges
- `create_edge` creates an edge between two nodes and returns the record
- `create_edge` accepts optional fields dict (e.g. context)
- `create_edge` does NOT deduplicate — two calls create two distinct edges
- `create_edge` returns a record with plain-string ID
- `delete_edge` removes an edge so it is no longer retrievable
- `delete_edge` does not raise for nonexistent edges
- `check_edge_exists` returns matching edges between two nodes on a given table
- `check_edge_exists` returns empty list when no matching edge exists

#### Search Operations

- `hybrid_search` returns matching results via BM25 + vector fusion
- `hybrid_search` auto-embeds the query text (no pre-computed embedding required)
- `hybrid_search` excludes embeddings from results
- `hybrid_search` returns empty list for no matches
- `hybrid_search` works on both note and entity tables
- `hybrid_search` respects the k parameter
- `vector_search` returns results for a pre-computed embedding
- `vector_search` excludes embeddings from results
- `vector_search` returns empty list for no matches
- `fulltext_search` returns BM25 matches
- `fulltext_search` excludes embeddings from results
- `fulltext_search` returns empty list for no matches

#### Graph Operations

- `get_connections` returns edge neighborhood with `edge_label`, `direction`, `adjacent_id`
- `get_connections` correctly labels outgoing edges as direction `"out"`
- `get_connections` correctly labels incoming edges as direction `"in"`
- `get_connections` returns empty list for isolated nodes

#### Low-level Operations

- `count_nodes` counts records in a specific table
- `count_nodes` returns zero for empty tables
- `count_nodes` counts note and entity tables independently
- `select_batch` returns ordered records with a limit, verifying sort order
- `select_batch` returns empty list for empty tables
- `select_batch` with `table=None` selects across both note and entity tables
- `get_node_field` returns a specific field value (content, embedding, dream_age)

**Review status:** approved

## Steps

**Pre-implementation commit:** `fe9854a53c2b7927aa122b801a2d309772c349dd`

### Step 1: Add private helpers to the Storage class

Add private utility methods inside `Storage` in `src/second_brain/db.py`. These are the internal plumbing every public method uses.

- **`_check(result, context)`** — static method. Same logic as `check_query_result` in `validation.py`: if `result` is a `str`, raise `RuntimeError(f"{context}: {result}")`. If `list`, return it. Otherwise return `[]`.
- **`_normalize(record, *, keep_embedding=False)`** — call `make_serializable(record)` from `models.py` to convert `RecordID` → `"table:id"` strings and `datetime` → ISO strings, then pop `"embedding"` unless `keep_embedding=True`. Return the dict.
- **`_embed_text(table, fields)`** — determine what text to embed for a record. If `table == "note"`, return `fields.get("content")`. Otherwise return `fields.get("description") or fields.get("name")`. Returns `str | None`.

Add `from second_brain.models import make_serializable` to the imports at the top of `db.py`.

**Verify:** No tests target these directly — they're exercised by all subsequent steps. Confirm `db.py` imports cleanly: `.venv/bin/python -c "from second_brain.db import Storage"`.
**Status:** done

### Step 2: Implement node creation methods

Implement `create_note`, `create_notes`, `create_entity`, `create_entities` in `Storage` in `src/second_brain/db.py`.

**`create_note(content, source, summary)`:**
- Embed content: `embedding = await self._embedder.embed(content)`.
- Build data dict: `{"content": content, "source": source, "embedding": embedding}`. Add `"summary"` if not `None`.
- Create: `result = await self._db.create("note", data)`. The SDK may return a dict or a single-element list — handle both: `rec = result if isinstance(result, dict) else result[0]`.
- Return `self._normalize(rec)`.

**`create_notes(notes)`:**
- Return `[]` for empty input.
- Extract content strings, call `self._embedder.embed_batch(contents)`.
- For each note dict + embedding, build data dict (content, source defaulting to `"api"`, embedding, optional summary) and `self._db.create("note", data)`.
- Return list of normalized records.

**`create_entity(name, type, description)`:**
- Embed: `await self._embedder.embed(description if description else name)`.
- Build data: `{"name": name, "type": type, "embedding": embedding}`. Add `"description"` if not `None`.
- Create via `self._db.create("entity", data)`.
- Return `self._normalize(rec)`.

**`create_entities(entities)`:**
- Return `[]` for empty input.
- Extract embed texts (`e.get("description") or e["name"]`), batch embed.
- For each entity dict + embedding, build data and create.
- Return list of normalized records.

**Verify:** `pytest tests/test_storage.py -k "TestCreateNote or TestCreateNotes or TestCreateEntity or TestCreateEntities"` — 16 tests pass.
**Status:** done

### Step 3: Implement node read and field access methods

Implement `get_node`, `get_nodes`, `get_node_field` in `Storage` in `src/second_brain/db.py`.

**`get_node(record_id)`:**
- Query: `SELECT * OMIT embedding FROM {record_id}` (inline the validated record ID).
- Validate with `self._check(result, ...)`.
- Return `self._normalize(result[0])` if result is non-empty, else `{}`.

**`get_nodes(record_ids)`:**
- Return `[]` for empty input.
- Loop: call `self.get_node(rid)` for each ID. Collect non-empty results.
- Return the collected list.

**`get_node_field(record_id, field)`:**
- Query: `SELECT {field} FROM {record_id}`.
- Validate, return `result[0].get(field)` if result is non-empty. The returned value is raw (may include embedding arrays) — do not normalize.

**Verify:** `pytest tests/test_storage.py -k "TestGetNode or TestGetNodes or TestGetNodeField"` — 11 tests pass.
**Status:** done

### Step 4: Implement node mutation methods

Implement `update_node`, `delete_node` in `Storage` in `src/second_brain/db.py`.

**`update_node(record_id, fields)`:**
- Determine table from record_id: `table = record_id.split(":")[0]`.
- Check if any text field is being updated: `TEXT_FIELDS = {"content", "name", "description"}`. `needs_embed = bool(TEXT_FIELDS & fields.keys())`.
- If `needs_embed`:
  - Fetch current record: `SELECT * FROM {record_id}` to get existing field values.
  - Merge: `merged = {**existing_fields, **fields}`.
  - Compute embed text via `self._embed_text(table, merged)`.
  - Embed: `embedding = await self._embedder.embed(text)` if text is non-empty.
  - Add `"embedding": embedding` to the fields dict.
- Build `SET` clause: `", ".join(f"{k} = ${k}" for k in fields)`.
- Query: `UPDATE {record_id} SET {set_clauses}, updated_at = time::now()` with fields as params.
- Validate result. Return `self._normalize(result[0])`.

**`delete_node(record_id)`:**
- Query: `DELETE {record_id}`. No error handling needed — SurrealDB silently ignores missing records.

**Verify:** `pytest tests/test_storage.py -k "TestUpdateNode or TestDeleteNode"` — 9 tests pass.
**Status:** done

### Step 5: Implement edge operations

Implement all six edge methods in `Storage` in `src/second_brain/db.py`.

**`create_edge(from_id, edge_table, to_id, fields)`:**
- Build query: `RELATE {from_id}->{edge_table}->{to_id}`.
- If `fields` is provided and non-empty, append `SET` clause: `SET {k} = ${k}, ...` with fields as params.
- Execute, validate. Return `self._normalize(result[0])` (edge dicts get `id`, `in`, `out` as plain strings).

**`get_edge(edge_id)`:**
- Query: `SELECT * FROM {edge_id}`.
- Return `self._normalize(result[0])` if found, else `{}`.

**`get_outgoing_edges(record_id)`:**
- Query: `SELECT * FROM {record_id}->?`.
- Handle: result may be a list of edges or a non-list. Validate.
- Return `[self._normalize(e) for e in result]` — edge dicts have `id`, `in`, `out` as plain strings plus edge-specific fields.

**`get_incoming_edges(record_id)`:**
- Query: `SELECT * FROM {record_id}<-?`.
- Same handling as outgoing.

**`delete_edge(edge_id)`:**
- Query: `DELETE {edge_id}`. Silent on missing.

**`check_edge_exists(from_id, edge_table, to_id)`:**
- Query: `SELECT * FROM {from_id}->{edge_table} WHERE out = {to_id}`.
- Validate. Return `[self._normalize(e) for e in result]`.

**Verify:** `pytest tests/test_storage.py -k "TestCreateEdge or TestGetEdge or TestGetOutgoingEdges or TestGetIncomingEdges or TestDeleteEdge or TestCheckEdgeExists"` — 16 tests pass.
**Status:** done

### Step 6: Implement search operations

Implement `hybrid_search`, `vector_search`, `fulltext_search` in `Storage` in `src/second_brain/db.py`. Port the search logic from `recall_tools.py`.

**`hybrid_search(table, query_text, k)`:**
- Embed query: `query_embedding = await self._embedder.embed(query_text)`.
- Vector search: `SELECT * OMIT embedding FROM {table} WHERE embedding <|{k},100|> $vec` with `{"vec": query_embedding}`.
- Determine BM25 field: `"content"` for `"note"`, `"name"` for `"entity"`.
- Fulltext search: `SELECT *, search::score(1) AS score OMIT embedding FROM {table} WHERE {field} @1@ $query ORDER BY score DESC LIMIT {k}` with `{"query": query_text}`.
- Validate both results with `self._check`.
- RRF fusion (k=60): for each ranked list, compute `score = 1 / (60 + rank + 1)` per record ID. Sum scores across both lists. Sort by total score descending, take top `k`.
- Strip `"score"` key from result dicts.
- Return `[self._normalize(r) for r in top_k]`.

**`vector_search(table, query_embedding, k)`:**
- Query: `SELECT * OMIT embedding FROM {table} WHERE embedding <|{k},100|> $vec` with `{"vec": query_embedding}`.
- Validate. Return `[self._normalize(r) for r in result]`.

**`fulltext_search(table, query_text, k)`:**
- Determine field: `"content"` for `"note"`, `"name"` for `"entity"`.
- Query: `SELECT *, search::score(1) AS score OMIT embedding FROM {table} WHERE {field} @1@ $query ORDER BY score DESC LIMIT {k}` with `{"query": query_text}`.
- Validate. Strip `"score"` from each result.
- Return `[self._normalize(r) for r in result]`.

**Verify:** `pytest tests/test_storage.py -k "TestHybridSearch or TestVectorSearch or TestFulltextSearch"` — 12 tests pass.
**Status:** done

### Step 7: Implement graph and low-level operations

Implement `get_connections`, `count_nodes`, `select_batch` in `Storage` in `src/second_brain/db.py`.

**`get_connections(record_id)`:**
- Fetch outgoing edges: `SELECT * FROM {record_id}->?`. Fetch incoming: `SELECT * FROM {record_id}<-?`.
- Build connection list. For each outgoing edge: `{"edge_label": edge_table_from_id_prefix, "direction": "out", "adjacent_id": make_serializable(edge["out"])}`. For each incoming edge: `{"edge_label": ..., "direction": "in", "adjacent_id": make_serializable(edge["in"])}`.
- Extract edge table from the edge's `id` field: `make_serializable(edge["id"]).split(":")[0]`.
- Return the connections list.

**`count_nodes(table)`:**
- Query: `SELECT count() FROM {table} GROUP ALL`.
- If result is a non-empty list with `"count"` key, return `result[0]["count"]`. Otherwise return `0`.

**`select_batch(table, order_by, limit)`:**
- If `table` is not `None`: query `SELECT * OMIT embedding FROM {table} ORDER BY {order_by} ASC LIMIT {limit}`.
- If `table` is `None`: query both `"note"` and `"entity"` separately with the same ordering, merge results, sort by `order_by` ascending, return first `limit` records.
- Return `[self._normalize(r) for r in results]`.

**Verify:** `pytest tests/test_storage.py` — all 74 tests pass.
**Status:** done

### Step 8: Migrate tool files to use Storage

Change all three tool files to use `Storage` instead of raw `AsyncSurreal` + `embed_fn`. Update their corresponding test files.

**`src/second_brain/tools/recall_tools.py`:**
- All primitives (`hybrid_search`, `get_node`, `fetch_records_by_ids`, `enrich_with_connections`, `_to_str`) are now in Storage. Convert remaining functions to thin wrappers that delegate to Storage, or remove the module if agents will call Storage directly. Recommended approach: keep the file with wrapper functions so the agent-level changes in step 9 are smaller.
- Change signatures from `(db: AsyncSurreal, ...)` to `(storage: Storage, ...)`.
- `hybrid_search(storage, table, query_text, query_embedding, k)` → `return await storage.hybrid_search(table, query_text, k)`. The `query_embedding` parameter is now unused (Storage embeds internally) — keep for API compatibility or remove.
- `get_node(storage, record_id)` → `return await storage.get_node(record_id)`. Remove `validate_record_id` call (Storage handles normalization).
- `fetch_records_by_ids(storage, record_ids)` → `return await storage.get_nodes(record_ids)`.
- `enrich_with_connections(storage, record)` → fetch connections via `storage.get_connections(record_id)`, attach as `record["connections"]`, return enriched dict.
- Remove `AsyncSurreal`, `RecordID`, `check_query_result` imports. Add `from second_brain.db import Storage`.
- Update `tests/test_recall_tools.py`: replace `db` fixture usage with `storage` fixture. Update all call sites to pass `storage` instead of `db`. Remove `embed_fn`/`query_embedding` arguments from `hybrid_search` calls if the parameter was dropped.

**`src/second_brain/tools/ingest_tools.py`:**
- Remove `create_notes`, `create_entities`, `update_node` functions — these are now Storage methods.
- Remove `BatchEmbedder` protocol — replaced by `Embedder` in `db.py`.
- Update `create_edges(storage: Storage, edges)`: replace `db.query(...)` calls with `storage.check_edge_exists(from_id, edge_table, to_id)` for duplicate checks and `storage.create_edge(from_id, edge_table, to_id, fields)` for creation. Remove `validate_record_id`/`validate_identifier`/`check_query_result` calls — Storage handles normalization. Self-edge rejection and duplicate-skip logic stay as business logic.
- Update `store_knowledge(storage: Storage, entities, notes, edges)`: remove `embed_fn` parameter. Call `storage.create_entities(entities)`, `storage.create_notes(notes)`, and the local `create_edges(storage, resolved)`. `make_serializable` calls on record IDs are no longer needed — Storage already returns plain strings.
- Update `_resolve_ref` — unchanged (pure business logic).
- Remove `AsyncSurreal`, `check_query_result`, `validate_identifier`, `validate_record_id`, `Callable`, `Awaitable` imports. Add `from second_brain.db import Storage`.
- Update `tests/test_ingest_tools.py` and `tests/test_store_knowledge.py`: use `storage` fixture. Remove `embed_fn` parameters from function calls. Adjust for removed functions (create_notes, create_entities, update_node tests may need to move to test_storage.py or be removed if already covered there).

**`src/second_brain/tools/dream_tools.py`:**
- All functions stay but switch from `(db: AsyncSurreal, ..., embed_fn)` to `(storage: Storage, ...)`.
- Remove `_to_str` helper — Storage returns plain string IDs.
- `find_similar(storage, record_id, k)`: use `storage.get_node(record_id)` for source node, `storage.get_node_field(record_id, "embedding")` for source embedding, `storage.vector_search(table, embedding, k+1)` and `storage.fulltext_search(table, query_text, k+1)` for search. Self-exclusion and RRF fusion stay as business logic. Remove `make_serializable` calls (Storage returns normalized data). Remove `check_query_result` calls.
- `merge_nodes(storage, ids, new_fields, cancel)`: remove `embed_fn` parameter. Use `storage.get_node_field(id, "dream_age")` for ages. Use `storage.update_node(survivor, {**new_fields, "dream_age": max_age})` for survivor update (auto-re-embeds). Use `storage.get_outgoing_edges(loser)` / `storage.get_incoming_edges(loser)` for edges. Use `storage.check_edge_exists(...)` for duplicate detection. Edge re-pointing and duplicate merge: use `storage.delete_edge(old)` + `storage.create_edge(new_from, table, new_to, preserved_fields)` (delete-recreate pattern since Storage has no `update_edge`). Use `storage.delete_node(loser)` for cleanup. Use `storage.get_node(survivor)` for final result.
- `explore(storage, record_id, ...)`: use `storage.get_outgoing_edges(id)` / `storage.get_incoming_edges(id)` for traversal, `storage.get_node(neighbor)` for content.
- `find_unlinked_cooccurrences(storage, record_id, cancel)`: use `storage.get_incoming_edges(record_id)` for references edges, `storage.get_outgoing_edges(note_id)` for note→entity edges, `storage.get_outgoing_edges(record_id)` / `storage.get_outgoing_edges(other_id)` for direct-edge checks, `storage.get_node(id)` for content.
- `merge_edges(storage, ids, new_context, cancel)`: use `storage.get_edge(eid)` for fetching. Survivor "update" via delete-recreate: `storage.delete_edge(survivor_id)` then `storage.create_edge(from_id, table, to_id, {"context": new_context, "dream_age": max_age})`. Use `storage.delete_edge(lid)` for losers. Use `storage.get_edge(new_survivor_id)` for final result.
- Remove `AsyncSurreal`, `RecordID`, `check_query_result`, `validate_record_id`, embed-related imports.
- Update `tests/test_dream_tools.py`: use `storage` fixture. Remove `embed_fn` from function calls. Adjust for changed return formats (Storage returns normalized data, so `_to_str` calls in assertions become direct string comparisons).

**Verify:** `pytest tests/test_recall_tools.py tests/test_ingest_tools.py tests/test_store_knowledge.py tests/test_dream_tools.py tests/test_storage.py` — all tool tests and Storage tests pass.
**Status:** done

### Step 9: Migrate agents, scheduler, app.py, and conftest.py

Update all callers to use `Storage` instead of raw `AsyncSurreal` + `embed_fn`. Clean up obsolete code.

**Agent Deps — all five agent files in `src/second_brain/agents/`:**

- `ingest.py`: Change `IngestDeps` to `storage: Storage` (remove `db` and `embed_fn`). Update tool functions: `search_knowledge` → `ctx.deps.storage.hybrid_search(table, query, k)` for search, `ctx.deps.storage.get_connections(r["id"])` for enrichment (attach as `r["connections"]`). `store_knowledge` → `ingest_tools.store_knowledge(ctx.deps.storage, ...)`. `update_node` → `ctx.deps.storage.update_node(...)`. `get_node` → `ctx.deps.storage.get_node(...)` + `ctx.deps.storage.get_connections(...)`. Remove `AsyncSurreal`, `Callable`, `Awaitable` imports, add `Storage` import.
- `recall.py`: Change `RecallDeps` to `storage: Storage`. Same search/enrichment pattern as ingest. Remove `AsyncSurreal` imports.
- `converse.py`: Change `ConverseDeps` to `storage: Storage` + `model_setting` + `context` + `progress_queue` (remove `db` and `embed_fn`). Update sub-agent deps construction: `RecallDeps(storage=ctx.deps.storage)`, `IngestDeps(storage=ctx.deps.storage)`. Replace `fetch_records_by_ids(ctx.deps.db, ids)` with `ctx.deps.storage.get_nodes(ids)`. For cited edges, loop: `[await ctx.deps.storage.get_edge(eid) for eid in cited_edge_ids]`, filter empty results. Remove `AsyncSurreal`, `fetch_records_by_ids` imports.
- `dream_dedup.py`: Change `DedupDeps` to `storage: Storage` + `cancel` + `touched_ids` (remove `db` and `embed_fn`). Update tool calls: `dream_tools.find_similar(ctx.deps.storage, ...)`, `dream_tools.explore(ctx.deps.storage, ...)`, `dream_tools.merge_nodes(ctx.deps.storage, ids, new_fields)` (no `embed_fn`), `dream_tools.merge_edges(ctx.deps.storage, ...)`, `recall_tools.get_node(ctx.deps.storage, ...)` or `ctx.deps.storage.get_node(...)` directly.
- `dream_connect.py`: Change `ConnectDeps` to `storage: Storage` + `cancel` + `touched_ids` (remove `db` and `embed_fn`). Update tool calls similarly. `ingest_tools.create_edges(ctx.deps.storage, edges)` for edge creation.

**`src/second_brain/scheduler.py`:**
- Change `__init__` to accept `storage: Storage` instead of `db: AsyncSurreal` + `embed_fn`. Store as `self.storage`.
- `_count_nodes()` → `return await self.storage.count_nodes("entity") + await self.storage.count_nodes("note")`.
- `_select_batch(table_filter)` → `return await self.storage.select_batch(table_filter, order_by="dream_age", limit=self.batch_size)`. When `table_filter` is `None`, pass `None` to `select_batch` — Storage handles cross-table selection. Remove the manual merge-sort logic.
- `_increment_dream_age(record_ids)` → for each ID: `current = await self.storage.get_node_field(rid, "dream_age")` then `await self.storage.update_node(rid, {"dream_age": (current or 0) + 1})`. This is two queries per ID instead of one, acceptable for the batch sizes involved.
- `run_cycle()`: update Deps construction: `DedupDeps(storage=self.storage, cancel=...)`, `ConnectDeps(storage=self.storage, cancel=...)`.
- Remove `AsyncSurreal`, `RecordID` imports.

**`src/second_brain/app.py`:**
- Replace globals `_db` and `_embed` with `_storage: Storage | None = None`.
- In `lifespan`, test mode: create a zero-vector embedder conforming to `Embedder` protocol (replace `_dummy_embed` closure), then `_storage = Storage(url="mem://", embedder=embedder, dimensions=settings.embedding_dimensions)` and `await _storage.init()`.
- In `lifespan`, production mode: wrap `create_embed_fn(...)` result in an `Embedder`-conforming adapter (the existing embed function is a bare callable, not an Embedder), then `_storage = Storage(url=f"surrealkv://{settings.db_path}", embedder=embedder, dimensions=settings.embedding_dimensions)` and `await _storage.init()`.
- Remove manual `init_schema`/`init_vector_indexes` calls — `Storage.init()` handles them.
- On shutdown: `await _storage.close()` instead of `await _db.close()`.
- Update all Deps construction: `IngestDeps(storage=_storage)`, `RecallDeps(storage=_storage)`, `ConverseDeps(storage=_storage, model_setting=_model)`, etc.
- Update `DreamScheduler` construction: `DreamScheduler(storage=_storage, model=_model, ...)`.
- Update `get_graph_data`: use `_storage.get_node(record_id)`, `_storage.get_outgoing_edges(record_id)` + `_storage.get_incoming_edges(record_id)` for connections. Remove `_get_raw_connections` helper. Storage returns normalized data — remove `make_serializable` wrapping.
- Update `run_recall_agent` and `run_converse_agent`: use `_storage` for Deps, replace `fetch_records_by_ids(_db, ids)` with `_storage.get_nodes(ids)`.
- Remove `AsyncSurreal`, `init_schema`, `init_vector_indexes`, `recall_tools.get_node`, `recall_tools.fetch_records_by_ids` imports.

**`tests/conftest.py`:**
- The `storage` fixture already exists and constructs Storage correctly. Keep it.
- The `db` fixture (raw `AsyncSurreal("mem://")`) may still be needed by tests that haven't migrated. If all tests now use `storage`, remove the `db` fixture. If some tests still need it, keep it.
- `DummyEmbedder` stays in `conftest.py` (it's test infrastructure).

**`src/second_brain/validation.py`:**
- Remove `check_query_result` function — it's now a private method in Storage (`_check`). Keep `validate_record_id` and `validate_identifier` (still used by tool business logic like `create_edges` in `ingest_tools.py` and possibly agents).
- Check: if `create_edges` in `ingest_tools.py` no longer uses `validate_record_id`/`validate_identifier` (Storage handles validation internally), remove those imports too and assess whether `validation.py` still has callers.

**`src/second_brain/mcp.py`:**
- Review for any direct `db` or `embed_fn` usage. The MCP module receives configured callbacks from `app.py` (`run_recall`, `run_ingest`, `get_graph`), so it should need no changes unless it imports SurrealDB types.

Update all agent and scheduler test files to construct Deps with `storage` instead of `db` + `embed_fn`:
- `tests/test_ingest_agent.py`
- `tests/test_recall_agent.py`
- `tests/test_converse_agent.py`
- `tests/test_dream_dedup_agent.py`
- `tests/test_dream_connect_agent.py`
- `tests/test_scheduler.py`
- `tests/test_app.py`
- `tests/test_mcp.py`

**Verify:** Full test suite passes: `pytest tests/` with zero failures. Confirm no remaining `AsyncSurreal` imports in tool files, agent files, or scheduler (only in `db.py`).
**Status:** done
