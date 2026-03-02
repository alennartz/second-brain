# pyright: reportGeneralTypeIssues=false
# AsyncSurreal is typed as a factory function in the surrealdb SDK, not a class.
import logging
import math

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
