from typing import Any, Protocol, runtime_checkable

from surrealdb import AsyncSurreal

from second_brain.config import settings


async def get_db() -> AsyncSurreal:  # pyright: ignore[reportGeneralTypeIssues]
    """Create and return an embedded SurrealDB connection."""
    db = AsyncSurreal(f"surrealkv://{settings.db_path}")  # pyright: ignore[reportGeneralTypeIssues]
    await db.use("brain", "brain")
    await init_schema(db)
    return db


async def init_schema(db: AsyncSurreal) -> None:  # pyright: ignore[reportGeneralTypeIssues]
    """Define tables, fields, and indexes. Idempotent."""
    await db.query("""
        -- Full-text search analyzer
        DEFINE ANALYZER IF NOT EXISTS simple_analyzer
            TOKENIZERS blank, class, camel, punct
            FILTERS lowercase, snowball(english);

        -- Note table
        DEFINE TABLE IF NOT EXISTS note SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS content ON note TYPE string;
        DEFINE FIELD IF NOT EXISTS summary ON note TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS embedding ON note TYPE option<array<float>>;
        DEFINE FIELD IF NOT EXISTS source ON note TYPE string;
        DEFINE FIELD IF NOT EXISTS created_at ON note TYPE datetime DEFAULT time::now();
        DEFINE FIELD IF NOT EXISTS updated_at ON note TYPE datetime DEFAULT time::now();
        DEFINE FIELD IF NOT EXISTS dream_age ON note TYPE int DEFAULT 0;

        -- Entity table
        DEFINE TABLE IF NOT EXISTS entity SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS name ON entity TYPE string;
        DEFINE FIELD IF NOT EXISTS type ON entity TYPE string;
        DEFINE FIELD IF NOT EXISTS description ON entity TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS embedding ON entity TYPE option<array<float>>;
        DEFINE FIELD IF NOT EXISTS dream_age ON entity TYPE int DEFAULT 0;

        -- Edge tables
        DEFINE TABLE IF NOT EXISTS references SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS dream_age ON references TYPE int DEFAULT 0;
        DEFINE TABLE IF NOT EXISTS relates_to SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS context ON relates_to TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS dream_age ON relates_to TYPE int DEFAULT 0;
        DEFINE TABLE IF NOT EXISTS derived_from SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS dream_age ON derived_from TYPE int DEFAULT 0;

        -- Full-text indexes
        DEFINE INDEX IF NOT EXISTS note_content_fts ON note FIELDS content
            SEARCH ANALYZER simple_analyzer BM25;
        DEFINE INDEX IF NOT EXISTS entity_name_fts ON entity FIELDS name
            SEARCH ANALYZER simple_analyzer BM25;
    """)


async def init_vector_indexes(db: AsyncSurreal, dimensions: int | None = None) -> None:  # pyright: ignore[reportGeneralTypeIssues]
    """Define HNSW vector indexes. Idempotent."""
    dim = dimensions or settings.embedding_dimensions
    await db.query(f"""
        DEFINE INDEX IF NOT EXISTS note_embedding_hnsw ON note
            FIELDS embedding HNSW DIMENSION {dim} DIST COSINE;
        DEFINE INDEX IF NOT EXISTS entity_embedding_hnsw ON entity
            FIELDS embedding HNSW DIMENSION {dim} DIST COSINE;
    """)


# ── Embedder Protocol ─────────────────────────────────────────────────────────


@runtime_checkable
class Embedder(Protocol):
    """Protocol for embedding text into vectors.

    Injected into Storage at construction. Replaces bare callable signatures
    and the BatchEmbedder protocol from ingest_tools.
    """

    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


# ── Storage Class ─────────────────────────────────────────────────────────────


