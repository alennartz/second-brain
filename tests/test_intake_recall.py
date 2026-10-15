"""Behavioral tests for cross-layer memory recall with queued chunks."""

from unittest.mock import AsyncMock

import pytest

from second_brain.models import MemorySearchResult
from second_brain.tools.recall_tools import search_memory


@pytest.fixture
def memory_storage(storage):
    async def hybrid_search(table: str, query_text: str, k: int = 5) -> list[dict]:
        del query_text, k
        if table == "note":
            return [
                {
                    "id": "note:1",
                    "table": "note",
                    "content": "organized memory",
                }
            ]
        return [
            {
                "id": "entity:1",
                "table": "entity",
                "name": "memory",
            }
        ]

    storage.hybrid_search = AsyncMock(side_effect=hybrid_search)  # type: ignore[method-assign]
    storage.search_intake_chunks = AsyncMock(
        return_value=[
            {
                "id": "intake_chunk:1",
                "table": "intake_chunk",
                "intake_id": "intake-1",
                "chunk_index": 0,
                "content": "queued evidence",
                "unprocessed": True,
            }
        ]
    )  # type: ignore[method-assign]
    storage.get_connections = AsyncMock(return_value=[])  # type: ignore[method-assign]
    return storage


async def test_search_memory_returns_graph_nodes_and_unprocessed_chunks_separately(
    memory_storage,
):
    result = await search_memory(memory_storage, "spaced repetition", k=5)

    assert isinstance(result, MemorySearchResult)
    assert result.nodes
    assert result.unprocessed
    assert all(node["table"] in {"note", "entity"} for node in result.nodes)
    assert all(chunk["table"] == "intake_chunk" for chunk in result.unprocessed)
    assert all(chunk.get("unprocessed") is True for chunk in result.unprocessed)
    assert not any("connections" in chunk for chunk in result.unprocessed)


async def test_search_memory_caps_each_layer_before_balanced_fusion(memory_storage):
    result = await search_memory(memory_storage, "memory", k=1)

    assert len(result.nodes) <= 1
    assert len(result.unprocessed) <= 1
    assert result.nodes and result.unprocessed


async def test_search_memory_enriches_only_graph_nodes(memory_storage):
    result = await search_memory(memory_storage, "memory", k=5)

    memory_storage.get_connections.assert_awaited()
    assert all("connections" in node for node in result.nodes)
    assert all("connections" not in chunk for chunk in result.unprocessed)
