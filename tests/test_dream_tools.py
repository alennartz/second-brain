import pytest

from second_brain.db import init_schema, init_vector_indexes


@pytest.fixture
async def dream_db(db):
    """DB with schema, vector indexes, and sample entities with embeddings."""
    await init_schema(db)
    await init_vector_indexes(db, dimensions=3)
    await db.query("""
        CREATE entity:py SET name = 'Python', type = 'language',
            embedding = [0.9, 0.1, 0.0];
        CREATE entity:py3 SET name = 'Python 3', type = 'language',
            embedding = [0.85, 0.15, 0.0];
        CREATE entity:rust SET name = 'Rust', type = 'language',
            embedding = [0.0, 0.1, 0.9];
    """)
    return db


async def test_find_similar_returns_nearest_neighbors(dream_db):
    from second_brain.tools.dream_tools import find_similar

    results = await find_similar(dream_db, "entity:py", k=2)
    assert len(results) >= 1
    # Python 3 should be more similar to Python than Rust is
    ids = [str(r["id"]) for r in results]
    assert any("entity:py3" in rid for rid in ids)
    # Should not include the source node itself
    assert not any(rid == "entity:py" for rid in ids)


async def test_find_similar_includes_similarity_score(dream_db):
    from second_brain.tools.dream_tools import find_similar

    results = await find_similar(dream_db, "entity:py", k=2)
    assert all("similarity" in r for r in results)
    assert all(isinstance(r["similarity"], float) for r in results)


async def test_find_similar_strips_embeddings(dream_db):
    from second_brain.tools.dream_tools import find_similar

    results = await find_similar(dream_db, "entity:py", k=2)
    assert all("embedding" not in r for r in results)
