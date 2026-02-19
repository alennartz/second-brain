from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from second_brain.app import app


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
        mock.return_value = "Found nothing relevant"
        resp = await client.post("/recall", json={"question": "what do I know?"})
    assert resp.status_code == 200
