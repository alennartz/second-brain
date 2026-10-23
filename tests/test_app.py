from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from second_brain.app import ConverseResponse, RecallResponse, app
from second_brain.models import Context


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_recall_endpoint_surfaces_usage_limit(client, monkeypatch):
    import importlib

    app_module = importlib.import_module("second_brain.app")
    from second_brain.agents.recall import RecallRunLimitExceeded

    monkeypatch.setattr(app_module, "_storage", object())
    monkeypatch.setattr(
        app_module,
        "run_recall",
        AsyncMock(side_effect=RecallRunLimitExceeded("tool budget exhausted")),
    )

    response = await client.post("/recall", json={"question": "memory?"})

    assert response.status_code == 502
    assert "tool budget exhausted" in response.json()["detail"]


async def test_recall_endpoint_exists(client):
    with patch("second_brain.app.run_recall_agent", new_callable=AsyncMock) as mock:
        mock.return_value = RecallResponse(answer="Found nothing relevant")
        resp = await client.post("/recall", json={"question": "what do I know?"})
    assert resp.status_code == 200
    assert resp.json()["answer"] == "Found nothing relevant"


async def test_recall_with_hints(client):
    """Verify hints are passed through to run_recall_agent."""
    with patch("second_brain.app.run_recall_agent", new_callable=AsyncMock) as mock:
        mock.return_value = RecallResponse(answer="Here is what I found")
        resp = await client.post(
            "/recall",
            json={"question": "what about X?", "hints": ["note:1", "entity:sr"]},
        )
    assert resp.status_code == 200
    mock.assert_called_once_with("what about X?", ["note:1", "entity:sr"])


async def test_recall_response_with_context(client):
    """Verify recall response includes context when present."""
    ctx = Context(
        nodes=[{"id": "note:1", "content": "test note"}],
        edges=[{"id": "references:abc", "in": "note:1", "out": "entity:sr"}],
    )
    with patch("second_brain.app.run_recall_agent", new_callable=AsyncMock) as mock:
        mock.return_value = RecallResponse(answer="Found info", context=ctx)
        resp = await client.post("/recall", json={"question": "test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Found info"
    assert body["context"] is not None
    assert len(body["context"]["nodes"]) == 1
    assert body["context"]["nodes"][0]["id"] == "note:1"
    assert len(body["context"]["edges"]) == 1


async def test_recall_rejects_unresolvable_citations(client, storage, monkeypatch):
    """Recall must not return an answer when its required citations cannot resolve."""
    from second_brain.agents.recall import RecallOutput
    from second_brain.app import _recall_agent
    from tests.test_converse_agent import RECALL_ANSWER

    async def fake_run(prompt, **kwargs):
        class Result:
            output = RecallOutput(
                answer=RECALL_ANSWER,
                has_evidence=True,
                cited_node_ids=["entity:missing"],
                cited_edge_ids=["references:missing"],
                cited_unprocessed_ids=[],
            )

        return Result()

    monkeypatch.setattr("second_brain.app._storage", storage)
    monkeypatch.setattr(_recall_agent, "run", fake_run)
    resp = await client.post("/recall", json={"question": "who wrote notes?"})
    assert resp.status_code == 502
    assert "none resolved to stored evidence" in resp.json()["detail"]


async def test_graph_endpoint(client):
    with patch("second_brain.app.get_graph_data", new_callable=AsyncMock) as mock_graph:
        from second_brain.app import ConnectionItem, GraphResponse

        mock_graph.return_value = GraphResponse(
            node={"id": "note:1", "content": "test note", "source": "api"},
            connections=[
                ConnectionItem(
                    edge={"id": "references:abc", "in": "entity:sr", "out": "note:1"},
                    node={"id": "entity:sr", "name": "spaced rep", "type": "concept"},
                )
            ],
        )
        resp = await client.get("/graph/note:1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["node"]["id"] == "note:1"
    assert len(data["connections"]) == 1
    assert data["connections"][0]["node"]["id"] == "entity:sr"


async def test_graph_endpoint_404(client):
    with patch("second_brain.app.get_graph_data", new_callable=AsyncMock) as mock_graph:
        mock_graph.return_value = None
        resp = await client.get("/graph/note:nonexistent")
    assert resp.status_code == 404


async def test_graph_endpoint_no_connections(client):
    with patch("second_brain.app.get_graph_data", new_callable=AsyncMock) as mock_graph:
        from second_brain.app import GraphResponse

        mock_graph.return_value = GraphResponse(
            node={"id": "note:1", "content": "lonely node"},
            connections=[],
        )
        resp = await client.get("/graph/note:1")
    assert resp.status_code == 200
    assert resp.json()["connections"] == []


async def test_converse_endpoint(client):
    with patch("second_brain.app.run_converse_agent", new_callable=AsyncMock) as mock:
        mock.return_value = ConverseResponse(response="Hello!")
        resp = await client.post("/converse", json={"message": "hi"})
    assert resp.status_code == 200
    assert resp.json()["response"] == "Hello!"


async def test_dream_scheduler_not_started_in_test_mode():
    """In test mode, the dream scheduler should not be running."""
    from second_brain.app import _scheduler

    assert _scheduler is None


async def test_converse_with_history(client):
    with patch("second_brain.app.run_converse_agent", new_callable=AsyncMock) as mock:
        mock.return_value = ConverseResponse(response="I remember that")
        resp = await client.post(
            "/converse",
            json={
                "message": "what about that?",
                "history": [
                    {
                        "user": "tell me about GTD",
                        "assistant": {"response": "GTD is a methodology..."},
                    }
                ],
            },
        )
    assert resp.status_code == 200
    assert resp.json()["response"] == "I remember that"
