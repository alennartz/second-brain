"""Tests for store_knowledge — the bulk ingest tool that creates entities,
notes, and edges in one call with internal reference resolution."""

from second_brain.db import Storage
from second_brain.tools.ingest_tools import store_knowledge

# ── Happy path ───────────────────────────────────────────────────────────────


async def test_creates_entities_and_returns_ids(storage: Storage):
    result = await store_knowledge(
        storage,
        entities=[
            {"name": "Python", "type": "language"},
            {"name": "FastAPI", "type": "framework", "description": "Web framework"},
        ],
        notes=[],
        edges=[],
    )
    assert len(result["entities_created"]) == 2
    assert result["entities_created"][0]["ref"] == "new_entity:0"
    assert result["entities_created"][0]["name"] == "Python"
    assert "id" in result["entities_created"][0]
    assert result["entities_created"][1]["ref"] == "new_entity:1"
    assert result["entities_created"][1]["name"] == "FastAPI"


async def test_creates_notes_and_returns_ids(storage: Storage):
    result = await store_knowledge(
        storage,
        entities=[],
        notes=[
            {"content": "Python is great", "summary": "Python praise"},
            {"content": "FastAPI is fast"},
        ],
        edges=[],
    )
    assert len(result["notes_created"]) == 2
    assert result["notes_created"][0]["ref"] == "new_note:0"
    assert "id" in result["notes_created"][0]
    assert result["notes_created"][1]["ref"] == "new_note:1"


async def test_edges_between_new_entities(storage: Storage):
    result = await store_knowledge(
        storage,
        entities=[
            {"name": "Python", "type": "language"},
            {"name": "FastAPI", "type": "framework"},
        ],
        notes=[],
        edges=[
            {
                "from_ref": "new_entity:1",
                "edge_table": "built_with",
                "to_ref": "new_entity:0",
            },
        ],
    )
    assert result["edges_created"] == 1
    assert result["edges_skipped"] == 0
    assert result["errors"] == []


async def test_edges_between_new_note_and_new_entity(storage: Storage):
    result = await store_knowledge(
        storage,
        entities=[{"name": "Python", "type": "language"}],
        notes=[{"content": "Python is great"}],
        edges=[
            {
                "from_ref": "new_note:0",
                "edge_table": "describes",
                "to_ref": "new_entity:0",
            },
        ],
    )
    assert result["edges_created"] == 1
    assert result["errors"] == []


async def test_edges_to_existing_record_ids(storage: Storage):
    existing = await storage.create_entity(name="Existing", type="concept")
    result = await store_knowledge(
        storage,
        entities=[{"name": "New Thing", "type": "concept"}],
        notes=[],
        edges=[
            {
                "from_ref": "new_entity:0",
                "edge_table": "depends_on",
                "to_ref": existing["id"],
            },
        ],
    )
    assert result["edges_created"] == 1
    assert result["errors"] == []


async def test_mixed_new_and_existing_refs_in_edges(storage: Storage):
    old = await storage.create_entity(name="Old Entity", type="concept")
    result = await store_knowledge(
        storage,
        entities=[{"name": "New Entity", "type": "concept"}],
        notes=[{"content": "A note about both"}],
        edges=[
            {
                "from_ref": "new_entity:0",
                "edge_table": "related_to",
                "to_ref": old["id"],
            },
            {
                "from_ref": "new_note:0",
                "edge_table": "describes",
                "to_ref": "new_entity:0",
            },
            {
                "from_ref": old["id"],
                "edge_table": "preceded_by",
                "to_ref": "new_entity:0",
            },
        ],
    )
    assert result["edges_created"] == 3
    assert result["errors"] == []


async def test_full_ingest_scenario(storage: Storage):
    """Simulates a realistic ingest: multiple entities, notes, and edges."""
    result = await store_knowledge(
        storage,
        entities=[
            {"name": "Ada Lovelace", "type": "person", "description": "Mathematician"},
            {"name": "Charles Babbage", "type": "person", "description": "Inventor"},
            {"name": "Analytical Engine", "type": "technology"},
        ],
        notes=[
            {
                "content": "Ada Lovelace worked with Babbage on the Analytical Engine.",
                "summary": "Lovelace-Babbage collaboration",
            },
        ],
        edges=[
            {
                "from_ref": "new_entity:0",
                "edge_table": "collaborated_with",
                "to_ref": "new_entity:1",
            },
            {
                "from_ref": "new_entity:0",
                "edge_table": "worked_on",
                "to_ref": "new_entity:2",
            },
            {
                "from_ref": "new_entity:1",
                "edge_table": "designed",
                "to_ref": "new_entity:2",
            },
            {
                "from_ref": "new_note:0",
                "edge_table": "describes",
                "to_ref": "new_entity:0",
            },
        ],
    )
    assert len(result["entities_created"]) == 3
    assert len(result["notes_created"]) == 1
    assert result["edges_created"] == 4
    assert result["errors"] == []


