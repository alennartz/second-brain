from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from second_brain.app import RecallResponse, app
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
