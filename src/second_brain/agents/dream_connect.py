import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal

from second_brain.models import make_serializable, strip_embeddings
from second_brain.tools import dream_tools, ingest_tools, recall_tools

logger = logging.getLogger(__name__)


@dataclass
class ConnectDeps:
    db: AsyncSurreal  # pyright: ignore[reportGeneralTypeIssues]
    embed_fn: Callable[[str], Awaitable[list[float]]]
    cancel: asyncio.Event
    touched_ids: list[str] = field(default_factory=list)


def create_connect_agent() -> Agent[ConnectDeps, str]:
    agent = Agent(
        deps_type=ConnectDeps,
        output_type=str,
        system_prompt=(
            "You are a knowledge graph connection discovery agent. You explore the graph "
            "to find meaningful relationships that are missing.\n\n"
            "Strategy (in priority order):\n"
            "1. **Structural patterns first**: Use find_unlinked_cooccurrences to find entities "
            "that share notes but aren't directly connected. This is the highest-signal source "
            "of missing connections.\n"
            "2. **Graph exploration**: Use explore to traverse the neighborhood of each node. "
            "Look for entities reachable through intermediate nodes but not directly linked. "
            "Vary direction and node_types to discover different patterns.\n"
            "3. **Similarity fallback**: For nodes with very few connections, use find_similar "
            "to find semantically related but unconnected nodes.\n\n"
            "When you find a missing connection:\n"
            "- Read the actual content of both nodes (use get_node if needed)\n"
            "- Decide if a real, meaningful relationship exists\n"
            "- Choose a descriptive edge name (e.g., built_with, inspired_by, depends_on — "
            "NOT generic labels like relates_to or references)\n"
            "- Create the edge using create_edges\n\n"
            "IMPORTANT — you are NOT a deduplication agent. NEVER create edges like "
            "duplicate_of, same_as, identical_to, alias_of, or any edge that indicates "
            "two nodes are the same thing. Deduplication is handled by a separate agent. "
            "Your job is ONLY to create edges representing real semantic relationships "
            "between distinct concepts.\n\n"
            "Be judicious: only create edges for genuine relationships. Not every pair of "
            "co-occurring entities needs a direct link.\n\n"
            "Return a summary of connections discovered and created."
        ),
    )

    @agent.tool
    async def find_unlinked_cooccurrences(
        ctx: RunContext[ConnectDeps], record_id: str
    ) -> list[dict]:
        """Find entities that share notes with this entity but have no direct edge.
        Returns entities with their shared note IDs. High-signal source of missing connections."""
        logger.info("connect: find_unlinked_cooccurrences id=%s", record_id)
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        return await dream_tools.find_unlinked_cooccurrences(ctx.deps.db, record_id)

    @agent.tool
    async def explore(
        ctx: RunContext[ConnectDeps],
        record_id: str,
        direction: str = "both",
        node_types: list[str] | None = None,
        depth: int = 2,
    ) -> dict:
        """Explore the graph neighborhood from a node.
        direction: 'out', 'in', or 'both'.
        node_types: filter targets by table, e.g. ['entity'], ['note'], ['entity', 'note'].
        depth: max hops (1-3).
        Returns target nodes with paths showing how they were reached."""
        logger.info(
            "connect: explore id=%s dir=%s types=%s depth=%d",
            record_id,
            direction,
            node_types,
            depth,
        )
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        return await dream_tools.explore(
            ctx.deps.db, record_id, direction, node_types, depth
        )

    @agent.tool
    async def get_node(ctx: RunContext[ConnectDeps], record_id: str) -> dict:
        """Get a single node by ID for closer inspection."""
        logger.info("connect: get_node id=%s", record_id)
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        node = await recall_tools.get_node(ctx.deps.db, record_id)
        if not node:
            return {"error": f"Node {record_id} not found"}
        return strip_embeddings(make_serializable(node))

    @agent.tool
    async def find_similar(
        ctx: RunContext[ConnectDeps], record_id: str, k: int = 5
    ) -> list[dict]:
        """Find semantically similar nodes by embedding. Fallback for structurally isolated nodes."""
        logger.info("connect: find_similar id=%s k=%d", record_id, k)
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        return await dream_tools.find_similar(ctx.deps.db, record_id, k)

    @agent.tool
    async def create_edges(
        ctx: RunContext[ConnectDeps], edges: list[dict]
    ) -> list[dict]:
        """Create relationship edges. Each dict needs 'from_id', 'edge_table', 'to_id', optional 'context'.
        Use descriptive edge names: built_with, inspired_by, depends_on, etc."""
        logger.info("connect: create_edges (%d edges)", len(edges))
        try:
            results = await ingest_tools.create_edges(ctx.deps.db, edges)
            for r in results:
                rid = str(r.get("id", ""))
                if rid and rid not in ctx.deps.touched_ids:
                    ctx.deps.touched_ids.append(rid)
            return [make_serializable(r) for r in results]
        except Exception as e:
            logger.error("connect: create_edges failed: %s", e)
            return [{"error": str(e)}]

    return agent
