import pytest
from surrealdb import AsyncSurreal

from second_brain.db import Storage


class DummyEmbedder:
    """Embedder that returns zero vectors. Conforms to the Embedder protocol."""

    def __init__(self, dimensions: int = 4) -> None:
        self.dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        return [0.0] * self.dimensions

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimensions for _ in texts]


@pytest.fixture
async def db():
    """In-memory SurrealDB for tests."""
    async with AsyncSurreal("mem://") as db:
        await db.use("test", "test")
        yield db


@pytest.fixture
async def storage():
    """Storage instance backed by in-memory SurrealDB with DummyEmbedder."""
    s = Storage(url="mem://", embedder=DummyEmbedder(dimensions=4), dimensions=4)
    await s.init()
    yield s
    await s.close()
