# MCP Server for Second Brain API

## Context

The brain API exposes intake staging, recall, converse, and graph lookup through REST endpoints. The embedded MCP server exposes staging, recall, and graph lookup to MCP-compatible clients. Intake staging shares the background pipeline used by HTTP and converse.

## Approach

**Custom FastMCP tools embedded in the existing FastAPI app** via streamable HTTP transport. Three hand-crafted MCP tools call configured application callbacks. Ingest stages chunks through the shared pipeline; recall runs the recall agent. There is no HTTP proxy layer or auto-generation.

## Tools

### `recall`
- **Parameters:** `question: str`, `hints: list[str] = []`
- **Returns:** Answer text with separate cited graph-node and unprocessed-evidence IDs
- **Implementation:** Calls the configured recall callback from `app.py`
- **Description:** Searches organized graph records and unprocessed intake chunks.

### `ingest`
- **Parameters:** `text: str`, `hints: list[str] = []`
- **Returns:** A queued chunk count. Chunks become searchable before this call returns.
- **Implementation:** Calls the configured staging callback from `app.py`
- **Description:** Stages source text for immediate search and background organization.

### `graph_lookup`
- **Parameters:** `record_id: str`
- **Returns:** Node data + list of connections (edge + connected node)
- **Implementation:** Reuses `get_node()` + `_get_raw_connections()` from `app.py`
- **Description:** "Look up a node and its connections in the knowledge graph"

## Architecture

```
[MCP Client] --streamable HTTP--> [FastAPI :8000/mcp/]
                                       |
[Browser/TUI] --REST--------------> [FastAPI :8000/]
                                       |
                                       v
                                  [SurrealDB]
```

- New file: `src/second_brain/mcp.py` — defines FastMCP instance + 3 tools
- Modified: `src/second_brain/app.py` — mounts MCP ASGI app at `/mcp`
- MCP tools use callbacks configured during the FastAPI lifespan. Staging, recall, and graph lookup use the app's shared storage and agents.
- No separate lifespan is needed for the MCP app

## Client Configuration

```json
{
  "mcpServers": {
    "second-brain": {
      "url": "http://localhost:8000/mcp/"
    }
  }
}
```

## Dependencies

- Add `fastmcp` to `pyproject.toml`
