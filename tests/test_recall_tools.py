import pytest

from second_brain.tools.recall_tools import (
    enrich_with_connections,
    fetch_records_by_ids,
    get_node,
    hybrid_search,
)


@pytest.fixture
async def seeded_storage(storage):
    """Storage with sample data for connection and node tests."""
    note1 = await storage.create_note(
        content="Spaced repetition improves long-term memory",
        summary="spaced repetition for memory",
        source="cli",
    )
    note2 = await storage.create_note(
        content="GTD is a productivity methodology",
        summary="GTD methodology",
        source="cli",
    )
    entity_sr = await storage.create_entity(
        name="spaced repetition",
        type="concept",
    )
    entity_gtd = await storage.create_entity(
        name="GTD",
        type="concept",
    )
    await storage.create_edge(note1["id"], "references", entity_sr["id"])
    await storage.create_edge(note2["id"], "references", entity_gtd["id"])
    await storage.create_edge(
        entity_sr["id"],
        "relates_to",
        entity_gtd["id"],
        {"context": "both are learning methods"},
    )
    records = {
        "note1": note1,
        "note2": note2,
        "entity_sr": entity_sr,
        "entity_gtd": entity_gtd,
    }
    return storage, records


@pytest.fixture
async def hybrid_storage(storage):
    """Storage with sample data for hybrid search tests."""
    note1 = await storage.create_note(
        content="Spaced repetition improves long-term memory",
        summary="spaced repetition for memory",
        source="cli",
    )
    note2 = await storage.create_note(
        content="GTD is a productivity methodology",
        summary="GTD methodology",
        source="cli",
    )
    entity_sr = await storage.create_entity(
        name="spaced repetition",
        type="concept",
    )
    entity_gtd = await storage.create_entity(
        name="GTD",
        type="concept",
    )
    records = {
        "note1": note1,
        "note2": note2,
        "entity_sr": entity_sr,
        "entity_gtd": entity_gtd,
    }
    return storage, records


async def test_hybrid_search_notes(hybrid_storage):
    """Hybrid search on notes table finds results matching both keyword and vector."""
    storage, records = hybrid_storage
    results = await hybrid_search(storage, "note", "repetition", k=5)
    assert len(results) >= 1
    ids = [r["id"] for r in results]
    assert records["note1"]["id"] in ids


async def test_hybrid_search_entities(hybrid_storage):
    """Hybrid search on entities table works."""
    storage, records = hybrid_storage
    results = await hybrid_search(storage, "entity", "spaced", k=5)
    assert len(results) >= 1
    ids = [r["id"] for r in results]
    assert records["entity_sr"]["id"] in ids


async def test_hybrid_search_no_results(storage):
    """Returns empty list when table has no data."""
    results = await hybrid_search(storage, "note", "xyznonexistent", k=5)
    assert results == []


async def test_hybrid_search_invalid_table(storage):
    """Raises ValueError for invalid table name."""
    with pytest.raises(ValueError, match="Invalid table"):
        await hybrid_search(storage, "invalid_table", "anything", k=5)


async def test_get_node(seeded_storage):
    """get_node returns a node by record ID."""
    storage, records = seeded_storage
    result = await get_node(storage, records["note1"]["id"])
    assert "Spaced repetition" in result["content"]


async def test_enrich_with_connections_outgoing(seeded_storage):
    """enrich_with_connections attaches outgoing edges."""
    storage, records = seeded_storage
    node = await storage.get_node(records["entity_sr"]["id"])
    enriched = await enrich_with_connections(storage, node)
    # entity_sr has an outgoing relates_to edge to entity_gtd
    assert "connections" in enriched
    out_conns = [c for c in enriched["connections"] if c["direction"] == "out"]
    assert len(out_conns) >= 1
    assert out_conns[0]["edge_label"] == "relates_to"
    assert out_conns[0]["adjacent_id"] == records["entity_gtd"]["id"]


async def test_enrich_with_connections_incoming(seeded_storage):
    """enrich_with_connections attaches incoming edges."""
    storage, records = seeded_storage
    node = await storage.get_node(records["entity_sr"]["id"])
    enriched = await enrich_with_connections(storage, node)
    # entity_sr has an incoming references edge from note1
    in_conns = [c for c in enriched["connections"] if c["direction"] == "in"]
    assert len(in_conns) >= 1
    assert in_conns[0]["edge_label"] == "references"
    assert in_conns[0]["adjacent_id"] == records["note1"]["id"]


async def test_enrich_with_connections_no_edges(storage):
    """enrich_with_connections returns empty connections for isolated node."""
    entity = await storage.create_entity(name="lonely", type="test")
    node = await storage.get_node(entity["id"])
    enriched = await enrich_with_connections(storage, node)
    assert enriched["connections"] == []


async def test_fetch_records_by_ids(seeded_storage):
    """fetch_records_by_ids returns records for valid IDs."""
    storage, records = seeded_storage
    results = await fetch_records_by_ids(storage, [records["note1"]["id"]])
    assert len(results) == 1
    assert "Spaced repetition" in results[0]["content"]


async def test_fetch_records_by_ids_empty(storage):
    """Passing an empty list returns an empty list."""
    results = await fetch_records_by_ids(storage, [])
    assert results == []


async def test_fetch_records_by_ids_missing(storage):
    """Passing a non-existent ID does not crash; returns empty or skips gracefully."""
    results = await fetch_records_by_ids(storage, ["note:nonexistent"])
    assert isinstance(results, list)
    assert len(results) == 0
