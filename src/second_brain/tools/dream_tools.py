# pyright: reportGeneralTypeIssues=false
# AsyncSurreal is typed as a factory function in the surrealdb SDK, not a class.
import asyncio
import logging
from collections.abc import Awaitable, Callable

from surrealdb import AsyncSurreal, RecordID

from second_brain.models import make_serializable
from second_brain.validation import check_query_result, validate_record_id

logger = logging.getLogger(__name__)


def _to_str(val) -> str:
    """Convert a RecordID or other value to a plain string like 'table:id'."""
    if isinstance(val, RecordID):
        return f"{val.table_name}:{val.id}"
    return str(val)


async def find_similar(
    db: AsyncSurreal,
    record_id: str,
    k: int = 5,
) -> list[dict]:
    """Find candidate duplicates using hybrid search (vector + BM25 on name).

    Combines embedding similarity with full-text name matching so that
    exact-name duplicates always surface, even when their descriptions
    differ enough to push embeddings apart.  Similarity scores are stripped
    from results — the caller should judge by reading names, types, and
    descriptions, not by thresholding a number.
    """
    validate_record_id(record_id)
    table = record_id.split(":")[0]
    field = "content" if table == "note" else "name"

    # Fetch the source node's embedding and name/content for BM25 query
    source = check_query_result(
        await db.query(f"SELECT * OMIT embedding FROM {record_id}"),
        f"fetch source for {record_id}",
    )
    if not source:
        logger.warning("find_similar: node not found %s", record_id)
        return []

    source_node = source[0]
    query_text = source_node.get(field, "")

    source_emb_result = check_query_result(
        await db.query(f"SELECT embedding FROM {record_id}"),
        f"fetch embedding for {record_id}",
    )
    source_embedding = (
        source_emb_result[0].get("embedding") if source_emb_result else None
    )

    # --- Vector search (if embedding exists) ---
    vs_results: list[dict] = []
    if source_embedding:
        vs_raw = check_query_result(
            await db.query(
                f"SELECT * OMIT embedding FROM {table} "
                f"WHERE embedding <|{k + 1},100|> $vec",
                {"vec": source_embedding},
            ),
            f"vector search on {table}",
        )
        vs_results = [r for r in vs_raw if _to_str(r["id"]) != record_id]

    # --- BM25 full-text search on name/content ---
    ft_results: list[dict] = []
    if query_text:
        ft_raw = await db.query(
            f"SELECT *, search::score(1) AS score OMIT embedding "
            f"FROM {table} WHERE {field} @1@ $query "
            f"ORDER BY score DESC LIMIT {k + 1}",
            {"query": query_text},
        )
        if isinstance(ft_raw, list):
            ft_results = [r for r in ft_raw if _to_str(r["id"]) != record_id]

    # --- Reciprocal rank fusion ---
    rrf_k = 60
    scores: dict[str, float] = {}
    records: dict[str, dict] = {}

    for rank, rec in enumerate(vs_results):
        rid = _to_str(rec["id"])
        scores[rid] = scores.get(rid, 0) + 1 / (rrf_k + rank + 1)
        records[rid] = rec

    for rank, rec in enumerate(ft_results):
        rid = _to_str(rec["id"])
        scores[rid] = scores.get(rid, 0) + 1 / (rrf_k + rank + 1)
        records[rid] = rec

    ranked_ids = sorted(scores, key=lambda rid: scores[rid], reverse=True)[:k]

    logger.info(
        "find_similar %s: vs=%d ft=%d fused=%d",
        record_id,
        len(vs_results),
        len(ft_results),
        len(ranked_ids),
    )

    # Strip scores — the dedup agent should judge by reading, not by number
    cleaned = []
    for rid in ranked_ids:
        rec = make_serializable(records[rid])
        rec.pop("similarity", None)
        rec.pop("score", None)
        cleaned.append(rec)
    return cleaned


