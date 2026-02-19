from collections.abc import Callable, Coroutine
from typing import Any

from surrealdb import AsyncSurreal

from second_brain.config import settings

# Late-initialized by configure_embedding()
_embed_fn: Callable[[str], Coroutine[Any, Any, list[float]]] | None = None


async def _get_embedding(text: str) -> list[float]:
    """Get embedding from configured model. Override in tests."""
    if _embed_fn is not None:
        return await _embed_fn(text)

    import os

    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={
                "model": settings.embedding_model.split(":")[-1],
                "input": text,
            },
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


async def embed_text(text: str) -> list[float]:
    """Generate an embedding vector for the given text."""
    return await _get_embedding(text)


async def init_vector_indexes(db: AsyncSurreal, dimensions: int | None = None) -> None:  # pyright: ignore[reportGeneralTypeIssues]
    """Define HNSW vector indexes. Idempotent."""
    dim = dimensions or settings.embedding_dimensions
    await db.query(f"""
        DEFINE INDEX IF NOT EXISTS note_embedding_hnsw ON note
            FIELDS embedding HNSW DIMENSION {dim} DIST COSINE;
        DEFINE INDEX IF NOT EXISTS entity_embedding_hnsw ON entity
            FIELDS embedding HNSW DIMENSION {dim} DIST COSINE;
    """)
