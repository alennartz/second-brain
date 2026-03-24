"""Shared validation helpers for SurrealDB identifiers and query results."""

import re
from typing import Any

# table:id — table part is a lowercase identifier, id part allows
# alphanumerics, underscores, hyphens, and the angle-bracket quoting
# SurrealDB uses for numeric-looking keys (⟨ ⟩).
_RECORD_ID_RE = re.compile(r"^[a-z_][a-z0-9_]*:[a-zA-Z0-9_⟨⟩-]+$")

# Plain SurrealQL identifier: table names, field names, edge tables.
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def validate_record_id(record_id: str) -> str:
    """Validate that *record_id* is a well-formed SurrealDB record ID.

    Raises ``ValueError`` if the format doesn't match
    ``table:id`` with safe characters.  Returns the unchanged
    *record_id* on success.
    """
    if not _RECORD_ID_RE.match(record_id):
        raise ValueError(f"Invalid record ID: {record_id!r}")
    return record_id


def validate_identifier(name: str) -> str:
    """Validate that *name* is a safe SurrealQL identifier.

    Covers table names, field names, and edge table names.
    Raises ``ValueError`` if the format doesn't match.
    Returns the unchanged *name* on success.
    """
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


def check_query_result(result: Any, context: str) -> list:
    """Ensure a ``db.query()`` return value is a result list, not an error.

    SurrealDB's Python driver sometimes returns an error string instead
    of raising an exception.  This helper turns that into a proper
    ``RuntimeError`` so callers don't silently swallow failures.

    Returns *result* unchanged when it is a ``list``, or an empty list
    for any other non-error type.
    """
    if isinstance(result, str):
        raise RuntimeError(f"{context}: {result}")
    if isinstance(result, list):
        return result
    return []