async def merge_nodes(
    db: AsyncSurreal,
    ids: list[str],
    new_fields: dict,
    embed_fn: Callable[[str], Awaitable[list[float]]],
    cancel: asyncio.Event | None = None,
) -> dict:
    """Fuse N nodes into one. First ID is the survivor.

    - Updates survivor with new_fields and re-embeds
    - Re-points all edges from losers to survivor
    - Auto-merges duplicate edges (same table + direction + target)
      with dream_age = max(inputs)
    - Survivor gets dream_age = max(all input nodes)
    - Deletes loser nodes
    - Returns {"survivor": {...}, "touched_ids": [...]}
    """
    if cancel is not None and cancel.is_set():
        return {"cancelled": True}
    for rid in ids:
        validate_record_id(rid)
    if len(ids) < 2:
        raise ValueError("merge_nodes requires at least 2 IDs")

    survivor_id = ids[0]
    loser_ids = ids[1:]

    # Compute max dream_age across all input nodes
    all_ages: list[int] = []
    for nid in ids:
        rec = check_query_result(
            await db.query(f"SELECT dream_age FROM {nid}"),
            f"fetch dream_age for {nid}",
        )
        if rec:
            all_ages.append(rec[0].get("dream_age") or 0)
    max_age = max(all_ages) if all_ages else 0

    # Re-embed based on new fields
    text_to_embed = (
        new_fields.get("content")
        or new_fields.get("description")
        or new_fields.get("name", "")
    )
    new_embedding = await embed_fn(text_to_embed)

    # Update survivor with new fields + embedding + dream_age
    set_clauses = ", ".join(f"{k} = ${k}" for k in new_fields)
    check_query_result(
        await db.query(
            f"UPDATE {survivor_id} SET {set_clauses}, embedding = $emb, dream_age = $age, updated_at = time::now()",
            {**new_fields, "emb": new_embedding, "age": max_age},
        ),
        f"update survivor {survivor_id}",
    )

    touched_ids = list(ids)
    edges_auto_merged: list[dict] = []  # track which edges got deduped

    # Re-point edges from each loser to survivor
    for loser_id in loser_ids:
        # Outgoing edges: loser->X becomes survivor->X
        out_edges = check_query_result(
            await db.query(f"SELECT * FROM {loser_id}->?"),
            f"fetch outgoing edges for {loser_id}",
        )
        for edge in out_edges:
            edge_id = _to_str(edge["id"])
            edge_table = edge_id.split(":")[0]
            target_id = _to_str(edge["out"])
            touched_ids.append(edge_id)

            # Bug #3: skip self-edges
            if target_id == survivor_id:
                check_query_result(
                    await db.query(f"DELETE {edge_id}"),
                    f"delete self-edge {edge_id}",
                )
                continue

            # Preserve all edge fields except id/in/out
            preserved = {k: v for k, v in edge.items() if k not in ("id", "in", "out")}

            # Check if survivor already has same edge
            existing = check_query_result(
                await db.query(
                    f"SELECT * FROM {survivor_id}->{edge_table} WHERE out = {target_id}"
                ),
                f"check existing outgoing edge {survivor_id}->{edge_table}->{target_id}",
            )
            if existing:
                # Duplicate: merge dream_age, delete the loser edge
                existing_age = existing[0].get("dream_age") or 0
                existing_eid = _to_str(existing[0]["id"])
                edge_age = preserved.get("dream_age") or 0
                new_age = max(edge_age, existing_age)
                check_query_result(
                    await db.query(f"UPDATE {existing_eid} SET dream_age = {new_age}"),
                    f"update dream_age on {existing_eid}",
                )
                check_query_result(
                    await db.query(f"DELETE {edge_id}"),
                    f"delete duplicate edge {edge_id}",
                )
                edges_auto_merged.append(
                    {"kept": existing_eid, "deleted": edge_id, "table": edge_table, "target": target_id}
                )
                touched_ids.append(existing_eid)
            else:
                # Re-point: delete old, create new with all preserved fields
                set_clause = ", ".join(f"{k} = ${k}" for k in preserved)
                relate_stmt = f"RELATE {survivor_id}->{edge_table}->{target_id}"
                if set_clause:
                    relate_stmt += f" SET {set_clause}"
                check_query_result(
                    await db.query(f"DELETE {edge_id}"),
                    f"delete edge {edge_id}",
                )
                check_query_result(
                    await db.query(relate_stmt, preserved),
                    f"re-point outgoing edge to {survivor_id}->{edge_table}->{target_id}",
                )

        # Incoming edges: X->loser becomes X->survivor
        in_edges = check_query_result(
            await db.query(f"SELECT * FROM {loser_id}<-?"),
            f"fetch incoming edges for {loser_id}",
        )
        for edge in in_edges:
            edge_id = _to_str(edge["id"])
            edge_table = edge_id.split(":")[0]
            source_id = _to_str(edge["in"])
            touched_ids.append(edge_id)

            # Bug #3: skip self-edges
            if source_id == survivor_id:
                check_query_result(
                    await db.query(f"DELETE {edge_id}"),
                    f"delete self-edge {edge_id}",
                )
                continue

            # Preserve all edge fields except id/in/out
            preserved = {k: v for k, v in edge.items() if k not in ("id", "in", "out")}

            # Check if survivor already has same incoming edge
            existing = check_query_result(
                await db.query(
                    f"SELECT * FROM {source_id}->{edge_table} WHERE out = {survivor_id}"
                ),
                f"check existing incoming edge {source_id}->{edge_table}->{survivor_id}",
            )
            if existing:
                existing_age = existing[0].get("dream_age") or 0
                existing_eid = _to_str(existing[0]["id"])
                edge_age = preserved.get("dream_age") or 0
                new_age = max(edge_age, existing_age)
                check_query_result(
                    await db.query(f"UPDATE {existing_eid} SET dream_age = {new_age}"),
                    f"update dream_age on {existing_eid}",
                )
                check_query_result(
                    await db.query(f"DELETE {edge_id}"),
                    f"delete duplicate edge {edge_id}",
                )
                edges_auto_merged.append(
                    {"kept": existing_eid, "deleted": edge_id, "table": edge_table, "source": source_id}
                )
                touched_ids.append(existing_eid)
            else:
                # Re-point: delete old, create new with all preserved fields
                set_clause = ", ".join(f"{k} = ${k}" for k in preserved)
                relate_stmt = f"RELATE {source_id}->{edge_table}->{survivor_id}"
                if set_clause:
                    relate_stmt += f" SET {set_clause}"
                check_query_result(
                    await db.query(f"DELETE {edge_id}"),
                    f"delete edge {edge_id}",
                )
                check_query_result(
                    await db.query(relate_stmt, preserved),
                    f"re-point incoming edge to {source_id}->{edge_table}->{survivor_id}",
                )

        # Delete the loser node
        check_query_result(
            await db.query(f"DELETE {loser_id}"),
            f"delete loser node {loser_id}",
        )

    survivor = check_query_result(
        await db.query(f"SELECT * OMIT embedding FROM {survivor_id}"),
        f"fetch survivor {survivor_id}",
    )
    return {
        "survivor": make_serializable(survivor[0]) if survivor else {},
        "touched_ids": list(set(touched_ids)),
        "edges_auto_merged": edges_auto_merged,
    }


