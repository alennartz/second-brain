from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from second_brain.app import app


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
