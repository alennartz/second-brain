"""Shared validation helpers for SurrealDB identifiers."""

import re

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
