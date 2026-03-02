# pyright: reportGeneralTypeIssues=false
# AsyncSurreal is typed as a factory function in the surrealdb SDK, not a class.
import logging
import math
from collections.abc import Awaitable, Callable

from surrealdb import AsyncSurreal, RecordID

from second_brain.models import make_serializable, strip_embeddings

logger = logging.getLogger(__name__)


def _to_str(val) -> str:
    """Convert a RecordID or other value to a plain string like 'table:id'."""
    if isinstance(val, RecordID):
        return f"{val.table_name}:{val.id}"
    return str(val)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def find_similar(
    db: AsyncSurreal,
    record_id: str,
    k: int = 5,
) -> list[dict]:
    """Find the k nearest same-table neighbors by embedding similarity.

    Returns results with similarity scores, embeddings stripped.
    Excludes the source node itself.
    """
    table = record_id.split(":")[0]

    # Fetch the source node's embedding
    source = await db.query(f"SELECT embedding FROM {record_id}")
    if not source or not source[0].get("embedding"):
        logger.warning("find_similar: no embedding for %s", record_id)
        return []
    source_embedding = source[0]["embedding"]

    # Vector search for nearest neighbors (fetch k+1 to account for self-match)
    results = await db.query(
        f"SELECT * FROM {table} WHERE embedding <|{k + 1},100|> $vec",
        {"vec": source_embedding},
    )
    if isinstance(results, str):
        raise RuntimeError(f"Vector search on {table} failed: {results}")

    # Filter out the source node, compute similarity, strip embeddings
    filtered = []
    for rec in results:
        rid = _to_str(rec["id"])
        if rid == record_id:
            continue
        sim = _cosine_similarity(source_embedding, rec.get("embedding", []))
        cleaned = strip_embeddings(make_serializable(rec))
        cleaned["similarity"] = round(sim, 4)
        filtered.append(cleaned)

    filtered.sort(key=lambda r: r["similarity"], reverse=True)
    return filtered[:k]


async def merge_nodes(
    db: AsyncSurreal,
    ids: list[str],
    new_fields: dict,
    embed_fn: Callable[[str], Awaitable[list[float]]],
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
    if len(ids) < 2:
        raise ValueError("merge_nodes requires at least 2 IDs")

    survivor_id = ids[0]
    loser_ids = ids[1:]

    # Compute max dream_age across all input nodes
    all_ages: list[int] = []
    for nid in ids:
        rec = await db.query(f"SELECT dream_age FROM {nid}")
        if rec:
            all_ages.append(rec[0].get("dream_age", 0))
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
    await db.query(
        f"UPDATE {survivor_id} SET {set_clauses}, embedding = $emb, dream_age = $age, updated_at = time::now()",
        {**new_fields, "emb": new_embedding, "age": max_age},
    )

    touched_ids = list(ids)

    # Re-point edges from each loser to survivor
    for loser_id in loser_ids:
        # Outgoing edges: loser->X becomes survivor->X
        out_edges = await db.query(f"SELECT * FROM {loser_id}->?")
        if isinstance(out_edges, list):
            for edge in out_edges:
                edge_id = _to_str(edge["id"])
                edge_table = edge_id.split(":")[0]
                target_id = _to_str(edge["out"])
                edge_age = edge.get("dream_age", 0)
                context = edge.get("context")
                touched_ids.append(edge_id)

                # Check if survivor already has same edge
                existing = await db.query(
                    f"SELECT * FROM {survivor_id}->{edge_table} WHERE out = {target_id}"
                )
                if existing:
                    # Duplicate: merge dream_age, delete the loser edge
                    existing_age = existing[0].get("dream_age", 0)
                    existing_eid = _to_str(existing[0]["id"])
                    new_age = max(edge_age, existing_age)
                    await db.query(f"UPDATE {existing_eid} SET dream_age = {new_age}")
                    await db.query(f"DELETE {edge_id}")
                    touched_ids.append(existing_eid)
                else:
                    # Re-point: delete old, create new
                    ctx_clause = (
                        " SET context = $ctx, dream_age = $age"
                        if context
                        else " SET dream_age = $age"
                    )
                    params: dict = {"age": edge_age}
                    if context:
                        params["ctx"] = context
                    await db.query(f"DELETE {edge_id}")
                    await db.query(
                        f"RELATE {survivor_id}->{edge_table}->{target_id}{ctx_clause}",
                        params,
                    )

        # Incoming edges: X->loser becomes X->survivor
        in_edges = await db.query(f"SELECT * FROM {loser_id}<-?")
        if isinstance(in_edges, list):
            for edge in in_edges:
                edge_id = _to_str(edge["id"])
                edge_table = edge_id.split(":")[0]
                source_id = _to_str(edge["in"])
                edge_age = edge.get("dream_age", 0)
                context = edge.get("context")
                touched_ids.append(edge_id)

                # Check if survivor already has same incoming edge
                existing = await db.query(
                    f"SELECT * FROM {source_id}->{edge_table} WHERE out = {survivor_id}"
                )
                if existing:
                    existing_age = existing[0].get("dream_age", 0)
                    existing_eid = _to_str(existing[0]["id"])
                    new_age = max(edge_age, existing_age)
                    await db.query(f"UPDATE {existing_eid} SET dream_age = {new_age}")
                    await db.query(f"DELETE {edge_id}")
                    touched_ids.append(existing_eid)
                else:
                    ctx_clause = (
                        " SET context = $ctx, dream_age = $age"
                        if context
                        else " SET dream_age = $age"
                    )
                    params = {"age": edge_age}
                    if context:
                        params["ctx"] = context
                    await db.query(f"DELETE {edge_id}")
                    await db.query(
                        f"RELATE {source_id}->{edge_table}->{survivor_id}{ctx_clause}",
                        params,
                    )

        # Delete the loser node
        await db.query(f"DELETE {loser_id}")

    survivor = await db.query(f"SELECT * FROM {survivor_id}")
    return {
        "survivor": strip_embeddings(make_serializable(survivor[0]))
        if survivor
        else {},
        "touched_ids": list(set(touched_ids)),
    }


async def merge_edges(
    db: AsyncSurreal,
    ids: list[str],
    new_context: str | None = None,
) -> dict:
    """Fuse N edges into one. First ID is the survivor.

    - Survivor gets new_context and dream_age = max(all inputs)
    - Losers are deleted
    - Returns {"survivor": {...}, "deleted_ids": [...]}
    """
    if len(ids) < 2:
        raise ValueError("merge_edges requires at least 2 IDs")

    survivor_id = ids[0]
    loser_ids = ids[1:]

    # Get max dream_age
    all_ages: list[int] = []
    for eid in ids:
        rec = await db.query(f"SELECT dream_age FROM {eid}")
        if rec:
            all_ages.append(rec[0].get("dream_age", 0))
    max_age = max(all_ages) if all_ages else 0

    # Update survivor
    if new_context is not None:
        await db.query(
            f"UPDATE {survivor_id} SET context = $ctx, dream_age = $age",
            {"ctx": new_context, "age": max_age},
        )
    else:
        await db.query(f"UPDATE {survivor_id} SET dream_age = {max_age}")

    # Delete losers
    for lid in loser_ids:
        await db.query(f"DELETE {lid}")

    survivor = await db.query(f"SELECT * FROM {survivor_id}")
    return {
        "survivor": make_serializable(survivor[0]) if survivor else {},
        "deleted_ids": loser_ids,
    }
