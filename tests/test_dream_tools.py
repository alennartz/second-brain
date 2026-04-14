import pytest


@pytest.fixture
async def dream_storage(storage):
    """Storage with schema, vector indexes, and sample entities with embeddings."""
    assert storage._db is not None
    await storage._db.query("""
        CREATE entity:py SET name = 'Python', type = 'language',
            embedding = [0.9, 0.1, 0.0, 0.0];
        CREATE entity:py3 SET name = 'Python 3', type = 'language',
            embedding = [0.85, 0.15, 0.0, 0.0];
        CREATE entity:rust SET name = 'Rust', type = 'language',
            embedding = [0.0, 0.1, 0.9, 0.0];
    """)
    return storage


async def test_find_similar_returns_nearest_neighbors(dream_storage):
    from second_brain.tools.dream_tools import find_similar

    results = await find_similar(dream_storage, "entity:py", k=2)
    assert len(results) >= 1
    # Python 3 should be more similar to Python than Rust is
    ids = [r["id"] for r in results]
    assert any("entity:py3" in rid for rid in ids)
    # Should not include the source node itself
    assert not any(rid == "entity:py" for rid in ids)


async def test_find_similar_strips_scores(dream_storage):
    from second_brain.tools.dream_tools import find_similar

    results = await find_similar(dream_storage, "entity:py", k=2)
    assert all("similarity" not in r for r in results)
    assert all("score" not in r for r in results)


async def test_find_similar_strips_embeddings(dream_storage):
    from second_brain.tools.dream_tools import find_similar

    results = await find_similar(dream_storage, "entity:py", k=2)
    assert all("embedding" not in r for r in results)


@pytest.fixture
async def merge_storage(storage):
    """Storage with schema and nodes ready for merging."""
    assert storage._db is not None
    await storage._db.query("""
        CREATE entity:py SET name = 'Python', type = 'language',
            description = 'A programming language', dream_age = 1;
        CREATE entity:py3 SET name = 'Python 3', type = 'language',
            description = 'Latest version of Python', dream_age = 3;
        CREATE entity:fa SET name = 'FastAPI', type = 'framework';
        CREATE note:1 SET content = 'test note', source = 'cli';
        RELATE note:1->references->entity:py SET dream_age = 2;
        RELATE note:1->references->entity:py3 SET dream_age = 5;
        RELATE entity:py->built_with->entity:fa SET dream_age = 1;
        RELATE entity:py3->built_with->entity:fa SET dream_age = 4;
    """)
    return storage


async def test_merge_nodes_fuses_into_first(merge_storage):
    from second_brain.tools.dream_tools import merge_nodes

    result = await merge_nodes(
        merge_storage,
        ids=["entity:py", "entity:py3"],
        new_fields={
            "name": "Python",
            "description": "A versatile programming language",
        },
    )
    # Survivor should have fused fields
    assert result["survivor"]["name"] == "Python"
    assert result["survivor"]["description"] == "A versatile programming language"
    # Loser should be deleted
    gone = await merge_storage.get_node("entity:py3")
    assert gone == {}


async def test_merge_nodes_repoints_edges(merge_storage):
    from second_brain.tools.dream_tools import merge_nodes

    await merge_nodes(
        merge_storage,
        ids=["entity:py", "entity:py3"],
        new_fields={"name": "Python"},
    )
    # note:1 should reference entity:py (repointed from py3)
    out_edges = await merge_storage.get_outgoing_edges("note:1")
    refs = [e for e in out_edges if e["id"].startswith("references:")]
    # There should be exactly one references edge (deduped)
    assert len(refs) == 1


async def test_merge_nodes_deduplicates_edges(merge_storage):
    from second_brain.tools.dream_tools import merge_nodes

    await merge_nodes(
        merge_storage,
        ids=["entity:py", "entity:py3"],
        new_fields={"name": "Python"},
    )
    # Both had built_with->entity:fa, should be deduped to one
    edges = await merge_storage.check_edge_exists(
        "entity:py", "built_with", "entity:fa"
    )
    assert len(edges) == 1


async def test_merge_nodes_dream_age_takes_max(merge_storage):
    from second_brain.tools.dream_tools import merge_nodes

    await merge_nodes(
        merge_storage,
        ids=["entity:py", "entity:py3"],
        new_fields={"name": "Python"},
    )
    # dream_age should be max(1, 3) = 3
    age = await merge_storage.get_node_field("entity:py", "dream_age")
    assert age == 3


async def test_merge_nodes_edge_dream_age_takes_max(merge_storage):
    from second_brain.tools.dream_tools import merge_nodes

    await merge_nodes(
        merge_storage,
        ids=["entity:py", "entity:py3"],
        new_fields={"name": "Python"},
    )
    # Surviving built_with edge should have dream_age = max(1, 4) = 4
    edges = await merge_storage.check_edge_exists(
        "entity:py", "built_with", "entity:fa"
    )
    assert len(edges) == 1
    assert edges[0]["dream_age"] == 4

    # Surviving references edge should have dream_age = max(2, 5) = 5
    refs = await merge_storage.check_edge_exists("note:1", "references", "entity:py")
    assert len(refs) == 1
    assert refs[0]["dream_age"] == 5


@pytest.fixture
async def edge_merge_storage(storage):
    """Storage with duplicate edges between same nodes."""
    assert storage._db is not None
    await storage._db.query("""
        CREATE entity:a SET name = 'A', type = 'concept';
        CREATE entity:b SET name = 'B', type = 'concept';
        RELATE entity:a->relates_to->entity:b SET context = 'first relationship', dream_age = 2;
        RELATE entity:a->relates_to->entity:b SET context = 'second relationship', dream_age = 5;
    """)
    return storage