async def explore(
    db: AsyncSurreal,
    record_id: str,
    direction: str = "both",
    node_types: list[str] | None = None,
    depth: int = 2,
    cancel: asyncio.Event | None = None,
) -> dict:
    """Explore graph neighborhood from a node.

    Args:
        record_id: Starting node.
        direction: "out", "in", or "both".
        node_types: Filter target nodes by table (e.g., ["entity", "note"]).
        depth: Max hops (bounded to 3).
        cancel: Optional cancellation event.

    Returns:
        {"targets": [{"node": {...}, "path": [{"edge_id": ..., "edge_label": ..., "node_id": ...}, ...]}]}
        Target nodes have full content (embeddings stripped).
        Paths show edge IDs, edge labels (table names), and intermediate node IDs.
    """
    if cancel is not None and cancel.is_set():
        return {"cancelled": True}
    validate_record_id(record_id)
    depth = min(depth, 3)
    node_types = node_types or ["entity", "note"]

    visited = {record_id}
    # BFS: each entry is (node_id, path_so_far)
    queue: list[tuple[str, list[dict]]] = [(record_id, [])]
    targets: list[dict] = []

    for _ in range(depth):
        next_queue: list[tuple[str, list[dict]]] = []
        for current_id, path in queue:
            neighbors: list[tuple[str, str]] = []

            if direction in ("out", "both"):
                out_edges = check_query_result(
                    await db.query(f"SELECT * FROM {current_id}->?"),
                    f"fetch outgoing edges for {current_id}",
                )
                for edge in out_edges:
                    eid = _to_str(edge["id"])
                    label = eid.split(":")[0]
                    neighbor_id = _to_str(edge["out"])
                    neighbors.append((neighbor_id, label, eid))

            if direction in ("in", "both"):
                in_edges = check_query_result(
                    await db.query(f"SELECT * FROM {current_id}<-?"),
                    f"fetch incoming edges for {current_id}",
                )
                for edge in in_edges:
                    eid = _to_str(edge["id"])
                    label = eid.split(":")[0]
                    neighbor_id = _to_str(edge["in"])
                    neighbors.append((neighbor_id, label, eid))

            for neighbor_id, label, edge_id in neighbors:
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                new_path = [*path, {"edge_id": edge_id, "edge_label": label, "node_id": neighbor_id}]
                neighbor_table = neighbor_id.split(":")[0]

                if neighbor_table in node_types:
                    node = check_query_result(
                        await db.query(f"SELECT * OMIT embedding FROM {neighbor_id}"),
                        f"fetch node {neighbor_id}",
                    )
                    if node:
                        targets.append(
                            {
                                "node": make_serializable(node[0]),
                                "path": new_path,
                            }
                        )

                # Continue traversal regardless of whether this node matched filter
                next_queue.append((neighbor_id, new_path))

        queue = next_queue

    return {"targets": targets}


