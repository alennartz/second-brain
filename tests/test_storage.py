"""Behavioral tests for the Storage class.

Tests exercise the public interface defined in the architecture.
All methods currently raise NotImplementedError — tests are expected to fail
until the implementation phase.
"""

from __future__ import annotations

import pytest

from second_brain.db import Storage

# ── Node Operations ──────────────────────────────────────────────────────────


class TestGetNode:
    async def test_returns_node_by_record_id(self, storage: Storage):
        created = await storage.create_note(content="Test content", source="test")
        result = await storage.get_node(created["id"])
        assert result["content"] == "Test content"

    async def test_returns_empty_dict_when_not_found(self, storage: Storage):
        result = await storage.get_node("note:nonexistent")
        assert result == {}

    async def test_excludes_embeddings(self, storage: Storage):
        created = await storage.create_note(content="Embedded content")
        result = await storage.get_node(created["id"])
        assert "embedding" not in result

    async def test_record_id_is_plain_string(self, storage: Storage):
        created = await storage.create_note(content="Test")
        result = await storage.get_node(created["id"])
        assert isinstance(result["id"], str)
        assert ":" in result["id"]

    async def test_rejects_malformed_record_id(self, storage: Storage):
        with pytest.raises(ValueError, match="Invalid record ID"):
            await storage.get_node("-none-")


class TestGetNodes:
    async def test_returns_multiple_nodes(self, storage: Storage):
        n1 = await storage.create_note(content="First")
        n2 = await storage.create_note(content="Second")
        results = await storage.get_nodes([n1["id"], n2["id"]])
        assert len(results) == 2

    async def test_excludes_embeddings(self, storage: Storage):
        n1 = await storage.create_note(content="Test")
        results = await storage.get_nodes([n1["id"]])
        for r in results:
            assert "embedding" not in r

    async def test_skips_missing_ids(self, storage: Storage):
        n1 = await storage.create_note(content="Exists")
        results = await storage.get_nodes([n1["id"], "note:missing"])
        assert len(results) == 1

    async def test_skips_malformed_ids(self, storage: Storage):
        """Malformed IDs (e.g. LLM-cited placeholders) are skipped, not raised."""
        n1 = await storage.create_note(content="Exists")
        results = await storage.get_nodes([n1["id"], "-none-"])
        assert len(results) == 1
        assert results[0]["id"] == n1["id"]

    async def test_returns_empty_for_empty_input(self, storage: Storage):
        results = await storage.get_nodes([])
        assert results == []


class TestCreateNote:
    async def test_creates_note_with_content(self, storage: Storage):
        result = await storage.create_note(content="Hello world")
        assert "id" in result
        assert result["content"] == "Hello world"

    async def test_defaults_source_to_api(self, storage: Storage):
        result = await storage.create_note(content="Test")
        assert result["source"] == "api"

    async def test_accepts_custom_source(self, storage: Storage):
        result = await storage.create_note(content="Test", source="cli")
        assert result["source"] == "cli"

    async def test_accepts_optional_summary(self, storage: Storage):
        result = await storage.create_note(content="Test", summary="A summary")
        assert result["summary"] == "A summary"

    async def test_auto_embeds_content(self, storage: Storage):
        result = await storage.create_note(content="Embedded text")
        embedding = await storage.get_node_field(result["id"], "embedding")
        assert isinstance(embedding, list)
        assert len(embedding) > 0

    async def test_returned_id_is_plain_string(self, storage: Storage):
        result = await storage.create_note(content="Test")
        assert isinstance(result["id"], str)
        assert result["id"].startswith("note:")


class TestCreateNotes:
    async def test_bulk_creates_multiple_notes(self, storage: Storage):
        notes = [
            {"content": "First note"},
            {"content": "Second note", "source": "cli", "summary": "Note 2"},
        ]
        results = await storage.create_notes(notes)
        assert len(results) == 2
        assert all("id" in r for r in results)

    async def test_auto_embeds_all_notes(self, storage: Storage):
        notes = [{"content": "One"}, {"content": "Two"}]
        results = await storage.create_notes(notes)
        for r in results:
            emb = await storage.get_node_field(r["id"], "embedding")
            assert isinstance(emb, list)

    async def test_returns_empty_for_empty_input(self, storage: Storage):
        results = await storage.create_notes([])
        assert results == []


