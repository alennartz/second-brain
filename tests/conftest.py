import pytest
from surrealdb import AsyncSurreal

from second_brain.db import Storage


class DummyEmbedder:
    """Embedder returning unique vectors per call for testing re-embedding behavior.

    Each embed() call increments a counter, producing [float(counter), 0.0, ...].
    All vectors share the same direction so cosine-similarity search still works.
    """

    def __init__(self, dimensions: int = 4) -> None:
        self.dimensions = dimensions
        self._counter = 0

    async def embed(self, text: str) -> list[float]:
        self._counter += 1
        return [float(self._counter)] + [0.0] * (self.dimensions - 1)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]


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
