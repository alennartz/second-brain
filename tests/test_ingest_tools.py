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


async def test_update_node(schema_db):
    await schema_db.query("CREATE note:1 SET content = 'old', source = 'cli'")
    updated = await update_node(
        schema_db, record_id="note:1", fields={"summary": "new summary"}
    )
    assert updated["summary"] == "new summary"
