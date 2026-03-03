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


async def test_ingest_endpoint_exists(client):
    with patch("second_brain.app.run_ingest_agent", new_callable=AsyncMock) as mock:
        mock.return_value = "Stored 1 note"
        resp = await client.post("/ingest", json={"text": "test note"})
    assert resp.status_code == 200
    mock.assert_called_once_with("test note", None)


async def test_ingest_with_hints(client):
    with patch("second_brain.app.run_ingest_agent", new_callable=AsyncMock) as mock:
        mock.return_value = "Stored 1 note"
        resp = await client.post(
            "/ingest", json={"text": "test", "hints": ["entity:1"]}
        )
    assert resp.status_code == 200
    mock.assert_called_once_with("test", ["entity:1"])


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


async def test_graph_endpoint(client):
    with (
        patch("second_brain.app.get_node", new_callable=AsyncMock) as mock_node,
        patch(
            "second_brain.app._get_raw_connections", new_callable=AsyncMock
        ) as mock_conn,
    ):
        mock_node.side_effect = [
            {"id": "note:1", "content": "test note", "source": "api"},  # main node
            {"id": "entity:sr", "name": "spaced rep", "type": "concept"},  # other node
        ]
        mock_conn.return_value = [
            {"id": "references:abc", "in": "entity:sr", "out": "note:1"},
        ]
        resp = await client.get("/graph/note:1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["node"]["id"] == "note:1"
    assert len(data["connections"]) == 1
    assert data["connections"][0]["node"]["id"] == "entity:sr"


async def test_graph_endpoint_404(client):
    with patch("second_brain.app.get_node", new_callable=AsyncMock) as mock_node:
        mock_node.return_value = {}
        resp = await client.get("/graph/note:nonexistent")
    assert resp.status_code == 404


async def test_graph_endpoint_no_connections(client):
    with (
        patch("second_brain.app.get_node", new_callable=AsyncMock) as mock_node,
        patch(
            "second_brain.app._get_raw_connections", new_callable=AsyncMock
        ) as mock_conn,
    ):
        mock_node.return_value = {"id": "note:1", "content": "lonely node"}
        mock_conn.return_value = []
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
