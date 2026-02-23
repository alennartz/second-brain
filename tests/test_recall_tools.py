import pytest

from second_brain.db import init_schema, init_vector_indexes
from second_brain.tools.recall_tools import (
    fetch_records_by_ids,
    get_connections,
    get_node,
    graph_traverse,
    hybrid_search,
)


@pytest.fixture
async def seeded_db(db):
    """DB with schema and sample data."""
    await init_schema(db)
    await db.query("""
        CREATE note:1 SET content = 'Spaced repetition improves long-term memory',
            summary = 'spaced repetition for memory', source = 'cli',
            embedding = [0.1, 0.2, 0.3];
        CREATE note:2 SET content = 'GTD is a productivity methodology',
            summary = 'GTD methodology', source = 'cli',
            embedding = [0.4, 0.5, 0.6];
        CREATE entity:sr SET name = 'spaced repetition', type = 'concept';
        CREATE entity:gtd SET name = 'GTD', type = 'concept';
        RELATE note:1->references->entity:sr;
        RELATE note:2->references->entity:gtd;
        RELATE entity:sr->relates_to->entity:gtd SET context = 'both are learning methods';
    """)
    return db


@pytest.fixture
async def hybrid_db(db):
    """DB with schema, vector indexes, and sample data with embeddings."""
    await init_schema(db)
    await init_vector_indexes(db, dimensions=3)
    await db.query("""
        CREATE note:1 SET content = 'Spaced repetition improves long-term memory',
            summary = 'spaced repetition for memory', source = 'cli',
            embedding = [0.1, 0.2, 0.3];
        CREATE note:2 SET content = 'GTD is a productivity methodology',
            summary = 'GTD methodology', source = 'cli',
            embedding = [0.4, 0.5, 0.6];
        CREATE entity:sr SET name = 'spaced repetition', type = 'concept',
            embedding = [0.1, 0.2, 0.3];
        CREATE entity:gtd SET name = 'GTD', type = 'concept',
            embedding = [0.4, 0.5, 0.6];
    """)
    return db


async def test_hybrid_search_notes(hybrid_db):
    """Hybrid search on notes table finds results matching both keyword and vector."""
    results = await hybrid_search(hybrid_db, "note", "repetition", [0.1, 0.2, 0.3], k=5)
    assert len(results) >= 1
    # The note about spaced repetition should be in results
    ids = [r["id"] for r in results]
    assert any("note:1" in str(rid) for rid in ids)


async def test_hybrid_search_entities(hybrid_db):
    """Hybrid search on entities table works."""
    results = await hybrid_search(hybrid_db, "entity", "spaced", [0.1, 0.2, 0.3], k=5)
    assert len(results) >= 1
    ids = [r["id"] for r in results]
    assert any("entity:sr" in str(rid) for rid in ids)


async def test_hybrid_search_no_results(db):
    """Returns empty list when table has no data."""
    await init_schema(db)
    await init_vector_indexes(db, dimensions=3)
    results = await hybrid_search(db, "note", "xyznonexistent", [0.9, 0.9, 0.9], k=5)
    assert results == []


async def test_hybrid_search_dimension_mismatch(hybrid_db):
    """Raises RuntimeError with clear message on vector dimension mismatch."""
    with pytest.raises(RuntimeError, match="Vector search on note failed"):
        await hybrid_search(
            hybrid_db, "note", "anything", [0.1, 0.2, 0.3, 0.4, 0.5], k=5
        )


async def test_get_node(seeded_db):
    result = await get_node(seeded_db, "note:1")
    assert "Spaced repetition" in result["content"]


async def test_get_connections(seeded_db):
    result = await get_connections(seeded_db, "entity:sr")
    assert len(result) > 0


async def test_graph_traverse(seeded_db):
    results = await graph_traverse(seeded_db, "note:1", depth=2)
    assert len(results) >= 1


async def test_fetch_records_by_ids(seeded_db):
    """fetch_records_by_ids returns records for valid IDs."""
    results = await fetch_records_by_ids(seeded_db, ["note:1"])
    assert len(results) == 1
    assert "Spaced repetition" in results[0]["content"]


async def test_fetch_records_by_ids_empty(seeded_db):
    """Passing an empty list returns an empty list."""
    results = await fetch_records_by_ids(seeded_db, [])
    assert results == []


async def test_fetch_records_by_ids_missing(seeded_db):
    """Passing a non-existent ID does not crash; returns empty or skips gracefully."""
    results = await fetch_records_by_ids(seeded_db, ["note:nonexistent"])
    # Should not crash; result should be empty (no record found)
    assert isinstance(results, list)
    # The missing ID should not produce a result
    assert len(results) == 0
