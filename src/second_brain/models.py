"""Shared models and serialization utilities."""

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


class Context(BaseModel):
    """Curated graph context returned by recall/converse responses."""

    nodes: list[dict] = []
    edges: list[dict] = []