# ── Empty inputs ─────────────────────────────────────────────────────────────


async def test_empty_inputs(storage: Storage):
    result = await store_knowledge(
        storage,
        entities=[],
        notes=[],
        edges=[],
    )
    assert result["entities_created"] == []
    assert result["notes_created"] == []
    assert result["edges_created"] == 0
    assert result["edges_skipped"] == 0
    assert result["errors"] == []


async def test_entities_only_no_notes_no_edges(storage: Storage):
    result = await store_knowledge(
        storage,
        entities=[{"name": "Solo", "type": "concept"}],
        notes=[],
        edges=[],
    )
    assert len(result["entities_created"]) == 1
    assert result["notes_created"] == []
    assert result["edges_created"] == 0


async def test_notes_only_no_entities_no_edges(storage: Storage):
    result = await store_knowledge(
        storage,
        entities=[],
        notes=[{"content": "A standalone thought"}],
        edges=[],
    )
    assert result["entities_created"] == []
    assert len(result["notes_created"]) == 1
    assert result["edges_created"] == 0


# ── Error cases: invalid references ──────────────────────────────────────────


async def test_edge_with_out_of_bounds_entity_ref(storage: Storage):
    result = await store_knowledge(
        storage,
        entities=[{"name": "Only One", "type": "concept"}],
        notes=[],
        edges=[
            {
                "from_ref": "new_entity:0",
                "edge_table": "relates_to",
                "to_ref": "new_entity:5",
            },
        ],
    )
    assert result["edges_created"] == 0
    assert result["edges_skipped"] == 1
    assert len(result["errors"]) == 1


async def test_edge_with_out_of_bounds_note_ref(storage: Storage):
    result = await store_knowledge(
        storage,
        entities=[],
        notes=[{"content": "Only one note"}],
        edges=[
            {
                "from_ref": "new_note:0",
                "edge_table": "describes",
                "to_ref": "new_note:99",
            },
        ],
    )
    assert result["edges_created"] == 0
    assert result["edges_skipped"] == 1
    assert len(result["errors"]) == 1


async def test_edge_with_malformed_ref(storage: Storage):
    result = await store_knowledge(
        storage,
        entities=[{"name": "X", "type": "concept"}],
        notes=[],
        edges=[
            {
                "from_ref": "garbage",
                "edge_table": "relates_to",
                "to_ref": "new_entity:0",
            },
        ],
    )
    # "garbage" isn't a valid record ID or a new_* ref — should be skipped
    assert result["edges_created"] == 0
    assert result["edges_skipped"] == 1
    assert len(result["errors"]) == 1


async def test_valid_and_invalid_edges_mixed(storage: Storage):
    """Valid edges should still be created even when other edges fail."""
    result = await store_knowledge(
        storage,
        entities=[
            {"name": "A", "type": "concept"},
            {"name": "B", "type": "concept"},
        ],
        notes=[],
        edges=[
            {
                "from_ref": "new_entity:0",
                "edge_table": "relates_to",
                "to_ref": "new_entity:1",
            },
            {
                "from_ref": "new_entity:0",
                "edge_table": "relates_to",
                "to_ref": "new_entity:99",
            },
        ],
    )
    assert result["edges_created"] == 1
    assert result["edges_skipped"] == 1
    assert len(result["errors"]) == 1


# ── Edge dedup: self-edges and duplicates pass through to create_edges ───────


async def test_self_edge_via_refs_is_skipped(storage: Storage):
    result = await store_knowledge(
        storage,
        entities=[{"name": "Solo", "type": "concept"}],
        notes=[],
        edges=[
            {
                "from_ref": "new_entity:0",
                "edge_table": "relates_to",
                "to_ref": "new_entity:0",
            },
        ],
    )
    assert result["edges_created"] == 0
    assert result["edges_skipped"] == 1
