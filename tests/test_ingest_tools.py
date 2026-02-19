import pytest
from second_brain.db import init_schema
from second_brain.tools.ingest_tools import (
    create_edge,
    create_entity,
    create_note,
    update_node,
)


@pytest.fixture
async def schema_db(db):
    await init_schema(db)
    return db


async def test_create_note(schema_db):
    note = await create_note(schema_db, content="Test note", source="cli")
    assert note["content"] == "Test note"
    assert note["source"] == "cli"
    assert "id" in note


async def test_create_entity(schema_db):
    entity = await create_entity(schema_db, name="Python", type="concept")
    assert entity["name"] == "Python"
    assert entity["type"] == "concept"


async def test_create_edge(schema_db):
    await schema_db.query("CREATE note:1 SET content = 'test', source = 'cli'")
    await schema_db.query("CREATE entity:py SET name = 'Python', type = 'concept'")

    edge = await create_edge(schema_db, from_id="note:1", edge_table="references", to_id="entity:py")
    assert edge is not None


async def test_update_node(schema_db):
    await schema_db.query("CREATE note:1 SET content = 'old', source = 'cli'")

    updated = await update_node(schema_db, record_id="note:1", fields={"summary": "new summary"})
    assert updated["summary"] == "new summary"
