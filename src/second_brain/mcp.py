from __future__ import annotations

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
