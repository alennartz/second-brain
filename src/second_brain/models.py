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


class Context(BaseModel):
    """Curated graph context returned by recall/converse responses."""

    nodes: list[dict] = []
    edges: list[dict] = []
