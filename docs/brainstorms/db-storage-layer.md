# DB Storage Layer Abstraction

## The Idea

Clean up database interactions by consolidating all raw SQL/SurrealQL into `db.py` and exposing a domain-level storage API. Callers should work with graph concepts (nodes, edges, search, traversal) without knowing the DB is SurrealDB specifically.

Currently, raw `db.query()` calls with SurrealQL strings are scattered across 5 files (`recall_tools.py`, `ingest_tools.py`, `dream_tools.py`, `scheduler.py`, `app.py`), and every tool/agent/scheduler is coupled to the `AsyncSurreal` SDK type.

## Key Decisions

### Graph concepts are part of the API, SurrealDB is not
The database being a graph with search and traversal capabilities is a domain reality — not an implementation detail. Edges, record IDs, hybrid search, graph traversal are all legitimate API concepts. What gets hidden: `AsyncSurreal`, `RecordID`, `db.query()`, SurrealQL syntax. Callers import and depend on the storage layer, never on the SurrealDB SDK.

### Storage layer is a class, not free functions
`db.py` becomes a class (e.g. `Storage`) that wraps the connection and exposes domain-level methods. Constructed at startup, injected into deps/scheduler/app. This replaces passing `AsyncSurreal` instances everywhere.

### Embeddings injected into storage via a protocol
The storage layer owns "embed before storing" behavior — callers don't think about vectors. An `Embedder` protocol is defined with `embed(text)` and `embed_batch(texts)` methods, injected at construction time. This replaces the `BatchEmbedder` protocol currently in `ingest_tools.py` and the bare `Callable[[str], Awaitable[list[float]]]` signatures used elsewhere.

### Fine-grained primitives, not high-level operations
The storage layer exposes graph primitives — CRUD on nodes, CRUD on edges, search, traversal. Complex multi-step operations like `merge_nodes`, `explore`, and `find_unlinked_cooccurrences` stay in `dream_tools.py` and compose primitives. Rationale: those operations contain business logic (edge dedup strategy, dream_age handling, BFS filtering) that doesn't belong in a storage layer.

### Hybrid search lives in the storage layer, including RRF fusion
One `hybrid_search` method combines vector search + BM25 fulltext search + reciprocal rank fusion. This replaces the duplicate implementations in `recall_tools.py` and `dream_tools.py`. `find_similar` in dream_tools becomes: fetch node → extract text + embedding → call `storage.hybrid_search()` → filter out self. RRF fusion is kept inside storage because it's part of "how search works."

### Chattiness is unchanged
The current code already does many sequential `await db.query()` calls (e.g. ~30 in `merge_nodes`). The refactor replaces those with named method calls — same number of awaits, just through an abstraction. SurrealDB runs embedded (in-process), so each call is essentially a function call. No optimization needed here.

## Direction

Introduce a `Storage` class in `db.py` with roughly these primitives:

- **Nodes:** `get_node`, `get_nodes`, `create_note`, `create_notes`, `create_entity`, `create_entities`, `update_node`, `delete_node`
- **Edges:** `get_edge`, `get_outgoing_edges`, `get_incoming_edges`, `create_edge`, `delete_edge`, `check_edge_exists`
- **Search:** `hybrid_search`, `vector_search`, `fulltext_search`
- **Graph:** `get_connections` (edge neighborhood enrichment)
- **Schema:** `init` (schema + vector indexes)

An `Embedder` protocol with `embed` and `embed_batch` is injected at construction.

All callers (`ingest_tools`, `recall_tools`, `dream_tools`, `scheduler`, `app`) switch from `AsyncSurreal` + raw queries to `Storage` + named methods. The `AsyncSurreal` type, `RecordID` type, and all SurrealQL strings are confined to `db.py`.

## Open Questions

- Exact method signatures will be worked out during architecture — some current queries have subtle variations (e.g. `SELECT * OMIT embedding` vs `SELECT embedding` vs `SELECT dream_age`) that need to be resolved into a coherent API.
- Whether `_to_str(RecordID)` normalization happens at the storage boundary (so callers always get plain strings) or whether a custom ID type is introduced.
- How the test helper (`mem://` backend) adapts — likely just a different `Storage` constructor argument.
