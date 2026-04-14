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
