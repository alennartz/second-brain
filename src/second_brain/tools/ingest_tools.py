# pyright: reportGeneralTypeIssues=false
import logging

from second_brain.db import Storage
from second_brain.validation import validate_identifier, validate_record_id

logger = logging.getLogger(__name__)


async def create_edges(
    storage: Storage,
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

        # Validate inputs (prevents malformed SurrealQL)
        validate_record_id(from_id)
        validate_record_id(to_id)
        validate_identifier(edge_table)

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
        existing = await storage.check_edge_exists(from_id, edge_table, to_id)
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

        fields = {"context": context} if context else None
        rec = await storage.create_edge(from_id, edge_table, to_id, fields)
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
    storage: Storage,
    entities: list[dict],
    notes: list[dict],
    edges: list[dict],
) -> dict:
    """Create entities, notes, and edges in one call with reference resolution.

    Edges can reference items created in this call via 'new_entity:N' or
    'new_note:N', or existing record IDs.

    Returns a summary dict with entities_created, notes_created,
    edges_created, edges_skipped, and errors.
    """
    errors: list[str] = []
    storage_errors: list[str] = []

    # 1. Create entities and collect IDs
    entity_records = await storage.create_entities(entities) if entities else []
    entities_created = []
    for i, rec in enumerate(entity_records):
        ref = f"new_entity:{i}"
        entities_created.append(
            {"ref": ref, "id": rec["id"], "name": entities[i]["name"]}
        )

    # 2. Create notes and collect IDs
    notes_created = []
    try:
        note_records = await storage.create_notes(notes) if notes else []
        for i, rec in enumerate(note_records):
            ref = f"new_note:{i}"
            notes_created.append({"ref": ref, "id": rec["id"]})
    except Exception as e:
        message = f"Note creation failed: {e}"
        errors.append(message)
        storage_errors.append(message)

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
            validate_identifier(edge["edge_table"])
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
    try:
        if resolved_edges:
            edge_results = await create_edges(storage, resolved_edges)
            for r in edge_results:
                if r.get("skipped"):
                    edges_skipped += 1
                else:
                    edges_created += 1
    except Exception as e:
        message = f"Edge creation failed: {e}"
        errors.append(message)
        storage_errors.append(message)

    # 6. Return summary
    return {
        "entities_created": entities_created,
        "notes_created": notes_created,
        "edges_created": edges_created,
        "edges_skipped": edges_skipped,
        "errors": errors,
        "storage_errors": storage_errors,
    }
