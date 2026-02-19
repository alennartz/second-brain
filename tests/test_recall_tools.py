import pytest
from second_brain.db import init_schema
from second_brain.tools.recall_tools import (
    full_text_search,
    get_connections,
    get_node,
    graph_traverse,
    vector_search,
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


async def test_get_node(seeded_db):
    result = await get_node(seeded_db, "note:1")
    assert "Spaced repetition" in result["content"]


async def test_get_connections(seeded_db):
    result = await get_connections(seeded_db, "entity:sr")
    assert len(result) > 0


async def test_full_text_search(seeded_db):
    results = await full_text_search(seeded_db, "note", "repetition")
    assert len(results) >= 1


async def test_graph_traverse(seeded_db):
    results = await graph_traverse(seeded_db, "note:1", depth=2)
    assert len(results) >= 1
