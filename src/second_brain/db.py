import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, TypeVar, runtime_checkable
from uuid import uuid4

from surrealdb import AsyncSurreal

from second_brain.config import settings
from second_brain.models import (
    ClaimedBatch,
    IntakeChunkDraft,
    IntakeQueueSnapshot,
    MemorySearchCandidates,
    RankedSearchCandidates,
    make_serializable,
    normalize_node,
)
from second_brain.validation import validate_identifier, validate_record_id

logger = logging.getLogger(__name__)

_SEARCH_FIELDS: dict[str, str] = {
    "note": "content",
    "entity": "name",
    "intake_chunk": "content",
}
_INTAKE_EVIDENCE_FIELDS = {
    "id",
    "intake_id",
    "chunk_index",
    "total_chunks",
    "content",
    "source",
    "created_at",
}

_T = TypeVar("_T")


class _RetryableConflict(RuntimeError):
    """A transaction conflict that is safe to retry."""


class IdempotencyConflict(ValueError):
    """An idempotency key was reused for different intake content."""


def _coerce_datetime(value: Any) -> datetime | None:
    """Return a timezone-aware datetime for queue comparisons."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    return None


def _intake_fingerprint(chunks: list[IntakeChunkDraft]) -> str:
    """Hash canonical staged content and metadata for idempotency checks."""
    payload = [
        {
            "content": chunk.content,
            "source": chunk.source,
            "hints": list(chunk.hints),
        }
        for chunk in chunks
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _project_intake_evidence(record: dict) -> dict:
    """Keep only source fields safe for recall evidence."""
    normalized = normalize_node(record)
    return {
        key: value
        for key, value in normalized.items()
        if key in _INTAKE_EVIDENCE_FIELDS or key == "table"
    }


def _select_claim(
    rows: list[dict], now: datetime, max_chars: int
) -> tuple[str, list[Any]] | None:
    """Select one intake's contiguous eligible queue rows for a lease."""
    if max_chars < 0:
        return None
    current = _coerce_datetime(now) or now.replace(tzinfo=UTC)

    def eligible(row: dict) -> bool:
        state = row.get("state")
        if state == "ready":
            return True
        if state == "retry_wait":
            retry_at = _coerce_datetime(row.get("next_attempt_at"))
            return retry_at is not None and retry_at <= current
        if state == "leased":
            expires_at = _coerce_datetime(row.get("lease_expires_at"))
            return expires_at is not None and expires_at <= current
        return False

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        intake_id = row.get("intake_id")
        if isinstance(intake_id, str):
            grouped.setdefault(intake_id, []).append(row)

    candidates: list[tuple[datetime, str, list[dict]]] = []
    for intake_id, intake_rows in grouped.items():
        ordered = sorted(
            intake_rows,
            key=lambda row: (
                row.get("chunk_index", 0),
                _coerce_datetime(row.get("created_at")) or current,
            ),
        )
        if any(row.get("paused") is True for row in ordered):
            continue
        if any(
            row.get("state") == "leased"
            and (_coerce_datetime(row.get("lease_expires_at")) or current) > current
            for row in ordered
        ):
            continue
        if not ordered or not eligible(ordered[0]):
            continue
        created_times = [
            created
            for row in ordered
            if (created := _coerce_datetime(row.get("created_at"))) is not None
        ]
        oldest = min(created_times) if created_times else current
        candidates.append((oldest, intake_id, ordered))

    if not candidates:
        return None
    _, intake_id, ordered = min(candidates, key=lambda item: (item[0], item[1]))
    selected: list[Any] = []
    total_chars = 0
    for row in ordered:
        if not eligible(row):
            break
        chars = row.get("chars", 0)
        try:
            row_chars = max(0, int(chars))
        except (TypeError, ValueError):
            row_chars = 0
        # Always lease the head row, even when it exceeds the budget.
        if selected and total_chars + row_chars > max_chars:
            break
        selected.append(row.get("id"))
        total_chars += row_chars
    return intake_id, selected


def _rrf_fuse(paths: list[list[dict]], k: int) -> list[dict]:
    """Fuse ranked paths with reciprocal rank fusion."""
    if k <= 0:
        return []
    scores: dict[str, float] = {}
    records: dict[str, dict] = {}
    for path in paths:
        for rank, record in enumerate(path[:k]):
            record_id = record.get("id")
            if record_id is None:
                continue
            rid = make_serializable(record_id)
            scores[rid] = scores.get(rid, 0.0) + 1 / (60 + rank + 1)
            records[rid] = record
    ranked_ids = sorted(scores, key=lambda rid: scores[rid], reverse=True)[:k]
    return [records[rid] for rid in ranked_ids]


