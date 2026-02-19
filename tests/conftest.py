import pytest
from surrealdb import AsyncSurreal


@pytest.fixture
async def db():
    """In-memory SurrealDB for tests."""
    async with AsyncSurreal("mem://") as db:
        await db.use("test", "test")
        yield db