class TestCreateEntity:
    async def test_creates_entity_with_name_and_type(self, storage: Storage):
        result = await storage.create_entity(name="Python", type="language")
        assert "id" in result
        assert result["name"] == "Python"
        assert result["type"] == "language"

    async def test_accepts_optional_description(self, storage: Storage):
        result = await storage.create_entity(
            name="FastAPI", type="framework", description="Web framework"
        )
        assert result["description"] == "Web framework"

    async def test_auto_embeds_description_when_present(self, storage: Storage):
        result = await storage.create_entity(
            name="Test", type="concept", description="A test entity"
        )
        emb = await storage.get_node_field(result["id"], "embedding")
        assert isinstance(emb, list)

    async def test_auto_embeds_name_when_no_description(self, storage: Storage):
        result = await storage.create_entity(name="Standalone", type="concept")
        emb = await storage.get_node_field(result["id"], "embedding")
        assert isinstance(emb, list)

    async def test_returned_id_is_plain_string(self, storage: Storage):
        result = await storage.create_entity(name="Test", type="concept")
        assert isinstance(result["id"], str)
        assert result["id"].startswith("entity:")


class TestCreateEntities:
    async def test_bulk_creates_multiple_entities(self, storage: Storage):
        entities = [
            {"name": "Python", "type": "language"},
            {"name": "FastAPI", "type": "framework", "description": "Web framework"},
        ]
        results = await storage.create_entities(entities)
        assert len(results) == 2
        assert all("id" in r for r in results)

    async def test_returns_empty_for_empty_input(self, storage: Storage):
        results = await storage.create_entities([])
        assert results == []


class TestUpdateNode:
    async def test_updates_specified_fields(self, storage: Storage):
        created = await storage.create_note(content="Original")
        updated = await storage.update_node(created["id"], {"summary": "New summary"})
        assert updated["summary"] == "New summary"

    async def test_preserves_unchanged_fields(self, storage: Storage):
        created = await storage.create_note(content="Keep this", source="cli")
        updated = await storage.update_node(created["id"], {"summary": "Added"})
        assert updated["content"] == "Keep this"

    async def test_re_embeds_when_content_changes(self, storage: Storage):
        created = await storage.create_note(content="Original text")
        old_emb = await storage.get_node_field(created["id"], "embedding")
        await storage.update_node(created["id"], {"content": "New content"})
        new_emb = await storage.get_node_field(created["id"], "embedding")
        assert new_emb != old_emb

    async def test_re_embeds_when_name_changes(self, storage: Storage):
        created = await storage.create_entity(name="Old Name", type="concept")
        old_emb = await storage.get_node_field(created["id"], "embedding")
        await storage.update_node(created["id"], {"name": "New Name"})
        new_emb = await storage.get_node_field(created["id"], "embedding")
        assert new_emb != old_emb

    async def test_re_embeds_when_description_changes(self, storage: Storage):
        created = await storage.create_entity(
            name="Entity", type="concept", description="Old desc"
        )
        old_emb = await storage.get_node_field(created["id"], "embedding")
        await storage.update_node(created["id"], {"description": "New desc"})
        new_emb = await storage.get_node_field(created["id"], "embedding")
        assert new_emb != old_emb

    async def test_does_not_re_embed_on_non_text_field(self, storage: Storage):
        """Updating non-text fields (like dream_age) should not trigger re-embedding."""
        created = await storage.create_note(content="Test")
        old_emb = await storage.get_node_field(created["id"], "embedding")
        await storage.update_node(created["id"], {"dream_age": 5})
        new_emb = await storage.get_node_field(created["id"], "embedding")
        assert old_emb == new_emb


class TestDeleteNode:
    async def test_deletes_existing_node(self, storage: Storage):
        created = await storage.create_note(content="To delete")
        await storage.delete_node(created["id"])
        result = await storage.get_node(created["id"])
        assert result == {}

    async def test_deleting_nonexistent_node_does_not_raise(self, storage: Storage):
        """Deleting a node that doesn't exist should not error."""
        await storage.delete_node("note:nonexistent")  # Should not raise


# ── Edge Operations ──────────────────────────────────────────────────────────


