from typing import Any, Protocol, runtime_checkable

from surrealdb import AsyncSurreal

from second_brain.config import settings
from second_brain.models import make_serializable


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

    # ── Private Helpers ──

    @staticmethod
    def _check(result: Any, context: str) -> list:
        """Validate a db.query() result — raise on error string, return list."""
        if isinstance(result, str):
            raise RuntimeError(f"{context}: {result}")
        if isinstance(result, list):
            return result
        return []

    @staticmethod
    def _normalize(record: dict, *, keep_embedding: bool = False) -> dict:
        """Convert SurrealDB types to plain Python and strip embeddings."""
        result = make_serializable(record)
        if not keep_embedding:
            result.pop("embedding", None)
        return result

    @staticmethod
    def _embed_text(table: str, fields: dict) -> str | None:
        """Determine what text to embed for a record."""
        if table == "note":
            return fields.get("content")
        return fields.get("description") or fields.get("name")

    # ── Nodes ──

    async def get_node(self, record_id: str) -> dict:
        """Fetch a single node by record ID. Returns ``{}`` if not found. Excludes embeddings."""
        assert self._db is not None
        result = await self._db.query(f"SELECT * OMIT embedding FROM {record_id}")
        result = self._check(result, f"get_node({record_id})")
        if not result:
            return {}
        return self._normalize(result[0])

    async def get_nodes(self, record_ids: list[str]) -> list[dict]:
        """Fetch multiple nodes by ID. Excludes embeddings. Skips missing."""
        if not record_ids:
            return []
        results = []
        for rid in record_ids:
            node = await self.get_node(rid)
            if node:
                results.append(node)
        return results

    async def create_note(
        self, content: str, source: str = "api", summary: str | None = None
    ) -> dict:
        """Create a note, auto-embedding content. Returns the created record."""
        assert self._db is not None
        embedding = await self._embedder.embed(content)
        data: dict[str, Any] = {
            "content": content,
            "source": source,
            "embedding": embedding,
        }
        if summary is not None:
            data["summary"] = summary
        result = await self._db.create("note", data)
        rec = result if isinstance(result, dict) else result[0]
        return self._normalize(rec)

    async def create_notes(self, notes: list[dict]) -> list[dict]:
        """Bulk create notes. Each dict: ``{content, source?, summary?}``. Auto-embeds."""
        if not notes:
            return []
        assert self._db is not None
        contents = [n["content"] for n in notes]
        embeddings = await self._embedder.embed_batch(contents)
        results = []
        for note, emb in zip(notes, embeddings, strict=True):
            data: dict[str, Any] = {
                "content": note["content"],
                "source": note.get("source", "api"),
                "embedding": emb,
            }
            if note.get("summary") is not None:
                data["summary"] = note["summary"]
            result = await self._db.create("note", data)
            rec = result if isinstance(result, dict) else result[0]
            results.append(self._normalize(rec))
        return results

    async def create_entity(
        self, name: str, type: str, description: str | None = None
    ) -> dict:
        """Create an entity, auto-embedding description (or name). Returns the created record."""
        assert self._db is not None
        embedding = await self._embedder.embed(description if description else name)
        data: dict[str, Any] = {"name": name, "type": type, "embedding": embedding}
        if description is not None:
            data["description"] = description
        result = await self._db.create("entity", data)
        rec = result if isinstance(result, dict) else result[0]
        return self._normalize(rec)

    async def create_entities(self, entities: list[dict]) -> list[dict]:
        """Bulk create entities. Each dict: ``{name, type, description?}``. Auto-embeds."""
        if not entities:
            return []
        assert self._db is not None
        texts = [e.get("description") or e["name"] for e in entities]
        embeddings = await self._embedder.embed_batch(texts)
        results = []
        for ent, emb in zip(entities, embeddings, strict=True):
            data: dict[str, Any] = {
                "name": ent["name"],
                "type": ent["type"],
                "embedding": emb,
            }
            if ent.get("description") is not None:
                data["description"] = ent["description"]
            result = await self._db.create("entity", data)
            rec = result if isinstance(result, dict) else result[0]
            results.append(self._normalize(rec))
        return results

    async def update_node(self, record_id: str, fields: dict) -> dict:
        """Update node fields. Auto re-embeds if text fields changed (content/name/description)."""
        assert self._db is not None
        table = record_id.split(":")[0]
        text_fields = {"content", "name", "description"}
        needs_embed = bool(text_fields & fields.keys())
        if needs_embed:
            existing = await self._db.query(f"SELECT * FROM {record_id}")
            existing = self._check(existing, f"update_node fetch {record_id}")
            if existing:
                merged = {**make_serializable(existing[0]), **fields}
            else:
                merged = dict(fields)
            embed_text = self._embed_text(table, merged)
            if embed_text:
                embedding = await self._embedder.embed(embed_text)
                fields["embedding"] = embedding
        set_clauses = ", ".join(f"{k} = ${k}" for k in fields)
        query = f"UPDATE {record_id} SET {set_clauses}, updated_at = time::now()"
        result = await self._db.query(query, fields)
        result = self._check(result, f"update_node({record_id})")
        return self._normalize(result[0])

    async def delete_node(self, record_id: str) -> None:
        """Delete a node by record ID."""
        assert self._db is not None
        await self._db.query(f"DELETE {record_id}")

    # ── Edges ──

    async def get_edge(self, edge_id: str) -> dict:
        """Fetch a single edge by ID. Returns ``{}`` if not found."""
        assert self._db is not None
        result = await self._db.query(f"SELECT * FROM {edge_id}")
        result = self._check(result, f"get_edge({edge_id})")
        if not result:
            return {}
        return self._normalize(result[0])

    async def get_outgoing_edges(self, record_id: str) -> list[dict]:
        """All edges from this node. Each has ``id``, ``in``, ``out`` as plain strings, plus edge-specific fields."""
        assert self._db is not None
        result = await self._db.query(f"SELECT * FROM {record_id}->?")
        result = self._check(result, f"get_outgoing_edges({record_id})")
        return [self._normalize(e) for e in result]

    async def get_incoming_edges(self, record_id: str) -> list[dict]:
        """All edges into this node."""
        assert self._db is not None
        result = await self._db.query(f"SELECT * FROM {record_id}<-?")
        result = self._check(result, f"get_incoming_edges({record_id})")
        return [self._normalize(e) for e in result]

    async def create_edge(
        self, from_id: str, edge_table: str, to_id: str, fields: dict | None = None
    ) -> dict:
        """Create a single edge. Returns the created record.

        Does **not** deduplicate — that is business logic in callers.
        """
        assert self._db is not None
        query = f"RELATE {from_id}->{edge_table}->{to_id}"
        if fields:
            set_parts = ", ".join(f"{k} = ${k}" for k in fields)
            query += f" SET {set_parts}"
            result = await self._db.query(query, fields)
        else:
            result = await self._db.query(query)
        result = self._check(result, f"create_edge({from_id}->{edge_table}->{to_id})")
        return self._normalize(result[0])

    async def delete_edge(self, edge_id: str) -> None:
        """Delete an edge by ID."""
        assert self._db is not None
        await self._db.query(f"DELETE {edge_id}")

    async def check_edge_exists(
        self, from_id: str, edge_table: str, to_id: str
    ) -> list[dict]:
        """Check if an edge exists between two nodes on a given table. Returns matching edges."""
        assert self._db is not None
        result = await self._db.query(
            f"SELECT * FROM {from_id}->{edge_table} WHERE out = {to_id}"
        )
        result = self._check(
            result, f"check_edge_exists({from_id}->{edge_table}->{to_id})"
        )
        return [self._normalize(e) for e in result]

    # ── Search ──

    async def hybrid_search(
        self, table: str, query_text: str, k: int = 5
    ) -> list[dict]:
        """BM25 + vector search with RRF fusion. Auto-embeds the query text. Excludes embeddings from results."""
        assert self._db is not None
        query_embedding = await self._embedder.embed(query_text)

        # Vector search
        vs_result = await self._db.query(
            f"SELECT * OMIT embedding FROM {table} WHERE embedding <|{k},100|> $vec",
            {"vec": query_embedding},
        )
        vs_result = self._check(vs_result, f"hybrid_search vector on {table}")

        # Fulltext search
        field = "content" if table == "note" else "name"
        ft_result = await self._db.query(
            f"SELECT *, search::score(1) AS score OMIT embedding "
            f"FROM {table} WHERE {field} @1@ $query "
            f"ORDER BY score DESC LIMIT {k}",
            {"query": query_text},
        )
        ft_result = self._check(ft_result, f"hybrid_search fulltext on {table}")

        # RRF fusion (k=60)
        rrf_k = 60
        scores: dict[str, float] = {}
        records: dict[str, dict] = {}
        for rank, rec in enumerate(vs_result):
            rid = (
                make_serializable(rec["id"])
                if not isinstance(rec["id"], str)
                else rec["id"]
            )
            scores[rid] = scores.get(rid, 0) + 1 / (rrf_k + rank + 1)
            records[rid] = rec
        for rank, rec in enumerate(ft_result):
            rid = (
                make_serializable(rec["id"])
                if not isinstance(rec["id"], str)
                else rec["id"]
            )
            scores[rid] = scores.get(rid, 0) + 1 / (rrf_k + rank + 1)
            records[rid] = rec

        ranked_ids = sorted(scores, key=lambda rid: scores[rid], reverse=True)[:k]
        results = []
        for rid in ranked_ids:
            rec = dict(records[rid])
            rec.pop("score", None)
            results.append(self._normalize(rec))
        return results

    async def vector_search(
        self, table: str, query_embedding: list[float], k: int = 5
    ) -> list[dict]:
        """Vector similarity search with a pre-computed embedding. Excludes embeddings from results."""
        assert self._db is not None
        result = await self._db.query(
            f"SELECT * OMIT embedding FROM {table} WHERE embedding <|{k},100|> $vec",
            {"vec": query_embedding},
        )
        result = self._check(result, f"vector_search on {table}")
        return [self._normalize(r) for r in result]

    async def fulltext_search(
        self, table: str, query_text: str, k: int = 5
    ) -> list[dict]:
        """BM25 full-text search. Excludes embeddings from results."""
        assert self._db is not None
        field = "content" if table == "note" else "name"
        result = await self._db.query(
            f"SELECT *, search::score(1) AS score OMIT embedding "
            f"FROM {table} WHERE {field} @1@ $query "
            f"ORDER BY score DESC LIMIT {k}",
            {"query": query_text},
        )
        result = self._check(result, f"fulltext_search on {table}")
        results = []
        for rec in result:
            r = dict(rec)
            r.pop("score", None)
            results.append(self._normalize(r))
        return results

    # ── Graph ──

    async def get_connections(self, record_id: str) -> list[dict]:
        """Edge neighborhood: ``[{edge_label, direction, adjacent_id}, ...]`` for a node."""
        assert self._db is not None
        outgoing = await self._db.query(f"SELECT * FROM {record_id}->?")
        outgoing = self._check(outgoing, f"get_connections outgoing({record_id})")
        incoming = await self._db.query(f"SELECT * FROM {record_id}<-?")
        incoming = self._check(incoming, f"get_connections incoming({record_id})")

        connections = []
        for edge in outgoing:
            edge_id = make_serializable(edge["id"])
            connections.append(
                {
                    "edge_label": edge_id.split(":")[0],
                    "direction": "out",
                    "adjacent_id": make_serializable(edge["out"]),
                }
            )
        for edge in incoming:
            edge_id = make_serializable(edge["id"])
            connections.append(
                {
                    "edge_label": edge_id.split(":")[0],
                    "direction": "in",
                    "adjacent_id": make_serializable(edge["in"]),
                }
            )
        return connections

    # ── Low-level ──

    async def count_nodes(self, table: str) -> int:
        """Count records in a table (for scheduler)."""
        assert self._db is not None
        result = await self._db.query(f"SELECT count() FROM {table} GROUP ALL")
        result = self._check(result, f"count_nodes({table})")
        if result and isinstance(result, list) and "count" in result[0]:
            return result[0]["count"]
        return 0

    async def select_batch(
        self, table: str | None, order_by: str, limit: int
    ) -> list[dict]:
        """Select nodes ordered by a field with limit (for scheduler batch selection)."""
        assert self._db is not None
        if table is not None:
            result = await self._db.query(
                f"SELECT * OMIT embedding FROM {table} ORDER BY {order_by} ASC LIMIT {limit}"
            )
            result = self._check(result, f"select_batch({table})")
            return [self._normalize(r) for r in result]
        # table=None: select from both note and entity, merge, sort, limit
        notes = await self._db.query(
            f"SELECT * OMIT embedding FROM note ORDER BY {order_by} ASC LIMIT {limit}"
        )
        notes = self._check(notes, "select_batch(note)")
        entities = await self._db.query(
            f"SELECT * OMIT embedding FROM entity ORDER BY {order_by} ASC LIMIT {limit}"
        )
        entities = self._check(entities, "select_batch(entity)")
        combined = [self._normalize(r) for r in notes + entities]
        combined.sort(key=lambda r: r.get(order_by, 0))
        return combined[:limit]

    async def get_node_field(self, record_id: str, field: str) -> Any:
        """Fetch a single field from a node (e.g. ``'embedding'``, ``'dream_age'``)."""
        assert self._db is not None
        result = await self._db.query(f"SELECT {field} FROM {record_id}")
        result = self._check(result, f"get_node_field({record_id}, {field})")
        if not result:
            return None
        return result[0].get(field)
