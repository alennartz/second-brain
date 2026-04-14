"""Tests for create_edges — the only ingest_tools function that remains
as business logic (self-edge rejection + duplicate skipping).

create_notes, create_entities, and update_node have moved to Storage
and are tested in test_storage.py.
"""

from second_brain.db import Storage
from second_brain.tools.ingest_tools import create_edges


async def test_create_edges_bulk(storage: Storage):
    note = await storage.create_note(content="test", source="cli")
    py = await storage.create_entity(name="Python", type="language")
    fa = await storage.create_entity(name="FastAPI", type="framework")
    edges = [
        {"from_id": note["id"], "edge_table": "mentions", "to_id": py["id"]},
        {
            "from_id": fa["id"],
            "edge_table": "built_with",
            "to_id": py["id"],
            "context": "FastAPI uses Python",
        },
    ]
    results = await create_edges(storage, edges)
    assert len(results) == 2
    assert all("id" in r for r in results)


async def test_create_edges_rejects_self_edges(storage: Storage):
    entity = await storage.create_entity(name="Alpha", type="concept")
    edges = [
        {
            "from_id": entity["id"],
            "edge_table": "relates_to",
            "to_id": entity["id"],
        }
    ]
    results = await create_edges(storage, edges)
    assert len(results) == 1
    assert results[0]["skipped"] is True
    assert results[0]["reason"] == "self-edge"


async def test_create_edges_rejects_duplicates(storage: Storage):
    a = await storage.create_entity(name="Alpha", type="concept")
    b = await storage.create_entity(name="Beta", type="concept")
    edge = {"from_id": a["id"], "edge_table": "relates_to", "to_id": b["id"]}

    # First creation should succeed
    results1 = await create_edges(storage, [edge])
    assert len(results1) == 1
    assert "id" in results1[0]

    # Second creation of same edge should be skipped
    results2 = await create_edges(storage, [edge])
    assert len(results2) == 1
    assert results2[0]["skipped"] is True
    assert results2[0]["reason"] == "duplicate"


async def test_create_edges_mixed_valid_and_invalid(storage: Storage):
    a = await storage.create_entity(name="Alpha", type="concept")
    b = await storage.create_entity(name="Beta", type="concept")
    edges = [
        {
            "from_id": a["id"],
            "edge_table": "relates_to",
            "to_id": a["id"],
        },  # self-edge
        {
            "from_id": a["id"],
            "edge_table": "built_with",
            "to_id": b["id"],
        },  # valid
    ]
    results = await create_edges(storage, edges)
    assert len(results) == 2
    assert results[0]["skipped"] is True
    assert "id" in results[1]
