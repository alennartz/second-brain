"""HTTP recall preserves intake evidence outside graph context and skips deleted chunks."""

import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai import models

from second_brain.agents.recall import RecallOutput
from second_brain.db import Storage
from second_brain.models import Context

app_module = importlib.import_module("second_brain.app")

NOTE = {"id": "note:organized", "content": "An organized fact", "source": "test"}
EDGE = {
    "id": "references:organized",
    "in": "note:organized",
    "out": "entity:topic",
}
CHUNK = {
    "id": "intake_chunk:pending",
    "table": "intake_chunk",
    "intake_id": "intake-1",
    "chunk_index": 1,
    "total_chunks": 3,
    "content": "An unprocessed source passage",
    "source": "cli",
    "hints": ["entity:topic"],
    "unprocessed": True,
}


@pytest.fixture
async def recall_app(monkeypatch):
    storage = Mock(spec=Storage)
    storage.get_nodes.return_value = [NOTE]
    storage.get_edge.return_value = EDGE
    # Citation fetching omits rows already deleted by the background pipeline.
    storage.get_intake_chunks = AsyncMock(return_value=[CHUNK])
    recall_agent = Mock(
        run=AsyncMock(
            return_value=SimpleNamespace(
                output=RecallOutput(
                    answer="Organized and unprocessed evidence support this answer.",
                    cited_node_ids=[NOTE["id"]],
                    cited_edge_ids=[EDGE["id"]],
                    cited_unprocessed_ids=[CHUNK["id"]],
                )
            )
        )
    )
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    monkeypatch.setattr(app_module, "_storage", storage)
    monkeypatch.setattr(app_module, "_recall_agent", recall_agent)
    monkeypatch.setattr(app_module, "_model", None)
    monkeypatch.setattr(app_module, "_scheduler", None)
    async with AsyncClient(
        transport=ASGITransport(app=app_module.app), base_url="http://test"
    ) as client:
        yield client, storage, recall_agent


async def test_http_recall_keeps_unprocessed_citations_outside_graph_arrays(recall_app):
    client, storage, recall_agent = recall_app

    response = await client.post("/recall", json={"question": "What did I submit?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == recall_agent.run.return_value.output.answer
    context = body["context"]
    assert [node["id"] for node in context["nodes"]] == [NOTE["id"]]
    assert [edge["id"] for edge in context["edges"]] == [EDGE["id"]]
    assert context["unprocessed"] == [CHUNK]
    assert context["nodes"][0]["table"] == "note"
    assert context["edges"][0]["from"] == EDGE["in"]
    assert context["edges"][0]["to"] == EDGE["out"]
    assert all("embedding" not in chunk for chunk in context["unprocessed"])
    assert all("connections" not in chunk for chunk in context["unprocessed"])
    storage.get_nodes.assert_awaited_once_with([NOTE["id"]])
    storage.get_edge.assert_awaited_once_with(EDGE["id"])
    storage.get_intake_chunks.assert_awaited_once_with([CHUNK["id"]])


async def test_http_recall_returns_context_when_only_unprocessed_evidence_is_cited(
    recall_app,
):
    client, storage, recall_agent = recall_app
    storage.get_nodes.return_value = []
    recall_agent.run.return_value.output = RecallOutput(
        answer="The submitted source is still unprocessed.",
        cited_unprocessed_ids=[CHUNK["id"]],
    )

    response = await client.post(
        "/recall", json={"question": "Is my intake searchable?"}
    )

    assert response.status_code == 200
    assert response.json()["context"] == {
        "nodes": [],
        "edges": [],
        "unprocessed": [CHUNK],
    }
    assert all(call.args == ([],) for call in storage.get_nodes.await_args_list)
    storage.get_edge.assert_not_awaited()
    storage.get_intake_chunks.assert_awaited_once_with([CHUNK["id"]])


@pytest.mark.parametrize("remaining_chunks", [[CHUNK], []])
async def test_http_recall_skips_chunks_deleted_between_search_and_citation_fetch(
    recall_app, remaining_chunks
):
    client, storage, recall_agent = recall_app
    storage.get_intake_chunks.return_value = remaining_chunks
    recall_agent.run.return_value.output = RecallOutput(
        answer="The answer survives a processed intake chunk.",
        cited_node_ids=[NOTE["id"]],
        cited_unprocessed_ids=[CHUNK["id"], "intake_chunk:deleted"],
    )

    response = await client.post("/recall", json={"question": "What remains?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "The answer survives a processed intake chunk."
    assert body["context"]["unprocessed"] == remaining_chunks
    assert [node["id"] for node in body["context"]["nodes"]] == [NOTE["id"]]
    assert "intake_chunk:deleted" not in response.text
    storage.get_intake_chunks.assert_awaited_once_with(
        [CHUNK["id"], "intake_chunk:deleted"]
    )
    storage.get_nodes.assert_awaited_once_with([NOTE["id"]])
    storage.get_edge.assert_not_awaited()


async def test_http_recall_still_answers_after_every_cited_chunk_disappears(recall_app):
    client, storage, recall_agent = recall_app
    storage.get_nodes.return_value = []
    storage.get_intake_chunks.return_value = []
    recall_agent.run.return_value.output = RecallOutput(
        answer="The retrieved passage was processed while I answered.",
        cited_unprocessed_ids=["intake_chunk:deleted"],
    )

    response = await client.post(
        "/recall", json={"question": "What did the passage say?"}
    )

    assert response.status_code == 200
    assert response.json()["answer"] == recall_agent.run.return_value.output.answer
    assert response.json()["context"] is None
    storage.get_intake_chunks.assert_awaited_once_with(["intake_chunk:deleted"])
    assert all(call.args == ([],) for call in storage.get_nodes.await_args_list)
    storage.get_edge.assert_not_awaited()


@pytest.mark.parametrize("endpoint", ["/converse", "/converse/stream"])
async def test_http_converse_retains_unprocessed_only_context_from_recall(
    recall_app, monkeypatch, endpoint
):
    client, _, _ = recall_app

    async def converse_turn(message, *args, deps, **kwargs):
        deps.context = Context(unprocessed=[CHUNK])
        return "The source remains unprocessed."

    async def converse_run(message, *, deps, **kwargs):
        return SimpleNamespace(output=await converse_turn(message, deps=deps))

    monkeypatch.setattr(
        app_module,
        "run_converse_turn",
        AsyncMock(side_effect=converse_turn),
        raising=False,
    )
    monkeypatch.setattr(
        app_module, "_converse_agent", Mock(run=AsyncMock(side_effect=converse_run))
    )

    response = await client.post(endpoint, json={"message": "What did I submit?"})

    assert response.status_code == 200
    if endpoint.endswith("/stream"):
        assert "event: error" not in response.text
        done_events = [
            event
            for event in response.text.split("\n\n")
            if event.startswith("event: done\n")
        ]
        assert len(done_events) == 1
        body = json.loads(done_events[0].split("data: ", 1)[1])
    else:
        body = response.json()
    assert body["context"] == {"nodes": [], "edges": [], "unprocessed": [CHUNK]}
