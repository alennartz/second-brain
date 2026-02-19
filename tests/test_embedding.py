import pytest
from unittest.mock import AsyncMock, patch

from second_brain.embedding import embed_text, init_vector_indexes


async def test_embed_text_returns_vector():
    fake_vector = [0.1] * 1536

    with patch("second_brain.embedding._get_embedding", new_callable=AsyncMock) as mock:
        mock.return_value = fake_vector
        result = await embed_text("hello world")

    assert len(result) == 1536
    assert isinstance(result, list)
    assert all(isinstance(x, float) for x in result)


async def test_init_vector_indexes(db):
    from second_brain.db import init_schema

    await init_schema(db)
    await init_vector_indexes(db, dimensions=3)

    # Should not raise on second call
    await init_vector_indexes(db, dimensions=3)