async def test_merge_edges_fuses(edge_merge_storage):
    from second_brain.tools.dream_tools import merge_edges

    edges = await edge_merge_storage.check_edge_exists(
        "entity:a", "relates_to", "entity:b"
    )
    edge_ids = [e["id"] for e in edges]
    assert len(edge_ids) == 2

    await merge_edges(
        edge_merge_storage,
        ids=edge_ids,
        new_context="combined relationship",
    )

    remaining = await edge_merge_storage.check_edge_exists(
        "entity:a", "relates_to", "entity:b"
    )
    assert len(remaining) == 1
    assert remaining[0]["context"] == "combined relationship"


async def test_merge_edges_dream_age_takes_max(edge_merge_storage):
    from second_brain.tools.dream_tools import merge_edges

    edges = await edge_merge_storage.check_edge_exists(
        "entity:a", "relates_to", "entity:b"
    )
    edge_ids = [e["id"] for e in edges]

    await merge_edges(edge_merge_storage, ids=edge_ids, new_context="merged")

    remaining = await edge_merge_storage.check_edge_exists(
        "entity:a", "relates_to", "entity:b"
    )
    assert len(remaining) == 1
    assert remaining[0]["dream_age"] == 5


# ── explore tests ──────────────────────────────────────────────────────


@pytest.fixture
async def graph_storage(storage):
    """Storage with a small graph for exploration tests."""
    assert storage._db is not None
    await storage._db.query("""
        CREATE entity:py SET name = 'Python', type = 'language';
        CREATE entity:fa SET name = 'FastAPI', type = 'framework';
        CREATE entity:sr SET name = 'SurrealDB', type = 'database';
        CREATE note:1 SET content = 'FastAPI is built with Python', source = 'cli';
        CREATE note:2 SET content = 'SurrealDB has a Python SDK', source = 'cli';
        RELATE note:1->references->entity:py;
        RELATE note:1->references->entity:fa;
        RELATE note:2->references->entity:py;
        RELATE note:2->references->entity:sr;
        RELATE entity:fa->built_with->entity:py;
    """)
    return storage


async def test_explore_outgoing_entities(graph_storage):
    from second_brain.tools.dream_tools import explore

    result = await explore(
        graph_storage, "entity:fa", direction="out", node_types=["entity"], depth=2
    )
    target_ids = [t["node"]["id"] for t in result["targets"]]
    assert any("entity:py" in tid for tid in target_ids)


async def test_explore_incoming_notes(graph_storage):
    from second_brain.tools.dream_tools import explore

    result = await explore(
        graph_storage, "entity:py", direction="in", node_types=["note"], depth=1
    )
    target_ids = [t["node"]["id"] for t in result["targets"]]
    assert len(target_ids) >= 2


async def test_explore_both_directions(graph_storage):
    from second_brain.tools.dream_tools import explore

    result = await explore(
        graph_storage, "entity:py", direction="both", node_types=["entity"], depth=2
    )
    target_ids = [t["node"]["id"] for t in result["targets"]]
    assert any("entity:fa" in tid for tid in target_ids)


async def test_explore_returns_paths(graph_storage):
    from second_brain.tools.dream_tools import explore

    result = await explore(
        graph_storage, "entity:fa", direction="out", node_types=["entity"], depth=2
    )
    for target in result["targets"]:
        assert "path" in target
        assert isinstance(target["path"], list)


async def test_explore_depth_bounded(graph_storage):
    from second_brain.tools.dream_tools import explore

    result = await explore(
        graph_storage, "entity:sr", direction="out", node_types=["entity"], depth=1
    )
    assert len(result["targets"]) == 0


# ── find_unlinked_cooccurrences tests ─────────────────────────────────


async def test_find_unlinked_cooccurrences(graph_storage):
    from second_brain.tools.dream_tools import find_unlinked_cooccurrences

    # entity:py and entity:fa share note:1 and fa->built_with->py exists,
    # but entity:py and entity:sr share note:2 and have no direct edge
    results = await find_unlinked_cooccurrences(graph_storage, "entity:py")
    other_ids = [r["entity"]["id"] for r in results]
    assert any("entity:sr" in oid for oid in other_ids)


async def test_find_unlinked_cooccurrences_excludes_linked(graph_storage):
    from second_brain.tools.dream_tools import find_unlinked_cooccurrences

    # entity:fa is linked to entity:py via built_with, should not appear
    results = await find_unlinked_cooccurrences(graph_storage, "entity:py")
    other_ids = [r["entity"]["id"] for r in results]
    assert not any("entity:fa" in oid for oid in other_ids)


async def test_find_unlinked_cooccurrences_includes_shared_notes(graph_storage):
    from second_brain.tools.dream_tools import find_unlinked_cooccurrences

    results = await find_unlinked_cooccurrences(graph_storage, "entity:py")
    for r in results:
        assert "shared_notes" in r
        assert len(r["shared_notes"]) >= 1


async def test_find_unlinked_cooccurrences_no_results(graph_storage):
    from second_brain.tools.dream_tools import find_unlinked_cooccurrences

    # Link entity:sr to entity:py, then check from entity:sr's perspective
    assert graph_storage._db is not None
    await graph_storage._db.query("RELATE entity:sr->relates_to->entity:py")
    results = await find_unlinked_cooccurrences(graph_storage, "entity:sr")
    # Now they are linked, so no results
    assert len(results) == 0
