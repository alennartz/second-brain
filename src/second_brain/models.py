"""Shared models and serialization utilities."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from surrealdb import RecordID


def make_serializable(obj: Any) -> Any:
    """Convert SurrealDB types (RecordID, datetime, etc.) to JSON-safe values.

    RecordID is serialized as ``"table:id"`` without the angle-bracket
    quoting that ``str(RecordID)`` applies to numeric-looking keys.
    """
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_serializable(v) for v in obj]
    if isinstance(obj, RecordID):
        return f"{obj.table_name}:{obj.id}"
    if isinstance(obj, datetime):
        return obj.isoformat()
    # Convert any other non-primitive types to str
    if not isinstance(obj, (str, int, float, bool, type(None))):
        return str(obj)
    return obj


def _extract_table(record_id: str) -> str:
    """Extract the table name from a SurrealDB record ID like ``'note:abc'``."""
    return record_id.split(":")[0] if ":" in record_id else ""


def normalize_node(node: dict) -> dict:
    """Add a ``table`` field derived from the record ``id``."""
    out = dict(node)
    if "table" not in out and "id" in out:
        out["table"] = _extract_table(str(out["id"]))
    return out


def normalize_edge(edge: dict) -> dict:
    """Translate SurrealDB edge fields to the client API contract.

    SurrealDB stores ``in``/``out``; the client expects ``from``/``to``/``table``.
    """
    out = dict(edge)
    if "from" not in out and "in" in out:
        out["from"] = out.pop("in")
    if "to" not in out and "out" in out:
        out["to"] = out.pop("out")
    if "table" not in out and "id" in out:
        out["table"] = _extract_table(str(out["id"]))
    return out


@dataclass(frozen=True)
class IntakeRequest:
    """Raw intake submitted for synchronous staging."""

    text: str
    hints: tuple[str, ...] = ()
    source: str = "api"
    idempotency_key: str | None = None


@dataclass(frozen=True)
class EnqueueResult:
    """Result returned after every intake chunk is persisted and searchable."""

    chunks_stored: int


@dataclass(frozen=True)
class IntakeChunkDraft:
    """Chunk data supplied to the storage queue primitive."""

    chunk_index: int
    total_chunks: int
    content: str
    source: str = "api"
    hints: tuple[str, ...] = ()


@dataclass
class IntakeChunk:
    """Persisted intake chunk row exposed to queue consumers."""

    id: str
    intake_id: str
    chunk_index: int
    total_chunks: int
    content: str
    source: str = "api"
    hints: tuple[str, ...] = ()
    state: str = "ready"
    attempt_count: int = 0
    next_attempt_at: datetime | None = None
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    last_error: str | None = None
    idempotency_key: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class ClaimedBatch:
    """A leased, contiguous processing batch from one intake document."""

    lease_token: str
    intake_id: str
    chunks: list[dict]


@dataclass
class IntakeQueueSnapshot:
    """Operational queue counts and bounded error visibility."""

    ready: int = 0
    leased: int = 0
    retry_wait: int = 0
    paused: int = 0
    oldest_ready_at: datetime | None = None
    oldest_retry_at: datetime | None = None
    worker_count: int = 0
    active_leases: int = 0
    stuck_intakes: list[dict] = field(default_factory=list)
    recent_errors: list[dict] = field(default_factory=list)


@dataclass
class PipelineSnapshot(IntakeQueueSnapshot):
    """Aggregate worker-pipeline snapshot exposed to operators."""


@dataclass
class MemorySearchResult:
    """Graph evidence and explicitly unprocessed intake evidence."""

    nodes: list[dict] = field(default_factory=list)
    unprocessed: list[dict] = field(default_factory=list)


class Context(BaseModel):
    """Curated graph context returned by recall/converse responses."""

    nodes: list[dict] = []
    edges: list[dict] = []
    unprocessed: list[dict] = []
