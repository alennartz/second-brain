import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal

from second_brain.models import make_serializable
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
            "For EVERY node in the batch:\n"
            "1. Call find_similar with k=10 to find candidates. This searches the ENTIRE "
            "table, not just the batch — duplicates from any ingest will appear.\n"
            "2. Scan the results for NAME MATCHES first, then consider similarity scores.\n"
            "3. If you find duplicates, merge them IMMEDIATELY using merge_nodes.\n\n"
            "Do NOT skip any batch member. Process every single one.\n\n"
            "CRITICAL — name matching rules:\n"
            "- **Identical names** (case-insensitive): ALWAYS merge. Two entities both named "
            "'Venice' or 'Sergei Korolev' are duplicates. Do not look at the similarity "
            "score — it reflects description/embedding differences, NOT name matching. "
            "Identical names = same entity, period.\n"
            "- **Name variants** (e.g., 'JS' vs 'JavaScript', 'NYC' vs 'New York City', "
            "'Dr. Smith' vs 'John Smith', 'Sergei Korolev' vs 'S.P. Korolev'): merge "
            "when clearly the same real-world entity.\n"
            "- **Overlapping names for same concept** (e.g., 'Florence Cathedral' and "
            "'Cathedral of Santa Maria del Fiore'): merge — these are the same place.\n"
            "- **Different aspects of a concept** (e.g., 'Python language' vs 'Python "
            "ecosystem', 'Brunelleschi' vs 'Brunelleschi`s dome'): do NOT merge.\n\n"
            "When merging, provide new_fields that combine the best information from "
            "all merged nodes — keep the richest description, the most complete name.\n\n"
            "After merging nodes, check the survivor's edges: if multiple edges connect "
            "the same pair of nodes with synonymous labels (e.g., 'developed' and "
            "'led_development_of'), use merge_edges to combine them.\n\n"
            "Bias toward merging. The cost of leaving duplicates is fragmented knowledge "
            "that degrades recall quality. An occasional over-merge can be corrected; "
            "unmerged duplicates accumulate silently and degrade every query.\n\n"
            "Return a summary of what you merged and what you left alone."
        ),
    )

    @agent.tool
    async def find_similar(
        ctx: RunContext[DedupDeps], record_id: str, k: int = 10
    ) -> list[dict]:
        """Find the k most similar nodes to the given node (same table). Returns content + similarity score.
        Searches the ENTIRE table — duplicates from any ingest will appear.
        record_id: MUST be a fully-qualified SurrealDB record ID in 'table:id' format, e.g. 'entity:abc123'."""
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
        """Get a single node by ID for closer inspection.
        record_id: MUST be a fully-qualified SurrealDB record ID in 'table:id' format, e.g. 'entity:abc123'."""
        logger.info("dedup: get_node id=%s", record_id)
        if ":" not in record_id:
            return {
                "error": f"Invalid record_id '{record_id}': must be 'table:id' format (e.g. 'entity:abc123')"
            }
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        node = await recall_tools.get_node(ctx.deps.db, record_id)
        if not node:
            return {"error": f"Node {record_id} not found"}
        return make_serializable(node)

    return agent
