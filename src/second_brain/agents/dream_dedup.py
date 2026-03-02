import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal

from second_brain.models import make_serializable, strip_embeddings
from second_brain.tools import dream_tools, recall_tools

logger = logging.getLogger(__name__)


@dataclass
class DedupDeps:
    db: AsyncSurreal  # pyright: ignore[reportGeneralTypeIssues]
    embed_fn: Callable[[str], Awaitable[list[float]]]
    cancel: asyncio.Event
    touched_ids: list[str] = field(default_factory=list)


def create_dedup_agent() -> Agent[DedupDeps, str]:
    agent = Agent(
        deps_type=DedupDeps,
        output_type=str,
        system_prompt=(
            "You are a knowledge graph deduplication agent. You process a batch of nodes "
            "and find duplicates that should be merged.\n\n"
            "For each node in the batch:\n"
            "1. Use find_similar to find semantically similar nodes.\n"
            "2. Examine the results — look at names, descriptions, content, and similarity scores.\n"
            "3. If you find true duplicates (same concept, different wording), merge them using "
            "merge_nodes. Provide a fused name/description/content that combines the best of both.\n"
            "4. If edges between the same pair of nodes have different labels that mean the same thing, "
            "use merge_edges to combine them.\n\n"
            "Be conservative: only merge when you are confident the nodes represent the same concept. "
            "Different versions or aspects of a concept are NOT duplicates.\n\n"
            "Return a summary of what you merged and what you left alone."
        ),
    )

    @agent.tool
    async def find_similar(
        ctx: RunContext[DedupDeps], record_id: str, k: int = 5
    ) -> list[dict]:
        """Find the k most similar nodes to the given node (same table). Returns content + similarity score."""
        logger.info("dedup: find_similar id=%s k=%d", record_id, k)
        try:
            if record_id not in ctx.deps.touched_ids:
                ctx.deps.touched_ids.append(record_id)
            results = await dream_tools.find_similar(ctx.deps.db, record_id, k)
            return results
        except Exception as e:
            logger.error("dedup: find_similar failed: %s", e)
            return [{"error": str(e)}]

    @agent.tool
    async def merge_nodes(
        ctx: RunContext[DedupDeps], ids: list[str], new_fields: dict
    ) -> dict:
        """Merge multiple nodes into one. First ID becomes the survivor.
        new_fields: the fused content — e.g. {"name": "...", "description": "..."} for entities,
        {"content": "...", "summary": "..."} for notes. Edges are automatically re-pointed and deduped."""
        logger.info("dedup: merge_nodes ids=%s", ids)
        try:
            result = await dream_tools.merge_nodes(
                ctx.deps.db, ids, new_fields, ctx.deps.embed_fn
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
        """Merge multiple edges between the same node pair into one.
        First ID becomes the survivor. Provide new_context if the label should be updated."""
        logger.info("dedup: merge_edges ids=%s", ids)
        try:
            result = await dream_tools.merge_edges(ctx.deps.db, ids, new_context)
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
        """Get a single node by ID for closer inspection."""
        logger.info("dedup: get_node id=%s", record_id)
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        node = await recall_tools.get_node(ctx.deps.db, record_id)
        if not node:
            return {"error": f"Node {record_id} not found"}
        return strip_embeddings(make_serializable(node))

    return agent
