# pyright: reportGeneralTypeIssues=false
# AsyncSurreal is typed as a factory function in the surrealdb SDK, not a class.
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from surrealdb import AsyncSurreal

from second_brain.models import make_serializable
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


def _resolve_ref(ref: str, ref_map: dict[str, str]) -> str:
    """Resolve a reference string to a record ID.

    - 'new_entity:N' / 'new_note:N' → look up in ref_map
    - Otherwise validate as an existing record ID

    Raises ValueError if the ref is invalid or out of bounds.
    """
    if ref.startswith("new_entity:") or ref.startswith("new_note:"):
        if ref not in ref_map:
            raise ValueError(f"Reference {ref!r} not found (out of bounds)")
        return ref_map[ref]
    # Must be an existing record ID
    return validate_record_id(ref)


async def store_knowledge(
    db: AsyncSurreal,
    entities: list[dict],
    notes: list[dict],
    edges: list[dict],
    embed_fn: Callable[[str], Awaitable[list[float]]],
) -> dict:
    """Create entities, notes, and edges in one call with reference resolution.

    Edges can reference items created in this call via 'new_entity:N' or
    'new_note:N', or existing record IDs.

    Returns a summary dict with entities_created, notes_created,
    edges_created, edges_skipped, and errors.
    """
    errors: list[str] = []

    # 1. Create entities and collect IDs
    entity_records = await create_entities(db, entities, embed_fn) if entities else []
    entities_created = []
    for i, rec in enumerate(entity_records):
        ref = f"new_entity:{i}"
        serialized_id = make_serializable(rec["id"])
        entities_created.append(
            {"ref": ref, "id": serialized_id, "name": entities[i]["name"]}
        )

    # 2. Create notes and collect IDs
    note_records = await create_notes(db, notes, embed_fn) if notes else []
    notes_created = []
    for i, rec in enumerate(note_records):
        ref = f"new_note:{i}"
        serialized_id = make_serializable(rec["id"])
        notes_created.append({"ref": ref, "id": serialized_id})

    # 3. Build ref map
    ref_map: dict[str, str] = {}
    for item in entities_created:
        ref_map[item["ref"]] = item["id"]
    for item in notes_created:
        ref_map[item["ref"]] = item["id"]

    # 4. Resolve and filter edges
    resolved_edges: list[dict] = []
    edges_skipped = 0
    for edge in edges:
        from_ref = edge["from_ref"]
        to_ref = edge["to_ref"]
        try:
            from_id = _resolve_ref(from_ref, ref_map)
            to_id = _resolve_ref(to_ref, ref_map)
        except ValueError as e:
            errors.append(str(e))
            edges_skipped += 1
            continue

        # Check for self-edges
        if from_id == to_id:
            edges_skipped += 1
            continue

        resolved_edge: dict = {
            "from_id": from_id,
            "edge_table": edge["edge_table"],
            "to_id": to_id,
        }
        if edge.get("context"):
            resolved_edge["context"] = edge["context"]
        resolved_edges.append(resolved_edge)

    # 5. Create edges
    edges_created = 0
    if resolved_edges:
        edge_results = await create_edges(db, resolved_edges)
        for r in edge_results:
            if r.get("skipped"):
                edges_skipped += 1
            else:
                edges_created += 1

    # 6. Return summary
    return {
        "entities_created": entities_created,
        "notes_created": notes_created,
        "edges_created": edges_created,
        "edges_skipped": edges_skipped,
        "errors": errors,
    }


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