class TestGetEdge:
    async def test_returns_edge_by_id(self, storage: Storage):
        n1 = await storage.create_note(content="Note")
        n2 = await storage.create_entity(name="Entity", type="concept")
        edge = await storage.create_edge(n1["id"], "references", n2["id"])
        result = await storage.get_edge(edge["id"])
        assert result != {}
        assert "id" in result

    async def test_returns_empty_dict_when_not_found(self, storage: Storage):
        result = await storage.get_edge("references:nonexistent")
        assert result == {}

    async def test_rejects_malformed_edge_id(self, storage: Storage):
        with pytest.raises(ValueError, match="Invalid record ID"):
            await storage.get_edge("-none-")


class TestGetOutgoingEdges:
    async def test_returns_outgoing_edges(self, storage: Storage):
        n1 = await storage.create_note(content="Source")
        n2 = await storage.create_entity(name="Target", type="concept")
        await storage.create_edge(n1["id"], "references", n2["id"])
        edges = await storage.get_outgoing_edges(n1["id"])
        assert len(edges) >= 1

    async def test_edge_dicts_have_string_ids(self, storage: Storage):
        """Edge dicts have id, in, out as plain strings per the contract."""
        n1 = await storage.create_note(content="Source")
        n2 = await storage.create_entity(name="Target", type="concept")
        await storage.create_edge(n1["id"], "references", n2["id"])
        edges = await storage.get_outgoing_edges(n1["id"])
        for e in edges:
            assert isinstance(e["id"], str)
            assert isinstance(e["in"], str)
            assert isinstance(e["out"], str)

    async def test_includes_edge_specific_fields(self, storage: Storage):
        n1 = await storage.create_entity(name="A", type="concept")
        n2 = await storage.create_entity(name="B", type="concept")
        await storage.create_edge(
            n1["id"], "relates_to", n2["id"], fields={"context": "test context"}
        )
        edges = await storage.get_outgoing_edges(n1["id"])
        assert any(e.get("context") == "test context" for e in edges)

    async def test_returns_empty_for_node_with_no_outgoing(self, storage: Storage):
        n1 = await storage.create_note(content="Isolated")
        edges = await storage.get_outgoing_edges(n1["id"])
        assert edges == []


class TestGetIncomingEdges:
    async def test_returns_incoming_edges(self, storage: Storage):
        n1 = await storage.create_note(content="Source")
        n2 = await storage.create_entity(name="Target", type="concept")
        await storage.create_edge(n1["id"], "references", n2["id"])
        edges = await storage.get_incoming_edges(n2["id"])
        assert len(edges) >= 1

    async def test_returns_empty_for_node_with_no_incoming(self, storage: Storage):
        n1 = await storage.create_note(content="Isolated")
        edges = await storage.get_incoming_edges(n1["id"])
        assert edges == []


class TestCreateEdge:
    async def test_creates_edge_between_nodes(self, storage: Storage):
        n1 = await storage.create_note(content="Note")
        n2 = await storage.create_entity(name="Entity", type="concept")
        edge = await storage.create_edge(n1["id"], "references", n2["id"])
        assert "id" in edge

    async def test_accepts_optional_fields(self, storage: Storage):
        n1 = await storage.create_entity(name="A", type="concept")
        n2 = await storage.create_entity(name="B", type="concept")
        edge = await storage.create_edge(
            n1["id"], "relates_to", n2["id"], fields={"context": "related concepts"}
        )
        assert "id" in edge

    async def test_does_not_deduplicate(self, storage: Storage):
        """create_edge is a primitive — dedup checking is the caller's responsibility."""
        n1 = await storage.create_entity(name="A", type="concept")
        n2 = await storage.create_entity(name="B", type="concept")
        e1 = await storage.create_edge(n1["id"], "relates_to", n2["id"])
        e2 = await storage.create_edge(n1["id"], "relates_to", n2["id"])
        assert e1["id"] != e2["id"]  # Two distinct edges created

    async def test_returned_id_is_plain_string(self, storage: Storage):
        n1 = await storage.create_note(content="N")
        n2 = await storage.create_entity(name="E", type="concept")
        edge = await storage.create_edge(n1["id"], "references", n2["id"])
        assert isinstance(edge["id"], str)
        assert ":" in edge["id"]