def _summarize_queue(rows: list[dict], now: datetime) -> IntakeQueueSnapshot:
    """Summarize queue rows into bounded operational visibility."""
    current = _coerce_datetime(now) or now.replace(tzinfo=UTC)
    counts = {"ready": 0, "leased": 0, "retry_wait": 0, "paused": 0}
    ready_times: list[datetime] = []
    retry_times: list[datetime] = []
    live_tokens: set[str] = set()
    grouped_stuck: dict[str, list[dict]] = {}
    grouped_errors: dict[str, dict] = {}

    for row in rows:
        state = row.get("state")
        if state in counts:
            counts[state] += 1
        created_at = _coerce_datetime(row.get("created_at"))
        if state == "ready" and created_at is not None:
            ready_times.append(created_at)
        retry_at = _coerce_datetime(row.get("next_attempt_at"))
        if state == "retry_wait" and retry_at is not None:
            retry_times.append(retry_at)
        lease_expiry = _coerce_datetime(row.get("lease_expires_at"))
        lease_token = row.get("lease_token")
        if (
            state == "leased"
            and isinstance(lease_token, str)
            and lease_expiry is not None
            and lease_expiry > current
        ):
            live_tokens.add(lease_token)

        intake_id = row.get("intake_id")
        if not isinstance(intake_id, str):
            continue
        if state in {"retry_wait", "paused"}:
            grouped_stuck.setdefault(intake_id, []).append(row)
        error = row.get("last_error")
        if error:
            updated_at = _coerce_datetime(row.get("updated_at")) or current
            previous = grouped_errors.get(intake_id)
            if previous is None or updated_at >= previous["at"]:
                grouped_errors[intake_id] = {
                    "intake_id": intake_id,
                    "error": str(error),
                    "at": updated_at,
                }

    stuck: list[dict] = []
    for intake_id, intake_rows in grouped_stuck.items():
        latest = max(
            intake_rows,
            key=lambda row: (
                _coerce_datetime(row.get("updated_at")) or current,
                row.get("chunk_index", 0),
            ),
        )
        transition_times = [
            value
            for stuck_row in intake_rows
            if (value := _coerce_datetime(stuck_row.get("updated_at"))) is not None
        ]
        since = min(transition_times) if transition_times else current
        stuck.append(
            {
                "intake_id": intake_id,
                "state": latest.get("state"),
                "attempt_count": max(
                    int(row.get("attempt_count", 0) or 0) for row in intake_rows
                ),
                "last_error": latest.get("last_error"),
                "since": since,
            }
        )
    stuck.sort(key=lambda item: item["since"])

    recent_errors = sorted(grouped_errors.values(), key=lambda item: item["at"])[-20:]
    return IntakeQueueSnapshot(
        ready=counts["ready"],
        leased=counts["leased"],
        retry_wait=counts["retry_wait"],
        paused=counts["paused"],
        oldest_ready_at=min(ready_times) if ready_times else None,
        oldest_retry_at=min(retry_times) if retry_times else None,
        worker_count=0,
        active_leases=len(live_tokens),
        stuck_intakes=stuck[:100],
        recent_errors=recent_errors,
    )


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

        -- Synchronous intake queue
        DEFINE TABLE IF NOT EXISTS intake_chunk SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS intake_id ON intake_chunk TYPE string;
        DEFINE FIELD IF NOT EXISTS chunk_index ON intake_chunk TYPE int;
        DEFINE FIELD IF NOT EXISTS total_chunks ON intake_chunk TYPE int;
        DEFINE FIELD IF NOT EXISTS content ON intake_chunk TYPE string;
        DEFINE FIELD IF NOT EXISTS source ON intake_chunk TYPE string;
        DEFINE FIELD IF NOT EXISTS hints ON intake_chunk TYPE array<string>;
        DEFINE FIELD IF NOT EXISTS embedding ON intake_chunk TYPE option<array<float>>;
        DEFINE FIELD IF NOT EXISTS state ON intake_chunk TYPE string;
        DEFINE FIELD IF NOT EXISTS attempt_count ON intake_chunk TYPE int DEFAULT 0;
        DEFINE FIELD IF NOT EXISTS next_attempt_at ON intake_chunk TYPE option<datetime>;
        DEFINE FIELD IF NOT EXISTS lease_token ON intake_chunk TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS lease_expires_at ON intake_chunk TYPE option<datetime>;
        DEFINE FIELD IF NOT EXISTS worker_id ON intake_chunk TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS last_error ON intake_chunk TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS idempotency_key ON intake_chunk TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS paused ON intake_chunk TYPE bool DEFAULT false;
        DEFINE FIELD IF NOT EXISTS created_at ON intake_chunk TYPE datetime;
        DEFINE FIELD IF NOT EXISTS updated_at ON intake_chunk TYPE datetime;
        DEFINE INDEX IF NOT EXISTS intake_chunk_content_fts ON intake_chunk FIELDS content
            SEARCH ANALYZER simple_analyzer BM25;
        DEFINE INDEX IF NOT EXISTS intake_chunk_intake_id ON intake_chunk FIELDS intake_id;
        DEFINE INDEX IF NOT EXISTS intake_chunk_state ON intake_chunk FIELDS state;

        DEFINE TABLE IF NOT EXISTS intake_key SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS intake_id ON intake_key TYPE string;
        DEFINE FIELD IF NOT EXISTS fingerprint ON intake_key TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS chunk_count ON intake_key TYPE option<int>;
    """)


async def init_vector_indexes(db: AsyncSurreal, dimensions: int | None = None) -> None:  # pyright: ignore[reportGeneralTypeIssues]
    """Define HNSW vector indexes. Idempotent."""
    dim = dimensions or settings.embedding_dimensions
    await db.query(f"""
        DEFINE INDEX IF NOT EXISTS note_embedding_hnsw ON note
            FIELDS embedding HNSW DIMENSION {dim} DIST COSINE;
        DEFINE INDEX IF NOT EXISTS entity_embedding_hnsw ON entity
            FIELDS embedding HNSW DIMENSION {dim} DIST COSINE;
        DEFINE INDEX IF NOT EXISTS intake_chunk_embedding_hnsw ON intake_chunk
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

    def __init__(
        self,
        url: str,
        embedder: Embedder,
        dimensions: int,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Wrap a DB connection.

        Args:
            url: ``'mem://'`` for tests, ``'surrealkv://path'`` for prod.
            embedder: Embedding provider conforming to the Embedder protocol.
            dimensions: Vector dimensions for HNSW indexes.
            clock: Timezone-aware UTC clock for queue lease and retry decisions.
                Defaults to the current UTC time.
        """
        self._url = url
        self._embedder = embedder
        self._dimensions = dimensions
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._db: AsyncSurreal | None = None  # pyright: ignore[reportGeneralTypeIssues]
        self._transaction_lock = asyncio.Lock()

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

    async def _run_transaction(
        self, sql: str, vars: dict[str, Any], context: str
    ) -> Any:
        """Run a multi-statement transaction and classify its failures."""
        assert self._db is not None
        async with self._transaction_lock:
            raw = await self._db.query_raw(sql, vars)
        statement_results = raw.get("result", []) if isinstance(raw, dict) else []
        if not isinstance(statement_results, list):
            raise RuntimeError(f"{context}: invalid transaction response")
        last_result: Any = None
        errors: list[str] = []
        retryable_errors: list[str] = []
        for statement in statement_results:
            if not isinstance(statement, dict):
                continue
            status = statement.get("status")
            result = statement.get("result")
            if status == "ERR":
                message = str(result)
                lowered = message.lower()
                if "can be retried" in lowered or "intake_conflict" in lowered:
                    retryable_errors.append(message)
                else:
                    errors.append(message)
            else:
                last_result = result
        if retryable_errors:
            raise _RetryableConflict(retryable_errors[-1])
        if errors:
            error = next(
                (
                    message
                    for message in errors
                    if "query was not executed due to a failed transaction"
                    not in message.lower()
                ),
                errors[-1],
            )
            raise RuntimeError(f"{context}: {error}")
        return last_result

    async def _retry_transaction(
        self, attempt: Callable[[], Awaitable[_T]], attempts: int = 8
    ) -> _T:
        """Retry a transaction after an embedded Surreal conflict."""
        max_attempts = max(1, attempts)
        for number in range(max_attempts):
            try:
                return await attempt()
            except _RetryableConflict:
                if number + 1 >= max_attempts:
                    raise
                # Yield to another worker before replaying the read/claim.
                await asyncio.sleep(0)
        raise RuntimeError("transaction retry loop exhausted")

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
        """Fetch a single node by record ID. Returns ``{}`` if not found. Excludes embeddings.

        Raises ``ValueError`` for a malformed record ID (agent output is not
        trusted to be well-formed).
        """
        assert self._db is not None
        validate_record_id(record_id)
        result = await self._db.query(f"SELECT * OMIT embedding FROM {record_id}")
        result = self._check(result, f"get_node({record_id})")
        if not result:
            return {}
        if record_id.split(":", 1)[0] == "intake_chunk":
            return _project_intake_evidence(self._normalize(result[0]))
        return self._normalize(result[0])

    async def get_nodes(self, record_ids: list[str]) -> list[dict]:
        """Fetch multiple nodes by ID. Excludes embeddings. Skips missing or malformed IDs."""
        if not record_ids:
            return []
        results = []
        for rid in record_ids:
            try:
                node = await self.get_node(rid)
            except ValueError:
                logger.warning("get_nodes: skipping malformed record ID %r", rid)
                continue
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

    async def update_node(
        self, record_id: str, fields: dict, *, touch_updated_at: bool = True
    ) -> dict:
        """Update node fields. Auto re-embeds if text fields changed (content/name/description).

        Args:
            record_id: The node to update.
            fields: Field values to set.
            touch_updated_at: If True (default), sets ``updated_at`` to now.
                Pass False for bookkeeping updates (e.g. dream_age) that
                shouldn't change the last-meaningful-edit timestamp.
        """
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
        for k in fields:
            if k != "embedding":
                validate_identifier(k)
        validate_record_id(record_id)
        set_clauses = ", ".join(f"{k} = ${k}" for k in fields)
        if touch_updated_at:
            query = f"UPDATE {record_id} SET {set_clauses}, updated_at = time::now()"
        else:
            query = f"UPDATE {record_id} SET {set_clauses}"
        result = await self._db.query(query, fields)
        result = self._check(result, f"update_node({record_id})")
        if not result:
            return {}
        return self._normalize(result[0])

    async def delete_node(self, record_id: str) -> None:
        """Delete a node by record ID."""
        assert self._db is not None
        validate_record_id(record_id)
        await self._db.query(f"DELETE {record_id}")

    # ── Edges ──

    async def get_edge(self, edge_id: str) -> dict:
        """Fetch a single edge by ID. Returns ``{}`` if not found.

        Raises ``ValueError`` for a malformed record ID (agent output is not
        trusted to be well-formed).
        """
        assert self._db is not None
        validate_record_id(edge_id)
        result = await self._db.query(f"SELECT * FROM {edge_id}")
        result = self._check(result, f"get_edge({edge_id})")
        if not result:
            return {}
        return self._normalize(result[0])

    async def get_outgoing_edges(self, record_id: str) -> list[dict]:
        """All edges from this node. Each has ``id``, ``in``, ``out`` as plain strings, plus edge-specific fields."""
        assert self._db is not None
        validate_record_id(record_id)
        result = await self._db.query(f"SELECT * FROM {record_id}->?")
        result = self._check(result, f"get_outgoing_edges({record_id})")
        return [self._normalize(e) for e in result]

    async def get_incoming_edges(self, record_id: str) -> list[dict]:
        """All edges into this node."""
        assert self._db is not None
        validate_record_id(record_id)
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
        validate_record_id(from_id)
        validate_record_id(to_id)
        validate_identifier(edge_table)
        query = f"RELATE {from_id}->{edge_table}->{to_id}"
        if fields:
            set_parts = ", ".join(f"{k} = ${k}" for k in fields)
            query += f" SET {set_parts}"
            result = await self._db.query(query, fields)
        else:
            result = await self._db.query(query)
        result = self._check(result, f"create_edge({from_id}->{edge_table}->{to_id})")
        if not result:
            return {}
        return self._normalize(result[0])

    async def delete_edge(self, edge_id: str) -> None:
        """Delete an edge by ID."""
        assert self._db is not None
        validate_record_id(edge_id)
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

    async def _vector_candidates(
        self, table: str, embedding: list[float], k: int
    ) -> list[dict]:
        """Return normalized vector candidates for a validated memory table."""
        if table not in _SEARCH_FIELDS:
            raise ValueError(f"Invalid table for search: {table}")
        if k <= 0:
            return []
        assert self._db is not None
        result = await self._db.query(
            f"SELECT * OMIT embedding FROM {table} WHERE embedding <|{k},100|> $vec",
            {"vec": embedding},
        )
        rows = self._check(result, f"vector_search on {table}")
        normalized = [normalize_node(self._normalize(row)) for row in rows]
        if table == "intake_chunk":
            return [_project_intake_evidence(row) for row in normalized]
        return normalized

    async def _fulltext_candidates(self, table: str, query: str, k: int) -> list[dict]:
        """Return normalized BM25 candidates for a validated memory table."""
        if table not in _SEARCH_FIELDS:
            raise ValueError(f"Invalid table for search: {table}")
        if k <= 0:
            return []
        assert self._db is not None
        field = _SEARCH_FIELDS[table]
        result = await self._db.query(
            f"SELECT *, search::score(1) AS score OMIT embedding "
            f"FROM {table} WHERE {field} @1@ $query "
            f"ORDER BY score DESC LIMIT {k}",
            {"query": query},
        )
        rows = self._check(result, f"fulltext_search on {table}")
        normalized: list[dict] = []
        for row in rows:
            record = dict(row)
            record.pop("score", None)
            normalized_record = normalize_node(self._normalize(record))
            if table == "intake_chunk":
                normalized_record = _project_intake_evidence(normalized_record)
            normalized.append(normalized_record)
        return normalized

    async def search_memory_candidates(
        self, query: str, k: int
    ) -> MemorySearchCandidates:
        """Embed once and return best-first BM25/vector lists for each memory table."""
        query_embedding = await self._embedder.embed(query)
        return MemorySearchCandidates(
            note=RankedSearchCandidates(
                bm25=await self._fulltext_candidates("note", query, k),
                vector=await self._vector_candidates("note", query_embedding, k),
            ),
            entity=RankedSearchCandidates(
                bm25=await self._fulltext_candidates("entity", query, k),
                vector=await self._vector_candidates("entity", query_embedding, k),
            ),
            intake_chunk=RankedSearchCandidates(
                bm25=await self._fulltext_candidates("intake_chunk", query, k),
                vector=await self._vector_candidates(
                    "intake_chunk", query_embedding, k
                ),
            ),
        )

    async def hybrid_search(
        self, table: str, query_text: str, k: int = 5
    ) -> list[dict]:
        """BM25 + vector search with RRF fusion. Auto-embeds the query text."""
        if table not in _SEARCH_FIELDS:
            raise ValueError(f"Invalid table for search: {table}")
        query_embedding = await self._embedder.embed(query_text)
        vector = await self._vector_candidates(table, query_embedding, k)
        fulltext = await self._fulltext_candidates(table, query_text, k)
        return _rrf_fuse([vector, fulltext], k)

    async def vector_search(
        self, table: str, query_embedding: list[float], k: int = 5
    ) -> list[dict]:
        """Vector similarity search with a pre-computed embedding."""
        return await self._vector_candidates(table, query_embedding, k)

    async def fulltext_search(
        self, table: str, query_text: str, k: int = 5
    ) -> list[dict]:
        """BM25 full-text search."""
        return await self._fulltext_candidates(table, query_text, k)

    # ── Graph ──

    async def get_connections(self, record_id: str) -> list[dict]:
        """Edge neighborhood: ``[{edge_label, direction, adjacent_id}, ...]`` for a node."""
        assert self._db is not None
        validate_record_id(record_id)
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

    # ── Intake queue ──

    async def create_intake_chunks(
        self,
        intake_id: str,
        chunks: list[IntakeChunkDraft],
        idempotency_key: str | None,
    ) -> int:
        """Persist and embed all chunks for one intake document atomically."""
        if not chunks:
            return 0
        assert self._db is not None
        fingerprint = _intake_fingerprint(chunks)

        if idempotency_key is not None:
            existing = await self._db.query(
                "SELECT * FROM type::thing('intake_key', $key)",
                {"key": idempotency_key},
            )
            existing_rows = self._check(
                existing, "create_intake_chunks idempotency lookup"
            )
            if existing_rows:
                key_row = existing_rows[0]
                existing_intake_id = make_serializable(key_row.get("intake_id"))
                if not isinstance(existing_intake_id, str):
                    raise RuntimeError(
                        "create_intake_chunks: invalid idempotency record"
                    )
                remaining = await self._db.query(
                    "SELECT id FROM intake_chunk WHERE intake_id = $intake_id",
                    {"intake_id": existing_intake_id},
                )
                remaining_rows = self._check(
                    remaining, "create_intake_chunks idempotency rows"
                )
                if remaining_rows:
                    existing_fingerprint = key_row.get("fingerprint")
                    if existing_fingerprint is None:
                        existing_fingerprint = _intake_fingerprint(
                            [
                                IntakeChunkDraft(
                                    chunk_index=int(row.get("chunk_index", 0)),
                                    total_chunks=int(row.get("total_chunks", 0)),
                                    content=str(row.get("content", "")),
                                    source=str(row.get("source", "api")),
                                    hints=tuple(row.get("hints", ())),
                                )
                                for row in self._check(
                                    await self._db.query(
                                        "SELECT chunk_index, total_chunks, content, source, hints "
                                        "FROM intake_chunk WHERE intake_id = $intake_id "
                                        "ORDER BY chunk_index",
                                        {"intake_id": existing_intake_id},
                                    ),
                                    "create_intake_chunks idempotency fingerprint",
                                )
                            ]
                        )
                    if str(existing_fingerprint) != fingerprint:
                        raise IdempotencyConflict(
                            "Idempotency-Key was already used for different intake content"
                        )
                    return 0
                # A crash can leave the key after its final row deletion. Reclaim it.
                self._check(
                    await self._db.query(
                        "DELETE FROM intake_key WHERE id = type::thing('intake_key', $key) "
                        "AND intake_id = $existing_intake_id",
                        {
                            "key": idempotency_key,
                            "existing_intake_id": existing_intake_id,
                        },
                    ),
                    "create_intake_chunks orphan key cleanup",
                )

        contents = [chunk.content for chunk in chunks]
        embeddings = await self._embedder.embed_batch(contents)
        if len(embeddings) != len(chunks):
            raise RuntimeError("create_intake_chunks: embedding count mismatch")

        now = _coerce_datetime(self._clock()) or datetime.now(UTC)
        rows: list[dict[str, Any]] = []
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            rows.append(
                {
                    "intake_id": intake_id,
                    "chunk_index": chunk.chunk_index,
                    "total_chunks": chunk.total_chunks,
                    "content": chunk.content,
                    "source": chunk.source,
                    "hints": list(chunk.hints),
                    "embedding": embedding,
                    "state": "ready",
                    "paused": False,
                    "attempt_count": 0,
                    "next_attempt_at": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "worker_id": None,
                    "last_error": None,
                    "idempotency_key": idempotency_key,
                    "created_at": now,
                    "updated_at": now,
                }
            )

        variables: dict[str, Any] = {
            "intake_id": intake_id,
            "count": len(rows),
            "fingerprint": fingerprint,
        }
        statements = ["BEGIN TRANSACTION;"]
        if idempotency_key is not None:
            variables["key"] = idempotency_key
            statements.append(
                "CREATE type::thing('intake_key', $key) SET intake_id = $intake_id, "
                "fingerprint = $fingerprint, chunk_count = $count;"
            )
        for index, row in enumerate(rows):
            variable_name = f"row_{index}"
            variables[variable_name] = row
            statements.append(f"CREATE intake_chunk CONTENT ${variable_name};")
        statements.extend(["COMMIT TRANSACTION;", "RETURN $count;"])

        async def write() -> int:
            result = await self._run_transaction(
                "\n".join(statements), variables, "create_intake_chunks"
            )
            return int(result or 0)

        try:
            return await self._retry_transaction(write)
        except RuntimeError as exc:
            if idempotency_key is not None and "already exists" in str(exc).lower():
                winner = await self._db.query(
                    "SELECT * FROM type::thing('intake_key', $key)",
                    {"key": idempotency_key},
                )
                winner_rows = self._check(winner, "create_intake_chunks winner lookup")
                if winner_rows:
                    winner_row = winner_rows[0]
                    winner_fingerprint = winner_row.get("fingerprint")
                    if (
                        winner_fingerprint is not None
                        and str(winner_fingerprint) != fingerprint
                    ):
                        raise IdempotencyConflict(
                            "Idempotency-Key was already used for different intake content"
                        ) from exc
                    return 0
                raise
            raise

    async def claim_intake_batch(
        self,
        worker_id: str,
        max_chars: int,
        lease_seconds: float,
    ) -> ClaimedBatch | None:
        """Atomically lease contiguous chunks from one eligible intake document."""
        assert self._db is not None
        db = self._db

        async def claim() -> ClaimedBatch | None:
            result = await db.query(
                "SELECT id, intake_id, chunk_index, state, paused, next_attempt_at, "
                "lease_expires_at, created_at, string::len(content) AS chars "
                "FROM intake_chunk"
            )
            rows = self._check(result, "claim_intake_batch select")
            now = _coerce_datetime(self._clock()) or datetime.now(UTC)
            selected = _select_claim(rows, now, max_chars)
            if selected is None:
                return None
            intake_id, record_ids = selected
            if not record_ids:
                return None
            lease_token = uuid4().hex
            lease_expires_at = now + timedelta(seconds=lease_seconds)
            variables: dict[str, Any] = {
                "intake_id": intake_id,
                "ids": record_ids,
                "now": now,
                "lease_token_value": lease_token,
                "expiry": lease_expires_at,
                "worker_id": worker_id,
            }
            sql = """
                BEGIN TRANSACTION;
                LET $paused = (SELECT count() AS count FROM intake_chunk
                    WHERE intake_id = $intake_id AND paused = true GROUP ALL);
                IF array::len($paused) > 0 AND $paused[0].count > 0 {
                    THROW 'intake_conflict';
                };
                LET $live = (SELECT count() AS count FROM intake_chunk
                    WHERE intake_id = $intake_id
                    AND state = 'leased'
                    AND lease_expires_at > $now GROUP ALL);
                IF array::len($live) > 0 AND $live[0].count > 0 {
                    THROW 'intake_conflict';
                };
                LET $invalid = (SELECT count() AS count FROM intake_chunk
                    WHERE id IN $ids
                    AND (paused = true OR NOT (
                        state = 'ready'
                        OR (state = 'retry_wait' AND next_attempt_at <= $now)
                        OR (state = 'leased' AND lease_expires_at <= $now)
                    )) GROUP ALL);
                IF array::len($invalid) > 0 AND $invalid[0].count > 0 {
                    THROW 'intake_conflict';
                };
                UPDATE intake_chunk SET
                    state = 'leased',
                    lease_token = $lease_token_value,
                    lease_expires_at = $expiry,
                    worker_id = $worker_id,
                    updated_at = $now
                    WHERE id IN $ids;
                COMMIT TRANSACTION;
                RETURN (SELECT * OMIT embedding FROM intake_chunk
                    WHERE id IN $ids AND lease_token = $lease_token_value
                    ORDER BY chunk_index ASC);
            """
            leased_rows = await self._run_transaction(
                sql, variables, "claim_intake_batch"
            )
            if not isinstance(leased_rows, list):
                return None
            normalized = [
                normalize_node(self._normalize(row))
                for row in leased_rows
                if isinstance(row, dict)
            ]
            normalized.sort(key=lambda row: row.get("chunk_index", 0))
            if not normalized:
                return None
            return ClaimedBatch(
                lease_token=lease_token,
                intake_id=intake_id,
                chunks=normalized,
            )

        try:
            return await self._retry_transaction(claim)
        except _RetryableConflict:
            # Another worker won the claim after our eligibility read.
            return None

    async def renew_intake_batch(self, lease_token: str, lease_seconds: float) -> int:
        """Extend a live lease and return the number of rows renewed."""
        assert self._db is not None
        now = _coerce_datetime(self._clock()) or datetime.now(UTC)
        expiry = now + timedelta(seconds=lease_seconds)
        result = await self._db.query(
            "UPDATE intake_chunk SET lease_expires_at = $expiry, updated_at = $now "
            "WHERE lease_token = $lease_token AND state = 'leased' "
            "AND lease_expires_at > $now",
            {"lease_token": lease_token, "expiry": expiry, "now": now},
        )
        rows = self._check(result, "renew_intake_batch")
        return len(rows)

    async def release_intake_batch(
        self,
        lease_token: str,
        error: str,
        next_attempt_at: datetime,
    ) -> None:
        """Return a failed lease to retry-wait without changing newer leases."""
        assert self._db is not None
        now = _coerce_datetime(self._clock()) or datetime.now(UTC)
        retry_at = _coerce_datetime(next_attempt_at) or next_attempt_at
        variables = {
            "lease_token": lease_token,
            "error": error,
            "next_attempt_at": retry_at,
            "now": now,
        }
        result = await self._db.query(
            "UPDATE intake_chunk SET "
            "state = 'retry_wait', "
            "last_error = $error, "
            "next_attempt_at = $next_attempt_at, "
            "attempt_count = attempt_count + 1, "
            "lease_token = NONE, "
            "lease_expires_at = NONE, "
            "worker_id = NONE, "
            "updated_at = $now "
            "WHERE lease_token = $lease_token AND state = 'leased' AND paused != true",
            variables,
        )
        self._check(result, "release_intake_batch")
        paused_result = await self._db.query(
            "UPDATE intake_chunk SET "
            "state = 'paused', "
            "last_error = $error, "
            "next_attempt_at = NONE, "
            "attempt_count = attempt_count + 1, "
            "lease_token = NONE, "
            "lease_expires_at = NONE, "
            "worker_id = NONE, "
            "updated_at = $now "
            "WHERE lease_token = $lease_token AND state = 'leased' AND paused = true",
            variables,
        )
        self._check(paused_result, "release_intake_batch paused")

    async def delete_intake_batch(self, lease_token: str) -> int:
        """Delete a successful lease's rows without changing newer leases."""
        assert self._db is not None
        db = self._db
        variables = {"lease_token": lease_token}
        sql = """
            BEGIN TRANSACTION;
            LET $matching = (SELECT intake_id FROM intake_chunk
                WHERE lease_token = $lease_token AND state = 'leased');
            LET $count = count($matching);
            LET $intakes = array::distinct($matching.intake_id);
            DELETE FROM intake_chunk
                WHERE lease_token = $lease_token AND state = 'leased';
            COMMIT TRANSACTION;
            RETURN {count: $count, intakes: $intakes};
        """
        result = await self._run_transaction(sql, variables, "delete_intake_batch")
        if not isinstance(result, dict):
            return 0
        intake_ids = result.get("intakes", [])
        if not isinstance(intake_ids, list):
            intake_ids = []
        for intake_id in intake_ids:
            if not isinstance(intake_id, str):
                continue
            # The embedded engine does not provide read-your-writes for an
            # aggregate SELECT inside the delete transaction. Check after
            # commit, with a conditional delete, so partial processing retains
            # its idempotency key.
            cleanup = await db.query(
                "DELETE FROM intake_key WHERE intake_id = $intake_id "
                "AND count((SELECT * FROM intake_chunk "
                "WHERE intake_id = $intake_id)) = 0",
                {"intake_id": intake_id},
            )
            self._check(cleanup, "delete_intake_batch idempotency cleanup")
        return int(result.get("count", 0) or 0)

    async def get_intake_chunks(self, record_ids: list[str]) -> list[dict]:
        """Fetch intake evidence by ID, omitting deleted rows and embeddings."""
        assert self._db is not None
        records: list[dict] = []
        for record_id in record_ids:
            try:
                validate_record_id(record_id)
            except ValueError:
                logger.warning(
                    "get_intake_chunks: skipping malformed record ID %r", record_id
                )
                continue
            if record_id.split(":", 1)[0] != "intake_chunk":
                continue
            result = await self._db.query(f"SELECT * OMIT embedding FROM {record_id}")
            rows = self._check(result, f"get_intake_chunks({record_id})")
            if rows:
                records.append(_project_intake_evidence(self._normalize(rows[0])))
        return records

    async def search_intake_chunks(self, query: str, k: int) -> list[dict]:
        """Search queued chunks for queue consumers without embedding arrays."""
        assert self._db is not None
        embedding = await self._embedder.embed(query)
        vector = await self._vector_candidates("intake_chunk", embedding, k)
        fulltext = await self._fulltext_candidates("intake_chunk", query, k)
        fused = _rrf_fuse([vector, fulltext], k)
        # This queue-facing helper retains operational fields for worker tests
        # and diagnostics. Public recall uses search_memory_candidates instead.
        records: list[dict] = []
        for candidate in fused:
            record_id = candidate.get("id")
            if not isinstance(record_id, str):
                continue
            result = await self._db.query(f"SELECT * OMIT embedding FROM {record_id}")
            rows = self._check(result, f"search_intake_chunks({record_id})")
            if rows:
                records.append(normalize_node(self._normalize(rows[0])))
        return records

    async def intake_queue_snapshot(self) -> IntakeQueueSnapshot:
        """Return aggregate queue counts and bounded operational errors."""
        assert self._db is not None
        result = await self._db.query(
            "SELECT * OMIT content, embedding FROM intake_chunk"
        )
        rows = self._check(result, "intake_queue_snapshot")
        return _summarize_queue(
            rows, _coerce_datetime(self._clock()) or datetime.now(UTC)
        )

    async def set_intake_paused(self, intake_id: str, paused: bool) -> int:
        """Persist pause intent for every remaining row in one intake."""
        assert self._db is not None
        now = _coerce_datetime(self._clock()) or datetime.now(UTC)
        existing = await self._db.query(
            "SELECT id FROM intake_chunk WHERE intake_id = $intake_id",
            {"intake_id": intake_id},
        )
        existing_rows = self._check(
            existing, f"set_intake_paused lookup({intake_id}, {paused})"
        )
        if not existing_rows:
            return 0
        variables = {"intake_id": intake_id, "now": now}
        if paused:
            flag_result = await self._db.query(
                "UPDATE intake_chunk SET paused = true, updated_at = $now "
                "WHERE intake_id = $intake_id",
                variables,
            )
            self._check(flag_result, f"set_intake_paused flag({intake_id})")
            state_result = await self._db.query(
                "UPDATE intake_chunk SET state = 'paused', updated_at = $now "
                "WHERE intake_id = $intake_id AND state IN ['ready', 'retry_wait']",
                variables,
            )
            self._check(state_result, f"set_intake_paused state({intake_id})")
        else:
            flag_result = await self._db.query(
                "UPDATE intake_chunk SET paused = false, updated_at = $now "
                "WHERE intake_id = $intake_id",
                variables,
            )
            self._check(flag_result, f"set_intake_resumed flag({intake_id})")
            state_result = await self._db.query(
                "UPDATE intake_chunk SET state = 'ready', next_attempt_at = NONE, "
                "updated_at = $now WHERE intake_id = $intake_id AND state = 'paused'",
                variables,
            )
            self._check(state_result, f"set_intake_resumed state({intake_id})")
        return len(existing_rows)

    async def delete_intake(self, intake_id: str) -> int:
        """Delete all remaining queue rows and idempotency keys for one intake."""
        sql = """
            BEGIN TRANSACTION;
            LET $rows = (SELECT id FROM intake_chunk WHERE intake_id = $intake_id);
            LET $count = count($rows);
            DELETE FROM intake_chunk WHERE intake_id = $intake_id;
            DELETE FROM intake_key WHERE intake_id = $intake_id;
            COMMIT TRANSACTION;
            RETURN $count;
        """
        result = await self._run_transaction(
            sql, {"intake_id": intake_id}, "delete_intake"
        )
        return int(result or 0)
