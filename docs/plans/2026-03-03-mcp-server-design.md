# MCP Server for Second Brain API

## Context

The brain API currently exposes its functionality (ingest, recall, converse, graph lookup) through REST endpoints consumed by the Go TUI client. To make the knowledge base accessible to any MCP-compatible LLM client (Claude Code, Claude Desktop, Cursor, etc.), we need an MCP server that exposes the brain's core operations as MCP tools.

## Approach

**Custom FastMCP tools embedded in the existing FastAPI app** via streamable HTTP transport. Three hand-crafted MCP tools call the existing agent code directly — no HTTP proxy layer, no auto-generation.

## Tools

### `recall`
- **Parameters:** `question: str`, `hints: list[str] = []`
- **Returns:** Answer text + cited node IDs
- **Implementation:** Calls `run_recall_agent()` from `app.py`
- **Description:** "Search the knowledge base and get a synthesized answer with citations"

### `ingest`
- **Parameters:** `text: str`, `hints: list[str] = []`
- **Returns:** Summary of what was stored
- **Implementation:** Calls `run_ingest_agent()` from `app.py`
- **Description:** "Store new knowledge — notes, entities, and relationships are extracted automatically"

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
- MCP tools share the same globals (`_db`, `_model`, `_embed`) initialized by the existing FastAPI lifespan
- No separate lifespan needed for the MCP app

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