async def find_unlinked_cooccurrences(
    db: AsyncSurreal,
    record_id: str,
    cancel: asyncio.Event | None = None,
) -> list[dict] | dict:
    """Find entities that share notes with this entity but have no direct edge.

    Follows: entity <-references- note -references-> other_entity
    Filters out pairs that already have any direct edge between them.

    Returns: [{"entity": {...}, "shared_notes": ["note:x", ...]}, ...]
    """
    if cancel is not None and cancel.is_set():
        return {"cancelled": True}
    validate_record_id(record_id)
    table = record_id.split(":")[0]
    if table != "entity":
        return []

    # Find all notes that reference this entity.
    # RELATE note->references->entity creates in=note, out=entity.
    # So entity<-references gives edges where out=entity; in=note.
    notes = check_query_result(
        await db.query(f"SELECT * FROM {record_id}<-references"),
        f"fetch references for {record_id}",
    )
    if not notes:
        return []

    note_ids = [_to_str(n["in"]) for n in notes]

    # For each note, find other entities it references
    cooccurrences: dict[str, list[str]] = {}  # other_entity_id -> [note_ids]
    for note_id in note_ids:
        # note->references gives edges where in=note; out=entity
        refs = check_query_result(
            await db.query(f"SELECT * FROM {note_id}->references"),
            f"fetch references from {note_id}",
        )
        for ref in refs:
            other_id = _to_str(ref["out"])
            if other_id == record_id:
                continue
            other_table = other_id.split(":")[0]
            if other_table != "entity":
                continue
            cooccurrences.setdefault(other_id, []).append(note_id)

    # Filter out entities that already have a direct edge (either direction)
    results = []
    for other_id, shared_notes in cooccurrences.items():
        # Check for any direct edge in either direction
        out_edges = check_query_result(
            await db.query(f"SELECT * FROM {record_id}->? WHERE out = {other_id}"),
            f"check outgoing edges from {record_id} to {other_id}",
        )
        in_edges = check_query_result(
            await db.query(f"SELECT * FROM {other_id}->? WHERE out = {record_id}"),
            f"check outgoing edges from {other_id} to {record_id}",
        )
        if out_edges or in_edges:
            continue

        # Fetch the other entity's content
        other = check_query_result(
            await db.query(f"SELECT * OMIT embedding FROM {other_id}"),
            f"fetch entity {other_id}",
        )
        if not other:
            continue

        # Fetch shared note content so the agent can read what the text says
        note_contents = []
        for nid in set(shared_notes):
            note = check_query_result(
                await db.query(f"SELECT * OMIT embedding FROM {nid}"),
                f"fetch note {nid}",
            )
            if note:
                n = make_serializable(note[0])
                note_contents.append(
                    {"id": n["id"], "content": n.get("content", "")}
                )

        results.append(
            {
                "entity": make_serializable(other[0]),
                "shared_notes": note_contents,
            }
            )

    return results


