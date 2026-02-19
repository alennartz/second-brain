# pyright: reportGeneralTypeIssues=false
# AsyncSurreal is typed as a factory function in the surrealdb SDK, not a class.
from surrealdb import AsyncSurreal


async def vector_search(
    db: AsyncSurreal, table: str, query_embedding: list[float], k: int = 5
) -> list[dict]:
    """Find the k nearest notes/entities by vector similarity."""
    result = await db.query(
        f"SELECT *, vector::similarity::cosine(embedding, $vec) AS score "
        f"FROM {table} "
        f"ORDER BY score DESC LIMIT $k",
        {"vec": query_embedding, "k": k},
    )
    return result


async def full_text_search(
    db: AsyncSurreal, table: str, query: str, limit: int = 10
) -> list[dict]:
    """Search notes or entities by full-text match using BM25."""
    field = "content" if table == "note" else "name"
    result = await db.query(
        f"SELECT *, search::score(1) AS score FROM {table} "
        f"WHERE {field} @1@ $query "
        f"ORDER BY score DESC LIMIT $limit",
        {"query": query, "limit": limit},
    )
    return result


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
