import logging

from second_brain.db import Storage
from second_brain.models import (
    MemorySearchCandidates,
    MemorySearchResult,
    normalize_node,
)

logger = logging.getLogger(__name__)


async def enrich_with_connections(storage: Storage, record: dict) -> dict:
    """Attach edge neighborhood summary to a node record.

    Each connection has: edge_label (edge table name), direction (in/out),
    and adjacent_id (the node on the other side).
    """
    record_id = record["id"]
    connections = await storage.get_connections(record_id)
    enriched = dict(record)
    enriched["connections"] = connections
    return enriched


async def hybrid_search(
    storage: Storage,
    table: str,
    query_text: str,
    k: int = 5,
) -> list[dict]:
    """Hybrid BM25 + vector search fused with reciprocal rank fusion."""
    if table not in ("note", "entity"):
        raise ValueError(f"Invalid table: {table}")
    results = await storage.hybrid_search(table, query_text, k)
    logger.info(
        "hybrid_search table=%s query=%r k=%d results=%d",
        table,
        query_text,
        k,
        len(results),
    )
    return results


async def get_node(storage: Storage, record_id: str) -> dict:
    """Get a single node by its record ID (e.g., 'note:1' or 'entity:sr')."""
    return await storage.get_node(record_id)


async def fetch_records_by_ids(storage: Storage, record_ids: list[str]) -> list[dict]:
    """Fetch multiple records by their SurrealDB IDs."""
    return await storage.get_nodes(record_ids)


def fuse_memory_candidates(candidates: MemorySearchCandidates, k: int) -> list[dict]:
    """Fuse capped search paths into one globally ranked result list.

    Organized paths each contribute half the weight of an intake path. The
    ordered path traversal gives ties a stable first-seen order.
    """
    if k <= 0:
        return []

    paths = (
        (candidates.note.bm25, 0.5),
        (candidates.note.vector, 0.5),
        (candidates.entity.bm25, 0.5),
        (candidates.entity.vector, 0.5),
        (candidates.intake_chunk.bm25, 1.0),
        (candidates.intake_chunk.vector, 1.0),
    )
    scores: dict[str, float] = {}
    records: dict[str, dict] = {}
    for path, weight in paths:
        for rank, candidate in enumerate(path[:k]):
            if "id" not in candidate:
                continue
            record = normalize_node(candidate)
            record_id = str(record["id"])
            if record_id not in scores:
                scores[record_id] = 0.0
                records[record_id] = record
            scores[record_id] += weight / (60 + rank + 1)

    ranked_ids = sorted(scores, key=lambda record_id: scores[record_id], reverse=True)
    return [records[record_id] for record_id in ranked_ids[:k]]


async def search_memory(storage: Storage, query: str, k: int = 5) -> MemorySearchResult:
    """Search organized and unprocessed memory with one global fusion pass."""
    candidates = await storage.search_memory_candidates(query, k)
    fused = fuse_memory_candidates(candidates, k)

    nodes: list[dict] = []
    unprocessed: list[dict] = []
    for record in fused:
        if record.get("table") == "intake_chunk":
            evidence = dict(record)
            evidence.pop("connections", None)
            evidence["unprocessed"] = True
            unprocessed.append(evidence)
        else:
            nodes.append(await enrich_with_connections(storage, record))
    return MemorySearchResult(nodes=nodes, unprocessed=unprocessed)
