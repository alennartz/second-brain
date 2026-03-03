from unittest.mock import AsyncMock

import pytest

from second_brain.db import init_schema
from second_brain.tools.ingest_tools import (
    create_edges,
    create_entities,
    create_notes,
    update_node,
)


@pytest.fixture
async def schema_db(db):
    await init_schema(db)
    return db


dummy_embed = AsyncMock(return_value=[0.1, 0.2, 0.3])


async def test_create_notes_bulk(schema_db):
    notes = [
        {"content": "Note one", "source": "cli"},
        {"content": "Note two", "source": "api", "summary": "second note"},
    ]
    results = await create_notes(schema_db, notes, dummy_embed)
    assert len(results) == 2
    assert results[0]["content"] == "Note one"
    assert results[1]["content"] == "Note two"
    assert results[1]["summary"] == "second note"
    assert all("id" in r for r in results)


async def test_create_notes_default_source(schema_db):
    notes = [{"content": "No source specified"}]
    results = await create_notes(schema_db, notes, dummy_embed)
    assert results[0]["source"] == "api"


async def test_create_entities_bulk(schema_db):
    entities = [
        {"name": "Python", "type": "language"},
        {
            "name": "FastAPI",
            "type": "framework",
            "description": "Web framework for Python",
        },
    ]
    results = await create_entities(schema_db, entities, dummy_embed)
    assert len(results) == 2
    assert results[0]["name"] == "Python"
    assert results[1]["description"] == "Web framework for Python"
    assert all("id" in r for r in results)


async def test_create_edges_bulk(schema_db):
    await schema_db.query("""
        CREATE note:1 SET content = 'test', source = 'cli';
        CREATE entity:py SET name = 'Python', type = 'language';
        CREATE entity:fa SET name = 'FastAPI', type = 'framework';
    """)
    edges = [
        {"from_id": "note:1", "edge_table": "mentions", "to_id": "entity:py"},
        {
            "from_id": "entity:fa",
            "edge_table": "built_with",
            "to_id": "entity:py",
            "context": "FastAPI uses Python",
        },
    ]
    results = await create_edges(schema_db, edges)
    assert len(results) == 2
    assert all("id" in r for r in results)


async def test_create_edges_rejects_self_edges(schema_db):
    await schema_db.query("CREATE entity:a SET name = 'Alpha', type = 'concept'")
    edges = [{"from_id": "entity:a", "edge_table": "relates_to", "to_id": "entity:a"}]
    results = await create_edges(schema_db, edges)
    assert len(results) == 1
    assert results[0]["skipped"] is True
    assert results[0]["reason"] == "self-edge"

    # Verify nothing was created in the DB
    db_edges = await schema_db.query("SELECT * FROM entity:a->relates_to")
    assert db_edges == [] or not db_edges


async def test_create_edges_rejects_duplicates(schema_db):
    await schema_db.query("""
        CREATE entity:a SET name = 'Alpha', type = 'concept';
        CREATE entity:b SET name = 'Beta', type = 'concept';
    """)
    edge = {"from_id": "entity:a", "edge_table": "relates_to", "to_id": "entity:b"}

    # First creation should succeed
    results1 = await create_edges(schema_db, [edge])
    assert len(results1) == 1
    assert "id" in results1[0]

    # Second creation of same edge should be skipped
    results2 = await create_edges(schema_db, [edge])
    assert len(results2) == 1
    assert results2[0]["skipped"] is True
    assert results2[0]["reason"] == "duplicate"


async def test_create_edges_mixed_valid_and_invalid(schema_db):
    await schema_db.query("""
        CREATE entity:a SET name = 'Alpha', type = 'concept';
        CREATE entity:b SET name = 'Beta', type = 'concept';
    """)
    edges = [
        {
            "from_id": "entity:a",
            "edge_table": "relates_to",
            "to_id": "entity:a",
        },  # self-edge
        {
            "from_id": "entity:a",
            "edge_table": "built_with",
            "to_id": "entity:b",
        },  # valid
    ]
    results = await create_edges(schema_db, edges)
    assert len(results) == 2
    assert results[0]["skipped"] is True
    assert "id" in results[1]


async def test_update_node(schema_db):
    await schema_db.query("CREATE note:1 SET content = 'old', source = 'cli'")
    updated = await update_node(
        schema_db, record_id="note:1", fields={"summary": "new summary"}
    )
    assert updated["summary"] == "new summary"
