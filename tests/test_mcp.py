from unittest.mock import AsyncMock, patch

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from second_brain.app import RecallResponse, app


async def test_mcp_lists_recall_tool():
    async with (
        LifespanManager(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        resp = await client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        tool_names = [t["name"] for t in data["result"]["tools"]]
        assert "recall" in tool_names


async def test_mcp_lists_ingest_tool():
    async with (
        LifespanManager(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        resp = await client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        tool_names = [t["name"] for t in resp.json()["result"]["tools"]]
        assert "ingest" in tool_names


async def test_mcp_lists_graph_lookup_tool():
    async with (
        LifespanManager(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        resp = await client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        tool_names = [t["name"] for t in resp.json()["result"]["tools"]]
        assert "graph_lookup" in tool_names


async def test_mcp_recall_tool_call():
    async with (
        LifespanManager(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        # Patch _run_recall after lifespan has configured the MCP globals
        mock_recall = AsyncMock(
            return_value=RecallResponse(
                answer="Paris is the capital",
                context=None,
            )
        )
        with patch("second_brain.mcp._run_recall", mock_recall):
            resp = await client.post(
                "/mcp/",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "recall",
                        "arguments": {"question": "What is the capital of France?"},
                    },
                },
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            # The result should contain the answer text
            content = data["result"]["content"]
            text_parts = [c["text"] for c in content if c["type"] == "text"]
            assert any("Paris" in t for t in text_parts)
