import logging

from second_brain.db import Storage
from second_brain.models import MemorySearchResult

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


async def search_memory(storage: Storage, query: str, k: int = 5) -> MemorySearchResult:
    """Search both memory layers with one candidate request and global RRF.

    Cap each candidate path at k before fusion. Use RRF offset 60, weight
    note/entity paths at 0.5 and intake paths at 1. Return at most k records
    across both collections. Enrich only graph nodes with connections.
    """
    raise NotImplementedError("not implemented")