async def merge_edges(
    db: AsyncSurreal,
    ids: list[str],
    new_context: str | None = None,
    cancel: asyncio.Event | None = None,
) -> dict:
    """Fuse N edges into one. First ID is the survivor.

    - Survivor gets new_context and dream_age = max(all inputs)
    - Losers are deleted
    - Returns {"survivor": {...}, "deleted_ids": [...]}
    """
    if cancel is not None and cancel.is_set():
        return {"cancelled": True}
    for rid in ids:
        validate_record_id(rid)
    if len(ids) < 2:
        raise ValueError("merge_edges requires at least 2 IDs")

    survivor_id = ids[0]
    loser_ids = ids[1:]

    # Fetch all edge records and validate they connect the same node pair
    all_ages: list[int] = []
    expected_in = None
    expected_out = None
    for eid in ids:
        rec = check_query_result(
            await db.query(f"SELECT * FROM {eid}"),
            f"fetch edge {eid}",
        )
        if not rec:
            raise ValueError(f"Edge {eid} not found")
        edge_rec = rec[0]
        all_ages.append(edge_rec.get("dream_age") or 0)
        edge_in = _to_str(edge_rec["in"])
        edge_out = _to_str(edge_rec["out"])
        if expected_in is None:
            expected_in = edge_in
            expected_out = edge_out
        elif edge_in != expected_in or edge_out != expected_out:
            return {
                "error": (
                    f"Cannot merge edges with different node pairs: "
                    f"expected {expected_in}->{expected_out} but "
                    f"{eid} connects {edge_in}->{edge_out}"
                )
            }
    max_age = max(all_ages) if all_ages else 0

    # Update survivor
    if new_context is not None:
        check_query_result(
            await db.query(
                f"UPDATE {survivor_id} SET context = $ctx, dream_age = $age",
                {"ctx": new_context, "age": max_age},
            ),
            f"update survivor edge {survivor_id}",
        )
    else:
        check_query_result(
            await db.query(f"UPDATE {survivor_id} SET dream_age = {max_age}"),
            f"update survivor edge {survivor_id}",
        )

    # Delete losers
    for lid in loser_ids:
        check_query_result(
            await db.query(f"DELETE {lid}"),
            f"delete loser edge {lid}",
        )

    survivor = check_query_result(
        await db.query(f"SELECT * FROM {survivor_id}"),
        f"fetch survivor edge {survivor_id}",
    )
    return {
        "survivor": make_serializable(survivor[0]) if survivor else {},
        "deleted_ids": loser_ids,
    }
