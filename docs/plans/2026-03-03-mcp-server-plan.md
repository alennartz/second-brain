# MCP Server Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expose the second brain's recall, ingest, and graph lookup as MCP tools via streamable HTTP, embedded in the existing FastAPI app.

**Architecture:** New `mcp.py` module defines a FastMCP instance with 3 tools that call existing agent runner functions. The MCP ASGI app is mounted at `/mcp` in the FastAPI app, with its lifespan nested inside the existing lifespan for transport session management.

**Tech Stack:** FastMCP (Python MCP framework), FastAPI, existing PydanticAI agents

---

### Task 1: Add fastmcp dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add fastmcp to dependencies**

In `pyproject.toml`, add `"fastmcp>=2.0.0"` to the `dependencies` list.

**Step 2: Install**

Run: `uv sync`
Expected: fastmcp installed successfully

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add fastmcp dependency"
```

---

### Task 2: Create MCP module with recall tool (TDD)

**Files:**
- Create: `src/second_brain/mcp.py`
- Create: `tests/test_mcp.py`
- Modify: `src/second_brain/app.py`

**Step 1: Write the failing test for recall tool**

`tests/test_mcp.py`:
```python
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from second_brain.app import app, RecallResponse
from second_brain.models import Context


@patch("second_brain.mcp._run_recall", new_callable=AsyncMock)
async def test_mcp_recall_tool(mock_recall):
    mock_recall.return_value = RecallResponse(
        answer="Paris is the capital of France",
        context=None,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        tool_names = [t["name"] for t in data["result"]["tools"]]
        assert "recall" in tool_names
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp.py::test_mcp_recall_tool -v`
Expected: FAIL (mcp module doesn't exist)

**Step 3: Create minimal MCP module**

`src/second_brain/mcp.py`:
```python
from __future__ import annotations

import json
import logging
from typing import Any

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "Second Brain",
    instructions=(
        "A personal knowledge engine. Use 'recall' to search for information, "
        "'ingest' to store new knowledge, and 'graph_lookup' to explore "
        "connections between concepts."
    ),
)

# These will be set by app.py lifespan via configure()
_run_recall: Any = None
_run_ingest: Any = None
_get_graph: Any = None


def configure(
    *,
    run_recall: Any,
    run_ingest: Any,
    get_graph: Any,
) -> None:
    """Wire up the MCP tools to the app's agent runners."""
    global _run_recall, _run_ingest, _get_graph
    _run_recall = run_recall
    _run_ingest = run_ingest
    _get_graph = get_graph


@mcp.tool
async def recall(question: str, hints: list[str] | None = None) -> str:
    """Search the knowledge base and get a synthesized answer with citations.

    Use this to find information that was previously stored in the brain.
    Returns an answer synthesized from matching notes and entities,
    along with cited node IDs you can explore with graph_lookup.
    """
    result = await _run_recall(question, hints)
    parts = [result.answer]
    if result.context and result.context.nodes:
        ids = [n.get("id", "") for n in result.context.nodes]
        parts.append(f"\nCited nodes: {', '.join(ids)}")
    return "\n".join(parts)
```

**Step 4: Mount in app.py**

Add to `src/second_brain/app.py` imports:
```python
from second_brain.mcp import configure as configure_mcp, mcp
```

After `app = FastAPI(...)`, add:
```python
_mcp_app = mcp.http_app(path="/")
app.mount("/mcp", _mcp_app)
```

Update the lifespan to nest the MCP lifespan and call `configure_mcp`:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing init code (DB, model, embed, scheduler — all unchanged) ...

    configure_mcp(
        run_recall=run_recall_agent,
        run_ingest=run_ingest_agent,
        get_graph=get_graph_data,
    )

    async with _mcp_app.router.lifespan_context(app):
        yield

    # ... existing cleanup code (scheduler stop, DB close — unchanged) ...
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp.py::test_mcp_recall_tool -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/second_brain/mcp.py tests/test_mcp.py src/second_brain/app.py
git commit -m "feat(mcp): add MCP server with recall tool"
```

---

### Task 3: Add ingest tool (TDD)

**Files:**
- Modify: `src/second_brain/mcp.py`
- Modify: `tests/test_mcp.py`

**Step 1: Write the failing test**

Add to `tests/test_mcp.py`:
```python
async def test_mcp_ingest_tool():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
        )
        tool_names = [t["name"] for t in resp.json()["result"]["tools"]]
        assert "ingest" in tool_names
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp.py::test_mcp_ingest_tool -v`
Expected: FAIL

**Step 3: Add ingest tool to mcp.py**

