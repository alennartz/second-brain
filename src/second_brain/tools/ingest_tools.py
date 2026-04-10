# pyright: reportGeneralTypeIssues=false
# AsyncSurreal is typed as a factory function in the surrealdb SDK, not a class.
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from surrealdb import AsyncSurreal

from second_brain.validation import (
    check_query_result,
    validate_identifier,
    validate_record_id,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class BatchEmbedder(Protocol):
    """Embedding callable that also supports batch embedding."""

    async def __call__(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


async def create_notes(
    db: AsyncSurreal,
    notes: list[dict],
    embed_fn: Callable[[str], Awaitable[list[float]]],
) -> list[dict]:
    """Create multiple notes. Each dict needs 'content', optional 'source' and 'summary'."""
    contents = [n["content"] for n in notes]
    if isinstance(embed_fn, BatchEmbedder):
        embeddings = await embed_fn.embed_batch(contents)
    else:
        embeddings = [await embed_fn(c) for c in contents]

    results = []
    for note, embedding in zip(notes, embeddings, strict=True):
        content = note["content"]
        source = note.get("source", "api")
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
    texts = [e.get("description") or e["name"] for e in entities]
    if isinstance(embed_fn, BatchEmbedder):
        embeddings = await embed_fn.embed_batch(texts)
    else:
        embeddings = [await embed_fn(t) for t in texts]

    results = []
    for entity, embedding in zip(entities, embeddings, strict=True):
        name = entity["name"]
        etype = entity["type"]
        description = entity.get("description")
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
        from_id = validate_record_id(edge["from_id"])
        edge_table = validate_identifier(edge["edge_table"])
        to_id = validate_record_id(edge["to_id"])
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
        existing = check_query_result(
            existing, f"duplicate check {from_id}->{edge_table}->{to_id}"
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
        result = check_query_result(result, f"RELATE {from_id}->{edge_table}->{to_id}")
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
    if not fields:
        return {"error": "No fields to update"}
    record_id = validate_record_id(record_id)
    for k in fields:
        validate_identifier(k)
    set_clauses = ", ".join(f"{k} = ${k}" for k in fields)
    result = await db.query(
        f"UPDATE {record_id} SET {set_clauses}, updated_at = time::now()",
        fields,
    )
    result = check_query_result(result, f"UPDATE {record_id}")
    rec = result[0] if result else {}
    logger.info("db: updated node id=%s fields=%s", record_id, list(fields.keys()))
    return rec
