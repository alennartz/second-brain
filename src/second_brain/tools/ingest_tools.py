# pyright: reportGeneralTypeIssues=false
# AsyncSurreal is typed as a factory function in the surrealdb SDK, not a class.
import logging
from collections.abc import Awaitable, Callable

from surrealdb import AsyncSurreal

logger = logging.getLogger(__name__)


async def create_notes(
    db: AsyncSurreal,
    notes: list[dict],
    embed_fn: Callable[[str], Awaitable[list[float]]],
) -> list[dict]:
    """Create multiple notes. Each dict needs 'content', optional 'source' and 'summary'."""
    results = []
    for note in notes:
        content = note["content"]
        source = note.get("source", "api")
        embedding = await embed_fn(content)
        data: dict = {"content": content, "source": source, "embedding": embedding}
        if note.get("summary"):
            data["summary"] = note["summary"]
        result = await db.create("note", data)
        rec = result if isinstance(result, dict) else result[0]
        logger.info("db: created note id=%s (%d chars)", rec.get("id"), len(content))
        results.append(rec)
    return results


async def create_entities(
    db: AsyncSurreal,
    entities: list[dict],
    embed_fn: Callable[[str], Awaitable[list[float]]],
) -> list[dict]:
    """Create multiple entities. Each dict needs 'name', 'type', optional 'description'."""
    results = []
    for entity in entities:
        name = entity["name"]
        etype = entity["type"]
        description = entity.get("description")
        text_to_embed = description or name
        embedding = await embed_fn(text_to_embed)
        data: dict = {"name": name, "type": etype, "embedding": embedding}
        if description:
            data["description"] = description
        result = await db.create("entity", data)
        rec = result if isinstance(result, dict) else result[0]
        logger.info(
            "db: created entity id=%s name='%s' type=%s", rec.get("id"), name, etype
        )
        results.append(rec)
    return results


async def create_edges(
    db: AsyncSurreal,
    edges: list[dict],
) -> list[dict]:
    """Create multiple relationship edges. Each dict needs 'from_id', 'edge_table', 'to_id', optional 'context'.

    Skips self-edges (from_id == to_id) and duplicate edges (same from/table/to already exists).
    """
    results = []
    for edge in edges:
        from_id = edge["from_id"]
        edge_table = edge["edge_table"]
        to_id = edge["to_id"]
        context = edge.get("context")

        # Reject self-edges
        if from_id == to_id:
            logger.warning(
                "db: skipping self-edge %s -[%s]-> %s", from_id, edge_table, to_id
            )
            results.append(
                {
                    "skipped": True,
                    "reason": "self-edge",
                    "from_id": from_id,
                    "to_id": to_id,
                }
            )
            continue

        # Reject duplicate edges (same from, table, to already exists)
        existing = await db.query(
            f"SELECT id FROM {from_id}->{edge_table} WHERE out = {to_id}"
        )
        if existing:
            logger.warning(
                "db: skipping duplicate edge %s -[%s]-> %s", from_id, edge_table, to_id
            )
            results.append(
                {
                    "skipped": True,
                    "reason": "duplicate",
                    "from_id": from_id,
                    "to_id": to_id,
                }
            )
            continue

        ctx_clause = " SET context = $context" if context else ""
        query = f"RELATE {from_id}->{edge_table}->{to_id}{ctx_clause}"
        result = await db.query(query, {"context": context} if context else None)
        rec = result[0] if result else {}
        logger.info(
            "db: created edge %s -[%s]-> %s id=%s",
            from_id,
            edge_table,
            to_id,
            rec.get("id"),
        )
        results.append(rec)
    return results


async def update_node(db: AsyncSurreal, record_id: str, fields: dict) -> dict:
    """Update fields on an existing node."""
    set_clauses = ", ".join(f"{k} = ${k}" for k in fields)
    result = await db.query(
        f"UPDATE {record_id} SET {set_clauses}, updated_at = time::now()",
        fields,
    )
    rec = result[0] if result else {}
    logger.info("db: updated node id=%s fields=%s", record_id, list(fields.keys()))
    return rec
