# pyright: reportGeneralTypeIssues=false
# AsyncSurreal is typed as a factory function in the surrealdb SDK, not a class.
import logging

from surrealdb import AsyncSurreal

logger = logging.getLogger(__name__)


async def create_note(
    db: AsyncSurreal,
    content: str,
    source: str,
    summary: str | None = None,
    embedding: list[float] | None = None,
) -> dict:
    """Create a new note in the knowledge base."""
    data: dict = {"content": content, "source": source}
    if summary:
        data["summary"] = summary
    if embedding:
        data["embedding"] = embedding
    result = await db.create("note", data)
    # db.create() returns a single dict in this SDK version
    rec = result if isinstance(result, dict) else result[0]
    logger.info("db: created note id=%s (%d chars)", rec.get("id"), len(content))
    return rec


async def create_entity(
    db: AsyncSurreal,
    name: str,
    type: str,
    description: str | None = None,
    embedding: list[float] | None = None,
) -> dict:
    """Create a new entity (concept, person, project, etc.)."""
    data: dict = {"name": name, "type": type}
    if description:
        data["description"] = description
    if embedding:
        data["embedding"] = embedding
    result = await db.create("entity", data)
    rec = result if isinstance(result, dict) else result[0]
    logger.info("db: created entity id=%s name='%s' type=%s", rec.get("id"), name, type)
    return rec


async def create_edge(
    db: AsyncSurreal,
    from_id: str,
    edge_table: str,
    to_id: str,
    context: str | None = None,
) -> dict:
    """Create a relationship edge between two nodes."""
    ctx_clause = " SET context = $context" if context else ""
    query = f"RELATE {from_id}->{edge_table}->{to_id}{ctx_clause}"
    result = await db.query(
        query,
        {"context": context} if context else None,
    )
    # db.query() returns a flat list of dicts
    rec = result[0] if result else {}
    logger.info(
        "db: created edge %s -[%s]-> %s id=%s",
        from_id,
        edge_table,
        to_id,
        rec.get("id"),
    )
    return rec


async def update_node(db: AsyncSurreal, record_id: str, fields: dict) -> dict:
    """Update fields on an existing node."""
    set_clauses = ", ".join(f"{k} = ${k}" for k in fields)
    result = await db.query(
        f"UPDATE {record_id} SET {set_clauses}, updated_at = time::now()",
        fields,
    )
    # db.query() returns a flat list of dicts
    rec = result[0] if result else {}
    logger.info("db: updated node id=%s fields=%s", record_id, list(fields.keys()))
    return rec