class TestDeleteEdge:
    async def test_deletes_existing_edge(self, storage: Storage):
        n1 = await storage.create_note(content="Note")
        n2 = await storage.create_entity(name="Entity", type="concept")
        edge = await storage.create_edge(n1["id"], "references", n2["id"])
        await storage.delete_edge(edge["id"])
        result = await storage.get_edge(edge["id"])
        assert result == {}

    async def test_deleting_nonexistent_edge_does_not_raise(self, storage: Storage):
        """Deleting an edge that doesn't exist should not error."""
        await storage.delete_edge("references:nonexistent")  # Should not raise


class TestCheckEdgeExists:
    async def test_returns_matching_edges(self, storage: Storage):
        n1 = await storage.create_note(content="Note")
        n2 = await storage.create_entity(name="Entity", type="concept")
        await storage.create_edge(n1["id"], "references", n2["id"])
        result = await storage.check_edge_exists(n1["id"], "references", n2["id"])
        assert len(result) >= 1

    async def test_returns_empty_when_no_match(self, storage: Storage):
        n1 = await storage.create_note(content="Note")
        n2 = await storage.create_entity(name="Entity", type="concept")
        result = await storage.check_edge_exists(n1["id"], "references", n2["id"])
        assert result == []


# ── Search Operations ────────────────────────────────────────────────────────


class TestHybridSearch:
    async def test_returns_matching_results(self, storage: Storage):
        await storage.create_note(content="Spaced repetition improves memory")
        results = await storage.hybrid_search("note", "spaced repetition", k=5)
        assert len(results) >= 1

    async def test_does_not_require_pre_computed_embedding(self, storage: Storage):
        """hybrid_search auto-embeds the query using the injected Embedder."""
        await storage.create_note(content="Test content for search")
        results = await storage.hybrid_search("note", "test content", k=5)
        assert isinstance(results, list)

    async def test_excludes_embeddings_from_results(self, storage: Storage):
        await storage.create_note(content="Searchable content")
        results = await storage.hybrid_search("note", "searchable", k=5)
        for r in results:
            assert "embedding" not in r

    async def test_returns_empty_for_no_matches(self, storage: Storage):
        results = await storage.hybrid_search("note", "xyznonexistent", k=5)
        assert results == []

    async def test_searches_entity_table(self, storage: Storage):
        await storage.create_entity(name="spaced repetition", type="concept")
        results = await storage.hybrid_search("entity", "spaced repetition", k=5)
        assert len(results) >= 1

    async def test_respects_k_parameter(self, storage: Storage):
        for i in range(10):
            await storage.create_note(content=f"Document number {i} about testing")
        results = await storage.hybrid_search("note", "testing", k=3)
        assert len(results) <= 3


class TestVectorSearch:
    async def test_returns_results(self, storage: Storage):
        await storage.create_note(content="Vector searchable content")
        results = await storage.vector_search("note", [1.0, 0.0, 0.0, 0.0], k=5)
        assert isinstance(results, list)

    async def test_excludes_embeddings_from_results(self, storage: Storage):
        await storage.create_note(content="Content with embedding")
        results = await storage.vector_search("note", [1.0, 0.0, 0.0, 0.0], k=5)
        for r in results:
            assert "embedding" not in r

    async def test_returns_empty_for_no_matches(self, storage: Storage):
        results = await storage.vector_search("note", [1.0, 0.0, 0.0, 0.0], k=5)
        assert results == []


class TestFulltextSearch:
    async def test_returns_bm25_matches(self, storage: Storage):
        await storage.create_note(content="Fulltext searchable document")
        results = await storage.fulltext_search("note", "fulltext searchable", k=5)
        assert len(results) >= 1

    async def test_excludes_embeddings_from_results(self, storage: Storage):
        await storage.create_note(content="Searchable text")
        results = await storage.fulltext_search("note", "searchable", k=5)
        for r in results:
            assert "embedding" not in r

    async def test_returns_empty_for_no_matches(self, storage: Storage):
        results = await storage.fulltext_search("note", "xyznonexistent", k=5)
        assert results == []


# ── Graph Operations ─────────────────────────────────────────────────────────