class Storage:
    """Domain-level storage abstraction over SurrealDB.

    Wraps all raw SurrealQL behind graph-concept operations (nodes, edges,
    search, traversal).  Callers work with plain dicts and strings — no
    SurrealDB SDK types leak out.
    """

    def __init__(self, url: str, embedder: Embedder, dimensions: int) -> None:
        """Wrap a DB connection.

        Args:
            url: ``'mem://'`` for tests, ``'surrealkv://path'`` for prod.
            embedder: Embedding provider conforming to the Embedder protocol.
            dimensions: Vector dimensions for HNSW indexes.
        """
        self._url = url
        self._embedder = embedder
        self._dimensions = dimensions
        self._db: AsyncSurreal | None = None  # pyright: ignore[reportGeneralTypeIssues]

    async def init(self) -> None:
        """Connect, set namespace, create schema + vector indexes. Call once at startup."""
        db = AsyncSurreal(self._url)  # pyright: ignore[reportGeneralTypeIssues]
        await db.use("brain", "brain")
        await init_schema(db)
        await init_vector_indexes(db, self._dimensions)
        self._db = db

    async def close(self) -> None:
        """Close the underlying connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # ── Nodes ──

    async def get_node(self, record_id: str) -> dict:
        """Fetch a single node by record ID. Returns ``{}`` if not found. Excludes embeddings."""
        raise NotImplementedError

    async def get_nodes(self, record_ids: list[str]) -> list[dict]:
        """Fetch multiple nodes by ID. Excludes embeddings. Skips missing."""
        raise NotImplementedError

    async def create_note(
        self, content: str, source: str = "api", summary: str | None = None
    ) -> dict:
        """Create a note, auto-embedding content. Returns the created record."""
        raise NotImplementedError

    async def create_notes(self, notes: list[dict]) -> list[dict]:
        """Bulk create notes. Each dict: ``{content, source?, summary?}``. Auto-embeds."""
        raise NotImplementedError

    async def create_entity(
        self, name: str, type: str, description: str | None = None
    ) -> dict:
        """Create an entity, auto-embedding description (or name). Returns the created record."""
        raise NotImplementedError

    async def create_entities(self, entities: list[dict]) -> list[dict]:
        """Bulk create entities. Each dict: ``{name, type, description?}``. Auto-embeds."""
        raise NotImplementedError

    async def update_node(self, record_id: str, fields: dict) -> dict:
        """Update node fields. Auto re-embeds if text fields changed (content/name/description)."""
        raise NotImplementedError

    async def delete_node(self, record_id: str) -> None:
        """Delete a node by record ID."""
        raise NotImplementedError

    # ── Edges ──

    async def get_edge(self, edge_id: str) -> dict:
        """Fetch a single edge by ID. Returns ``{}`` if not found."""
        raise NotImplementedError

    async def get_outgoing_edges(self, record_id: str) -> list[dict]:
        """All edges from this node. Each has ``id``, ``in``, ``out`` as plain strings, plus edge-specific fields."""
        raise NotImplementedError

    async def get_incoming_edges(self, record_id: str) -> list[dict]:
        """All edges into this node."""
        raise NotImplementedError

    async def create_edge(
        self, from_id: str, edge_table: str, to_id: str, fields: dict | None = None
    ) -> dict:
        """Create a single edge. Returns the created record.

        Does **not** deduplicate — that is business logic in callers.
        """
        raise NotImplementedError

    async def delete_edge(self, edge_id: str) -> None:
        """Delete an edge by ID."""
        raise NotImplementedError

    async def check_edge_exists(
        self, from_id: str, edge_table: str, to_id: str
    ) -> list[dict]:
        """Check if an edge exists between two nodes on a given table. Returns matching edges."""
        raise NotImplementedError

    # ── Search ──

    async def hybrid_search(
        self, table: str, query_text: str, k: int = 5
    ) -> list[dict]:
        """BM25 + vector search with RRF fusion. Auto-embeds the query text. Excludes embeddings from results."""
        raise NotImplementedError

    async def vector_search(
        self, table: str, query_embedding: list[float], k: int = 5
    ) -> list[dict]:
        """Vector similarity search with a pre-computed embedding. Excludes embeddings from results."""
        raise NotImplementedError

    async def fulltext_search(
        self, table: str, query_text: str, k: int = 5
    ) -> list[dict]:
        """BM25 full-text search. Excludes embeddings from results."""
        raise NotImplementedError

    # ── Graph ──

    async def get_connections(self, record_id: str) -> list[dict]:
        """Edge neighborhood: ``[{edge_label, direction, adjacent_id}, ...]`` for a node."""
        raise NotImplementedError

    # ── Low-level ──

    async def count_nodes(self, table: str) -> int:
        """Count records in a table (for scheduler)."""
        raise NotImplementedError

    async def select_batch(
        self, table: str | None, order_by: str, limit: int
    ) -> list[dict]:
        """Select nodes ordered by a field with limit (for scheduler batch selection)."""
        raise NotImplementedError

    async def get_node_field(self, record_id: str, field: str) -> Any:
        """Fetch a single field from a node (e.g. ``'embedding'``, ``'dream_age'``)."""
        raise NotImplementedError
