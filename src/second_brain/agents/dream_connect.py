import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal

from second_brain.models import make_serializable
from second_brain.tools import dream_tools, ingest_tools, recall_tools

_ID_FMT_ERROR = (
    "Invalid record_id '{rid}': must be 'table:id' format (e.g. 'entity:abc123')"
)


def _bad_id(rid: str) -> bool:
    return ":" not in rid


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
            "You are a knowledge graph connection discovery agent. Your job is to find "
            "meaningful relationships between entities that should be linked but aren't.\n\n"
            "## Strategy\n\n"
            "For each entity node in the batch:\n\n"
            "1. **Find related entities**: Use find_similar to discover semantically "
            "related entities anywhere in the graph. These are your candidates — "
            "entities that might be connected but aren't yet.\n"
            "2. **Check what's already connected**: Use explore (depth 1) to see the "
            "entity's existing connections. Don't recreate edges that already exist.\n"
            "3. **Find co-occurring entities**: Use find_unlinked_cooccurrences to find "
            "entities that share notes with this one but lack a direct edge.\n"
            "4. **Read and judge**: For promising candidates, use get_node to read both "
            "entities. If a real relationship exists (e.g., one influenced the other, "
            "one was part of the other, one created the other), create an edge.\n\n"
            "The most valuable connections are between entities from DIFFERENT ingests "
            "— information that was added at different times but describes related things. "
            "For example, if one snippet mentions 'Tsiolkovsky inspired Oberth' and "
            "another mentions 'Oberth mentored von Braun', both entities exist but may "
            "not be connected yet.\n\n"
            "## Edge naming\n\n"
            "Choose clear, specific edge names that describe the relationship:\n"
            "- inspired_by, mentored, developed, funded, commissioned, trained_at, "
            "member_of, located_in, part_of, succeeded, etc.\n"
            "- Do NOT use generic labels like relates_to, references, connected_to.\n"
            "- Prefer reusing existing edge names in the graph over inventing new ones "
            "for the same kind of relationship.\n\n"
            "## Rules\n\n"
            "- NEVER create edges like duplicate_of, same_as, alias_of — deduplication "
            "is handled by a separate agent.\n"
            "- Only create edges for genuine relationships you can justify from the "
            "entity names and descriptions.\n"
            "- Process every entity in the batch.\n\n"
            "Return a summary of connections discovered and created."
        ),
    )

    @agent.tool
    async def find_similar(
        ctx: RunContext[ConnectDeps], record_id: str, k: int = 10
    ) -> list[dict]:
        """Find semantically related entities anywhere in the graph. Returns entities
        with their names, types, and descriptions. Use this to discover candidates for
        missing connections — especially entities from different ingests that should
        be linked.
        record_id: fully-qualified SurrealDB record ID, e.g. 'entity:abc123'."""
        logger.info("connect: find_similar id=%s k=%d", record_id, k)
        if _bad_id(record_id):
            return [{"error": _ID_FMT_ERROR.format(rid=record_id)}]
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        return await dream_tools.find_similar(ctx.deps.db, record_id, k)

    @agent.tool
    async def find_unlinked_cooccurrences(
        ctx: RunContext[ConnectDeps], record_id: str
    ) -> list[dict]:
        """Find entities that share notes with this entity but have no direct edge.
        record_id: fully-qualified SurrealDB record ID, e.g. 'entity:abc123'.
        Returns entities with their shared note IDs."""
        logger.info("connect: find_unlinked_cooccurrences id=%s", record_id)
        if _bad_id(record_id):
            return [{"error": _ID_FMT_ERROR.format(rid=record_id)}]
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        result = await dream_tools.find_unlinked_cooccurrences(
            ctx.deps.db, record_id, cancel=ctx.deps.cancel
        )
        if isinstance(result, dict):
            return [result]
        return result

    @agent.tool
    async def explore(
        ctx: RunContext[ConnectDeps],
        record_id: str,
        direction: str = "both",
        node_types: list[str] | None = None,
        depth: int = 2,
    ) -> dict:
        """Explore the graph neighborhood from a node. Use to see what's already
        connected (depth 1) or to find entities reachable through intermediate
        nodes (depth 2-3).
        record_id: fully-qualified SurrealDB record ID, e.g. 'entity:abc123'.
        direction: 'out', 'in', or 'both'.
        node_types: filter by table, e.g. ['entity'].
        depth: max hops (1-3)."""
        logger.info(
            "connect: explore id=%s dir=%s types=%s depth=%d",
            record_id,
            direction,
            node_types,
            depth,
        )
        if _bad_id(record_id):
            return {"error": _ID_FMT_ERROR.format(rid=record_id)}
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        return await dream_tools.explore(
            ctx.deps.db, record_id, direction, node_types, depth
        )

    @agent.tool
    async def get_node(ctx: RunContext[ConnectDeps], record_id: str) -> dict:
        """Get a single node by ID for closer inspection.
        record_id: fully-qualified SurrealDB record ID, e.g. 'entity:abc123'."""
        logger.info("connect: get_node id=%s", record_id)
        if _bad_id(record_id):
            return {"error": _ID_FMT_ERROR.format(rid=record_id)}
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        node = await recall_tools.get_node(ctx.deps.db, record_id)
        if not node:
            return {"error": f"Node {record_id} not found"}
        return make_serializable(node)

    @agent.tool
    async def create_edges(
        ctx: RunContext[ConnectDeps], edges: list[dict]
    ) -> list[dict]:
        """Create relationship edges. Each dict needs 'from_id', 'edge_table', 'to_id',
        optional 'context'."""
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