class TestGetConnections:
    async def test_returns_edge_neighborhood(self, storage: Storage):
        n1 = await storage.create_note(content="Source note")
        n2 = await storage.create_entity(name="Target", type="concept")
        await storage.create_edge(n1["id"], "references", n2["id"])
        connections = await storage.get_connections(n1["id"])
        assert len(connections) >= 1

    async def test_connection_shape(self, storage: Storage):
        """Each connection dict has edge_label, direction, adjacent_id."""
        n1 = await storage.create_note(content="Source")
        n2 = await storage.create_entity(name="Target", type="concept")
        await storage.create_edge(n1["id"], "references", n2["id"])
        connections = await storage.get_connections(n1["id"])
        conn = connections[0]
        assert "edge_label" in conn
        assert "direction" in conn
        assert "adjacent_id" in conn
        assert conn["direction"] in ("in", "out")

    async def test_shows_outgoing_direction(self, storage: Storage):
        n1 = await storage.create_note(content="Source")
        n2 = await storage.create_entity(name="Target", type="concept")
        await storage.create_edge(n1["id"], "references", n2["id"])
        connections = await storage.get_connections(n1["id"])
        out_conns = [c for c in connections if c["direction"] == "out"]
        assert len(out_conns) >= 1
        assert out_conns[0]["edge_label"] == "references"

    async def test_shows_incoming_direction(self, storage: Storage):
        n1 = await storage.create_note(content="Source")
        n2 = await storage.create_entity(name="Target", type="concept")
        await storage.create_edge(n1["id"], "references", n2["id"])
        connections = await storage.get_connections(n2["id"])
        in_conns = [c for c in connections if c["direction"] == "in"]
        assert len(in_conns) >= 1
        assert in_conns[0]["edge_label"] == "references"

    async def test_returns_empty_for_isolated_node(self, storage: Storage):
        n1 = await storage.create_note(content="Alone")
        connections = await storage.get_connections(n1["id"])
        assert connections == []


# ── Low-level Operations ─────────────────────────────────────────────────────


class TestCountNodes:
    async def test_counts_records_in_table(self, storage: Storage):
        await storage.create_note(content="One")
        await storage.create_note(content="Two")
        count = await storage.count_nodes("note")
        assert count == 2

    async def test_returns_zero_for_empty_table(self, storage: Storage):
        count = await storage.count_nodes("note")
        assert count == 0

    async def test_counts_entities_separately(self, storage: Storage):
        await storage.create_note(content="A note")
        await storage.create_entity(name="An entity", type="concept")
        assert await storage.count_nodes("note") == 1
        assert await storage.count_nodes("entity") == 1


class TestSelectBatch:
    async def test_selects_ordered_records_with_limit(self, storage: Storage):
        n1 = await storage.create_note(content="A")
        n2 = await storage.create_note(content="B")
        n3 = await storage.create_note(content="C")
        # Set different dream_age values to verify ordering
        await storage.update_node(n1["id"], {"dream_age": 10})
        await storage.update_node(n2["id"], {"dream_age": 5})
        await storage.update_node(n3["id"], {"dream_age": 1})
        batch = await storage.select_batch("note", order_by="dream_age", limit=2)
        assert len(batch) == 2
        # Verify ascending order (lowest dream_age first)
        assert batch[0]["dream_age"] <= batch[1]["dream_age"]

    async def test_returns_empty_for_empty_table(self, storage: Storage):
        batch = await storage.select_batch("note", order_by="dream_age", limit=10)
        assert batch == []

    async def test_none_table_selects_across_tables(self, storage: Storage):
        """When table is None, selects from both note and entity."""
        await storage.create_note(content="A note")
        await storage.create_entity(name="An entity", type="concept")
        batch = await storage.select_batch(None, order_by="dream_age", limit=10)
        assert len(batch) >= 2


class TestGetNodeField:
    async def test_returns_specific_field_value(self, storage: Storage):
        created = await storage.create_note(content="Test content")
        content = await storage.get_node_field(created["id"], "content")
        assert content == "Test content"

    async def test_returns_embedding_field(self, storage: Storage):
        created = await storage.create_note(content="Embedded")
        emb = await storage.get_node_field(created["id"], "embedding")
        assert isinstance(emb, list)
        assert len(emb) > 0

    async def test_returns_dream_age_field(self, storage: Storage):
        created = await storage.create_note(content="Test")
        dream_age = await storage.get_node_field(created["id"], "dream_age")
        assert dream_age == 0  # Default value
