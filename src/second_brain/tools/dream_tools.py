import asyncio
import logging

from second_brain.db import Storage

logger = logging.getLogger(__name__)


async def find_similar(
    storage: Storage,
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
    table = record_id.split(":")[0]
    field = "content" if table == "note" else "name"

    # Fetch the source node's embedding and name/content for BM25 query
    source_node = await storage.get_node(record_id)
    if not source_node:
        logger.warning("find_similar: node not found %s", record_id)
        return []

    query_text = source_node.get(field, "")
    source_embedding = await storage.get_node_field(record_id, "embedding")

    # --- Vector search (if embedding exists) ---
    vs_results: list[dict] = []
    if source_embedding:
        vs_raw = await storage.vector_search(table, source_embedding, k + 1)
        vs_results = [r for r in vs_raw if r["id"] != record_id]

    # --- BM25 full-text search on name/content ---
    ft_results: list[dict] = []
    if query_text:
        ft_raw = await storage.fulltext_search(table, query_text, k + 1)
        ft_results = [r for r in ft_raw if r["id"] != record_id]

    # --- Reciprocal rank fusion ---
    rrf_k = 60
    scores: dict[str, float] = {}
    records: dict[str, dict] = {}

    for rank, rec in enumerate(vs_results):
        rid = rec["id"]
        scores[rid] = scores.get(rid, 0) + 1 / (rrf_k + rank + 1)
        records[rid] = rec

    for rank, rec in enumerate(ft_results):
        rid = rec["id"]
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
        rec = dict(records[rid])
        rec.pop("similarity", None)
        rec.pop("score", None)
        cleaned.append(rec)
    return cleaned


async def merge_nodes(
    storage: Storage,
    ids: list[str],
    new_fields: dict,
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
    if len(ids) < 2:
        raise ValueError("merge_nodes requires at least 2 IDs")

    survivor_id = ids[0]
    loser_ids = ids[1:]

    # Compute max dream_age across all input nodes
    all_ages: list[int] = []
    for nid in ids:
        age = await storage.get_node_field(nid, "dream_age")
        all_ages.append(age or 0)
    max_age = max(all_ages) if all_ages else 0

    # Update survivor with new fields + dream_age (auto re-embeds text fields)
    await storage.update_node(survivor_id, {**new_fields, "dream_age": max_age})

    touched_ids = list(ids)
    edges_auto_merged: list[dict] = []  # track which edges got deduped

    # Re-point edges from each loser to survivor
    for loser_id in loser_ids:
        # Outgoing edges: loser->X becomes survivor->X
        out_edges = await storage.get_outgoing_edges(loser_id)
        for edge in out_edges:
            edge_id = edge["id"]
            edge_table = edge_id.split(":")[0]
            target_id = edge["out"]
            touched_ids.append(edge_id)

            # Skip self-edges (loser->survivor becomes survivor->survivor)
            if target_id == survivor_id:
                await storage.delete_edge(edge_id)
                continue

            # Preserve all edge fields except id/in/out
            preserved = {k: v for k, v in edge.items() if k not in ("id", "in", "out")}

            # Check if survivor already has same edge
            existing = await storage.check_edge_exists(
                survivor_id, edge_table, target_id
            )
            if existing:
                # Duplicate: merge dream_age, delete both, recreate with max age
                existing_edge = existing[0]
                existing_eid = existing_edge["id"]
                existing_age = existing_edge.get("dream_age") or 0
                edge_age = preserved.get("dream_age") or 0
                new_age = max(edge_age, existing_age)

                # Preserve existing edge fields, update dream_age
                existing_fields = {
                    k: v
                    for k, v in existing_edge.items()
                    if k not in ("id", "in", "out")
                }
                existing_fields["dream_age"] = new_age

                await storage.delete_edge(existing_eid)
                await storage.delete_edge(edge_id)
                await storage.create_edge(
                    survivor_id, edge_table, target_id, existing_fields
                )

                edges_auto_merged.append(
                    {
                        "kept": existing_eid,
                        "deleted": edge_id,
                        "table": edge_table,
                        "target": target_id,
                    }
                )
                touched_ids.append(existing_eid)
            else:
                # Re-point: delete old, create new with all preserved fields
                await storage.delete_edge(edge_id)
                await storage.create_edge(survivor_id, edge_table, target_id, preserved)

        # Incoming edges: X->loser becomes X->survivor
        in_edges = await storage.get_incoming_edges(loser_id)
        for edge in in_edges:
            edge_id = edge["id"]
            edge_table = edge_id.split(":")[0]
            source_id = edge["in"]
            touched_ids.append(edge_id)

            # Skip self-edges
            if source_id == survivor_id:
                await storage.delete_edge(edge_id)
                continue

            # Preserve all edge fields except id/in/out
            preserved = {k: v for k, v in edge.items() if k not in ("id", "in", "out")}

            # Check if survivor already has same incoming edge
            existing = await storage.check_edge_exists(
                source_id, edge_table, survivor_id
            )
            if existing:
                existing_edge = existing[0]
                existing_eid = existing_edge["id"]
                existing_age = existing_edge.get("dream_age") or 0
                edge_age = preserved.get("dream_age") or 0
                new_age = max(edge_age, existing_age)

                existing_fields = {
                    k: v
                    for k, v in existing_edge.items()
                    if k not in ("id", "in", "out")
                }
                existing_fields["dream_age"] = new_age

                await storage.delete_edge(existing_eid)
                await storage.delete_edge(edge_id)
                await storage.create_edge(
                    source_id, edge_table, survivor_id, existing_fields
                )

                edges_auto_merged.append(
                    {
                        "kept": existing_eid,
                        "deleted": edge_id,
                        "table": edge_table,
                        "source": source_id,
                    }
                )
                touched_ids.append(existing_eid)
            else:
                # Re-point: delete old, create new with all preserved fields
                await storage.delete_edge(edge_id)
                await storage.create_edge(source_id, edge_table, survivor_id, preserved)

        # Delete the loser node
        await storage.delete_node(loser_id)

    survivor = await storage.get_node(survivor_id)
    return {
        "survivor": survivor,
        "touched_ids": list(set(touched_ids)),
        "edges_auto_merged": edges_auto_merged,
    }


async def explore(
    storage: Storage,
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
    depth = min(depth, 3)
    node_types = node_types or ["entity", "note"]

    visited = {record_id}
    # BFS: each entry is (node_id, path_so_far)
    queue: list[tuple[str, list[dict]]] = [(record_id, [])]
    targets: list[dict] = []

    for _ in range(depth):
        next_queue: list[tuple[str, list[dict]]] = []
        for current_id, path in queue:
            neighbors: list[tuple[str, str, str]] = []

            if direction in ("out", "both"):
                out_edges = await storage.get_outgoing_edges(current_id)
                for edge in out_edges:
                    eid = edge["id"]
                    label = eid.split(":")[0]
                    neighbor_id = edge["out"]
                    neighbors.append((neighbor_id, label, eid))

            if direction in ("in", "both"):
                in_edges = await storage.get_incoming_edges(current_id)
                for edge in in_edges:
                    eid = edge["id"]
                    label = eid.split(":")[0]
                    neighbor_id = edge["in"]
                    neighbors.append((neighbor_id, label, eid))

            for neighbor_id, label, edge_id in neighbors:
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                new_path = [
                    *path,
                    {"edge_id": edge_id, "edge_label": label, "node_id": neighbor_id},
                ]
                neighbor_table = neighbor_id.split(":")[0]

                if neighbor_table in node_types:
                    node = await storage.get_node(neighbor_id)
                    if node:
                        targets.append(
                            {
                                "node": node,
                                "path": new_path,
                            }
                        )

                # Continue traversal regardless of whether this node matched filter
                next_queue.append((neighbor_id, new_path))

        queue = next_queue

    return {"targets": targets}


async def find_unlinked_cooccurrences(
    storage: Storage,
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
    table = record_id.split(":")[0]
    if table != "entity":
        return []

    # Find all notes that reference this entity.
    # RELATE note->references->entity creates in=note, out=entity.
    # So entity<-references gives edges where out=entity; in=note.
    in_edges = await storage.get_incoming_edges(record_id)
    ref_edges = [e for e in in_edges if e["id"].startswith("references:")]
    if not ref_edges:
        return []

    note_ids = [e["in"] for e in ref_edges]

    # For each note, find other entities it references
    cooccurrences: dict[str, list[str]] = {}  # other_entity_id -> [note_ids]
    for note_id in note_ids:
        out_edges = await storage.get_outgoing_edges(note_id)
        ref_out = [e for e in out_edges if e["id"].startswith("references:")]
        for ref in ref_out:
            other_id = ref["out"]
            if other_id == record_id:
                continue
            other_table = other_id.split(":")[0]
            if other_table != "entity":
                continue
            cooccurrences.setdefault(other_id, []).append(note_id)

    # Pre-fetch edges for direct-edge checking (both directions)
    all_out = await storage.get_outgoing_edges(record_id)
    out_targets = {e["out"] for e in all_out}
    in_sources = {e["in"] for e in in_edges}

    # Filter out entities that already have a direct edge (either direction)
    results = []
    for other_id, shared_notes in cooccurrences.items():
        # Check record_id -> other_id (outgoing) or other_id -> record_id (incoming)
        if other_id in out_targets or other_id in in_sources:
            continue

        # Fetch the other entity's content
        other = await storage.get_node(other_id)
        if not other:
            continue

        # Fetch shared note content so the agent can read what the text says
        note_contents = []
        for nid in set(shared_notes):
            note = await storage.get_node(nid)
            if note:
                note_contents.append(
                    {"id": note["id"], "content": note.get("content", "")}
                )

        results.append(
            {
                "entity": other,
                "shared_notes": note_contents,
            }
        )

    return results


async def merge_edges(
    storage: Storage,
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
    if len(ids) < 2:
        raise ValueError("merge_edges requires at least 2 IDs")

    survivor_id = ids[0]
    loser_ids = ids[1:]

    # Fetch all edge records and validate they connect the same node pair
    all_ages: list[int] = []
    expected_in: str | None = None
    expected_out: str | None = None
    survivor_table: str | None = None
    for eid in ids:
        rec = await storage.get_edge(eid)
        if not rec:
            raise ValueError(f"Edge {eid} not found")
        all_ages.append(rec.get("dream_age") or 0)
        edge_in = rec["in"]
        edge_out = rec["out"]
        if expected_in is None:
            expected_in = edge_in
            expected_out = edge_out
            survivor_table = eid.split(":")[0]
        elif edge_in != expected_in or edge_out != expected_out:
            return {
                "error": (
                    f"Cannot merge edges with different node pairs: "
                    f"expected {expected_in}->{expected_out} but "
                    f"{eid} connects {edge_in}->{edge_out}"
                )
            }
    max_age = max(all_ages) if all_ages else 0

    assert expected_in is not None
    assert expected_out is not None
    assert survivor_table is not None

    # Delete survivor and recreate with new fields (no update_edge in Storage)
    fields: dict = {"dream_age": max_age}
    if new_context is not None:
        fields["context"] = new_context

    await storage.delete_edge(survivor_id)
    new_survivor = await storage.create_edge(
        expected_in, survivor_table, expected_out, fields
    )

    # Delete losers
    for lid in loser_ids:
        await storage.delete_edge(lid)

    return {
        "survivor": new_survivor,
        "deleted_ids": loser_ids,
    }
