# pyright: reportGeneralTypeIssues=false
# AsyncSurreal is typed as a factory function in the surrealdb SDK, not a class.
import logging

from surrealdb import AsyncSurreal

logger = logging.getLogger(__name__)


async def hybrid_search(
    db: AsyncSurreal,
    table: str,
    query_text: str,
    query_embedding: list[float],
    k: int = 5,
) -> list[dict]:
    """Hybrid BM25 + vector search fused with reciprocal rank fusion."""
    if table not in ("note", "entity"):
        raise ValueError(f"Invalid table: {table}")
    field = "content" if table == "note" else "name"

    # Run vector search and full-text search separately, then fuse with RRF.
    # SurrealDB's search::rrf() may not be available in mem:// test backend,
    # so we compute RRF in Python for portability.
    #
    # NOTE: The SurrealDB Python SDK does not check per-statement errors.
    # When a statement fails (e.g. dimension mismatch), db.query() returns
    # the error string instead of a list of records. We must check for this.
    vs_result = await db.query(
        f"SELECT * FROM {table} WHERE embedding <|{k},100|> $vec",
        {"vec": query_embedding},
    )
    if isinstance(vs_result, str):
        raise RuntimeError(f"Vector search on {table} failed: {vs_result}")

    ft_result = await db.query(
        f"SELECT *, search::score(1) AS score "
        f"FROM {table} WHERE {field} @1@ $query "
        f"ORDER BY score DESC LIMIT {k}",
        {"query": query_text},
    )
    if isinstance(ft_result, str):
        raise RuntimeError(f"Full-text search on {table} failed: {ft_result}")

    # Reciprocal rank fusion: score = sum(1 / (k + rank)) across lists
    rrf_k = 60  # standard RRF constant
    scores: dict[str, float] = {}
    records: dict[str, dict] = {}

    for rank, rec in enumerate(vs_result):
        rid = str(rec["id"])
        scores[rid] = scores.get(rid, 0) + 1 / (rrf_k + rank + 1)
        records[rid] = rec

    for rank, rec in enumerate(ft_result):
        rid = str(rec["id"])
        scores[rid] = scores.get(rid, 0) + 1 / (rrf_k + rank + 1)
        records[rid] = rec

    # Sort by RRF score descending and return top k
    ranked_ids = sorted(scores, key=lambda rid: scores[rid], reverse=True)[:k]
    logger.info(
        "hybrid_search table=%s: vs=%d ft=%d fused=%d",
        table,
        len(vs_result),
        len(ft_result),
        len(ranked_ids),
    )
    return [records[rid] for rid in ranked_ids]


async def get_node(db: AsyncSurreal, record_id: str) -> dict:
    """Get a single node by its record ID (e.g., 'note:1' or 'entity:sr')."""
    result = await db.query(f"SELECT * FROM {record_id}")
    if not result:
        return {}
    return result[0]


async def get_connections(db: AsyncSurreal, record_id: str) -> list[dict]:
    """Get all edges connected to a node (both incoming and outgoing)."""
    outgoing = await db.query(f"SELECT * FROM {record_id}->?.*")
    incoming = await db.query(f"SELECT * FROM {record_id}<-?.*")
    return outgoing + incoming


async def graph_traverse(
    db: AsyncSurreal, record_id: str, depth: int = 2
) -> list[dict]:
    """Traverse the graph from a starting node up to N hops."""
    arrows = "->?->?" * depth
    result = await db.query(f"SELECT * FROM {record_id}{arrows}")
    return result


async def fetch_records_by_ids(db: AsyncSurreal, record_ids: list[str]) -> list[dict]:
    """Fetch multiple records by their SurrealDB IDs."""
    if not record_ids:
        return []
    results = []
    for rid in record_ids:
        result = await db.query(f"SELECT * FROM {rid}")
        if result:
            results.append(result[0])
    return results
