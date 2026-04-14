import asyncio
import logging
from dataclasses import dataclass, field

from pydantic_ai import Agent, RunContext

from second_brain.db import Storage
from second_brain.tools import dream_tools

logger = logging.getLogger(__name__)


@dataclass
class DedupDeps:
    storage: Storage
    cancel: asyncio.Event
    touched_ids: list[str] = field(default_factory=list)


def create_dedup_agent() -> Agent[DedupDeps, str]:
    agent = Agent(
        deps_type=DedupDeps,
        output_type=str,
        system_prompt=(
            "You are a knowledge graph deduplication agent. You do two things:\n"
            "1. Merge duplicate entity nodes\n"
            "2. Merge redundant edges between the same entity pair\n\n"
            "Both are equally important. Do both on every run.\n\n"
            "## Step 1: Node dedup\n\n"
            "For EVERY entity in the batch:\n"
            "1. Call find_similar to get candidate matches from the full table.\n"
            "2. Read the candidates \u2014 names, types, descriptions.\n"
            "3. For promising candidates, use explore to see what each is connected to.\n"
            "4. If they're the same real-world thing, merge them with merge_nodes.\n\n"
            "**Merge:** same name, name variants ('NYC'/'New York City'), or different "
            "names clearly referring to the same thing ('Chief Designer' connected to "
            "Soviet space program = 'Sergei Korolev').\n"
            "**Don't merge:** different aspects ('Brunelleschi' vs 'Brunelleschi`s dome'), "
            "different instances ('Apollo 1' vs 'Apollo 11').\n\n"
            "## Step 2: Edge dedup\n\n"
            "For each entity you processed in step 1, use explore (depth 1) and look at "
            "the edges. When two or more edges connect the SAME pair of nodes, read the "
            "labels and decide:\n\n"
            "**Merge (synonyms or specializations):** 'launched' and 'used_launch_vehicle' "
            "between the same pair \u2014 keep the more specific one. 'crew_included' and "
            "'commanded_by' \u2014 keep 'commanded_by' (it says more). 'authored' and "
            "'authored_by' \u2014 same thing, merge. Use merge_edges with the more specific "
            "edge ID FIRST (it becomes the survivor).\n\n"
            "**Don't merge (genuinely different):** 'arrived_in' and 'died_in' for the "
            "same person and city \u2014 these are different events.\n\n"
            "## Bias\n\n"
            "Lean toward merging. Unmerged duplicates fragment knowledge and degrade "
            "every future query.\n\n"
            "Return a summary of what you merged (nodes and edges)."
        ),
    )

    @agent.tool
    async def find_similar(
        ctx: RunContext[DedupDeps], record_id: str, k: int = 10
    ) -> list[dict]:
        """Find candidate duplicate nodes by name and embedding. Searches the ENTIRE
        table — duplicates from any ingest will appear. Returns node content (name,
        type, description). Read the results and use your judgment.
        record_id: fully-qualified SurrealDB record ID, e.g. 'entity:abc123'."""
        logger.info("dedup: find_similar id=%s k=%d", record_id, k)
        try:
            if record_id not in ctx.deps.touched_ids:
                ctx.deps.touched_ids.append(record_id)
            return await dream_tools.find_similar(ctx.deps.storage, record_id, k)
        except Exception as e:
            logger.error("dedup: find_similar failed: %s", e)
            return [{"error": str(e)}]

    @agent.tool
    async def explore(
        ctx: RunContext[DedupDeps],
        record_id: str,
        direction: str = "both",
        depth: int = 1,
    ) -> dict:
        """See what a node is connected to. Use this to compare two candidate
        duplicates — if they're connected to the same people/places/events,
        they're almost certainly the same entity.
        direction: 'out', 'in', or 'both'. depth: 1-2 hops."""
        logger.info("dedup: explore id=%s dir=%s depth=%d", record_id, direction, depth)
        if ":" not in record_id:
            return {
                "error": f"Invalid record_id '{record_id}': must be 'table:id' format"
            }
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        return await dream_tools.explore(
            ctx.deps.storage, record_id, direction, None, depth
        )

    @agent.tool
    async def merge_nodes(
        ctx: RunContext[DedupDeps], ids: list[str], new_fields: dict
    ) -> dict:
        """Merge multiple nodes into one. First ID becomes the survivor.
        new_fields: the fused content — e.g. {"name": "...", "description": "..."} for
        entities, {"content": "...", "summary": "..."} for notes.
        Edges are automatically re-pointed and deduped."""
        logger.info("dedup: merge_nodes ids=%s", ids)
        try:
            result = await dream_tools.merge_nodes(
                ctx.deps.storage, ids, new_fields, cancel=ctx.deps.cancel
            )
            ctx.deps.touched_ids.extend(result.get("touched_ids", []))
            return result
        except Exception as e:
            logger.error("dedup: merge_nodes failed: %s", e)
            return {"error": str(e)}

    @agent.tool
    async def merge_edges(
        ctx: RunContext[DedupDeps], ids: list[str], new_context: str | None = None
    ) -> dict:
        """Merge multiple edges between the same node pair into one. The first
        edge ID becomes the survivor (its table/label is kept), the rest are deleted.
        Put the edge with the MOST SPECIFIC label first.
        You can get edge IDs from explore results (the edge_id field in each path step)."""
        logger.info("dedup: merge_edges ids=%s", ids)
        try:
            result = await dream_tools.merge_edges(ctx.deps.storage, ids, new_context)
            ctx.deps.touched_ids.extend(result.get("deleted_ids", []))
            if result.get("survivor"):
                sid = str(result["survivor"].get("id", ""))
                if sid and sid not in ctx.deps.touched_ids:
                    ctx.deps.touched_ids.append(sid)
            return result
        except Exception as e:
            logger.error("dedup: merge_edges failed: %s", e)
            return {"error": str(e)}

    @agent.tool
    async def get_node(ctx: RunContext[DedupDeps], record_id: str) -> dict:
        """Get a single node by ID for closer inspection.
        record_id: fully-qualified SurrealDB record ID, e.g. 'entity:abc123'."""
        logger.info("dedup: get_node id=%s", record_id)
        if ":" not in record_id:
            return {
                "error": f"Invalid record_id '{record_id}': must be 'table:id' format"
            }
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        node = await ctx.deps.storage.get_node(record_id)
        if not node:
            return {"error": f"Node {record_id} not found"}
        return node

    return agent