```python
@mcp.tool
async def ingest(text: str, hints: list[str] | None = None) -> str:
    """Store new knowledge in the brain.

    Notes, entities, and relationships are extracted automatically.
    The brain deduplicates against existing knowledge and creates
    semantic connections between concepts.
    """
    return await _run_ingest(text, hints)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp.py::test_mcp_ingest_tool -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/second_brain/mcp.py tests/test_mcp.py
git commit -m "feat(mcp): add ingest tool"
```

---

### Task 4: Add graph_lookup tool (TDD)

**Files:**
- Modify: `src/second_brain/mcp.py`
- Modify: `src/second_brain/app.py` (extract graph logic into reusable function)
- Modify: `tests/test_mcp.py`

**Step 1: Write the failing test**

Add to `tests/test_mcp.py`:
```python
async def test_mcp_graph_lookup_tool():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
        )
        tool_names = [t["name"] for t in resp.json()["result"]["tools"]]
        assert "graph_lookup" in tool_names
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp.py::test_mcp_graph_lookup_tool -v`
Expected: FAIL

**Step 3: Extract graph data function in app.py**

In `app.py`, extract the graph lookup logic from the `get_graph` endpoint into a reusable `get_graph_data` function:

```python
async def get_graph_data(record_id: str) -> GraphResponse | None:
    """Fetch a node and its connections. Returns None if not found."""
    node = await get_node(_db, record_id)
    if not node:
        return None

    raw_edges = await _get_raw_connections(_db, record_id)
    connections = []
    for edge in raw_edges:
        edge_s = make_serializable(edge)
        other_id = (
            str(edge_s.get("in"))
            if str(edge_s.get("out")) == record_id
            else str(edge_s.get("out"))
        )
        if other_id:
            other_node = await get_node(_db, str(other_id))
            if other_node:
                connections.append(
                    ConnectionItem(
                        edge=normalize_edge(edge_s),
                        node=normalize_node(make_serializable(other_node)),
                    )
                )
    return GraphResponse(
        node=normalize_node(make_serializable(node)), connections=connections
    )
```

Update the `/graph` endpoint to use it:
```python
@app.get("/graph/{record_id:path}", response_model=GraphResponse)
async def get_graph(record_id: str):
    result = await get_graph_data(record_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Node {record_id} not found")
    return result
```

**Step 4: Add graph_lookup tool to mcp.py**

```python
@mcp.tool
async def graph_lookup(record_id: str) -> str:
    """Look up a node and its connections in the knowledge graph.

    Use this to explore connections from node IDs returned by recall.
    Returns the node's data and all its relationships to other nodes.

    Args:
        record_id: A node ID like 'entity:abc123' or 'note:xyz789'
    """
    import json
    result = await _get_graph(record_id)
    if not result:
        return f"Node '{record_id}' not found."
    return json.dumps(result.model_dump(), indent=2, default=str)
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp.py::test_mcp_graph_lookup_tool -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/second_brain/mcp.py src/second_brain/app.py tests/test_mcp.py
git commit -m "feat(mcp): add graph_lookup tool"
```

---

### Task 5: Integration test — full MCP tool call

**Files:**
- Modify: `tests/test_mcp.py`

**Step 1: Write integration test for recall tool call**

```python
@patch("second_brain.mcp._run_recall", new_callable=AsyncMock)
async def test_mcp_recall_tool_call(mock_recall):
    mock_recall.return_value = RecallResponse(
        answer="Paris is the capital",
        context=None,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
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
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "Paris" in str(data["result"])
```

**Step 2: Run test**

Run: `uv run pytest tests/test_mcp.py::test_mcp_recall_tool_call -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_mcp.py
git commit -m "test(mcp): add integration test for MCP tool call"
```

---

### Task 6: Run all checks and fix issues

**Step 1: Run full test suite**

Run: `make check`
Expected: All checks pass (lint + typecheck + tests)

**Step 2: Fix any issues found**

Address lint, type, or test failures.

**Step 3: Final commit**

```bash
git add -A
git commit -m "chore: fix lint/type issues from MCP integration"
```

---

## Verification

After implementation, test end-to-end:

1. Start the server: `make dev`
2. Verify MCP endpoint responds:
   ```bash
   curl -X POST http://localhost:8000/mcp/ \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
   ```
   Expected: JSON response listing `recall`, `ingest`, `graph_lookup` tools

3. Add to Claude Code config (`~/.claude.json` or project `.mcp.json`):
   ```json
   {
     "mcpServers": {
       "second-brain": {
         "url": "http://localhost:8000/mcp/"
       }
     }
   }
   ```

4. Verify existing REST endpoints still work:
   ```bash
   curl http://localhost:8000/health
   ```

## Key files

- `src/second_brain/mcp.py` (new) — FastMCP instance + 3 tool definitions
- `src/second_brain/app.py` (modify) — mount MCP app, nest lifespan, extract `get_graph_data`
- `tests/test_mcp.py` (new) — MCP tool tests
- `pyproject.toml` (modify) — add fastmcp dependency
