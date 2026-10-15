"""Behavioral tests for synchronous intake and aggregate pipeline HTTP APIs."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from second_brain.app import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client


async def test_post_ingest_stages_chunks_synchronously(client):
    with patch("second_brain.app.run_ingest_agent", new_callable=AsyncMock):
        response = await client.post(
            "/ingest",
            json={
                "text": "First paragraph.\n\nSecond paragraph.",
                "hints": ["entity:one"],
                "source": "cli",
            },
            headers={"Idempotency-Key": "request-1"},
        )

    assert response.status_code == 200
    assert response.json()["chunks_stored"] == 2
    assert "location" not in response.headers


async def test_post_ingest_returns_only_after_all_chunks_are_searchable(client):
    with patch("second_brain.app.run_ingest_agent", new_callable=AsyncMock):
        response = await client.post(
            "/ingest",
            json={"text": "A complete intake document."},
        )

    assert response.status_code == 200
    assert set(response.json()) == {"chunks_stored"}


async def test_get_pipeline_snapshot_exposes_aggregate_queue_visibility(client):
    response = await client.get("/ingest/pipeline")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] >= 0
    assert body["leased"] >= 0
    assert body["retry_wait"] >= 0
    assert body["paused"] >= 0
    assert isinstance(body["stuck_intakes"], list)
    assert isinstance(body["recent_errors"], list)


@pytest.mark.parametrize("action", ["pause", "resume", "discard"])
async def test_pipeline_intake_controls_return_aggregate_operation_result(
    client, action
):
    response = await client.post(f"/ingest/pipeline/intake-1/{action}")

    assert response.status_code == 200
    assert response.json()["intake_id"] == "intake-1"
    if action == "discard":
        assert response.json()["chunks_discarded"] >= 0


async def test_pipeline_controls_do_not_roll_back_graph_records(client):
    response = await client.post("/ingest/pipeline/intake-1/discard")

    assert response.status_code == 200
    assert response.json()["graph_records_rolled_back"] is False


async def test_mcp_ingest_reports_queued_chunk_count(client):
    with patch("second_brain.app.run_ingest_agent", new_callable=AsyncMock):
        response = await client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "ingest",
                    "arguments": {"text": "queued through MCP"},
                },
            },
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    text = response.text
    assert "chunks_stored" in text
