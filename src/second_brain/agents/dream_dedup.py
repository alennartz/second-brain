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
            "You are a knowledge graph deduplication agent. You process a batch of "
            "entity nodes and decide which ones are duplicates that should be merged.\n\n"
            "## Workflow\n\n"
            "For EVERY entity in the batch:\n"
            "1. Call find_similar to get candidate matches from the full table.\n"
            "2. **Read the candidates.** Look at their names, types, and descriptions.\n"
            "3. For any candidate that looks like it might be the same entity, use "
            "explore to see what each one is connected to. Two nodes with the same "
            "name connected to related things (same people, same places, same events) "
            "are almost certainly duplicates.\n"
            "4. If you're confident they're the same thing, merge them.\n\n"
            "Do NOT skip any batch member. Process every single one.\n\n"
            "## How to judge duplicates\n\n"
            "Use your own judgment. Read the names and descriptions like a human would.\n\n"
            "**Obvious duplicates — merge immediately:**\n"
            "- Same name, same type (two entities both called 'Venice' of type 'place')\n"
            "- Name variants for the same thing ('Sergei Korolev' vs 'S.P. Korolev', "
            "'NYC' vs 'New York City', 'Florence Cathedral' vs "
            "'Cattedrale di Santa Maria del Fiore')\n\n"
            "**Check connections to decide:**\n"
            "- Similar names but you're not sure? Use explore on both. If they share "
            "connections to the same people, places, or events, they're the same.\n"
            "- Different names but descriptions overlap heavily? Check connections. "
            "A 'Chief Designer' entity connected to Soviet space program entities is "
            "the same person as 'Sergei Korolev'.\n\n"
            "**Do NOT merge:**\n"
            "- Different aspects of related things ('Brunelleschi' the person vs "
            "'Brunelleschi`s dome' the building)\n"
            "- Same category but clearly different instances ('Apollo 1' vs 'Apollo 11')\n\n"
            "## Edge dedup\n\n"
            "After processing all entities for node dedup, check for redundant edges. "
            "Use explore (depth 1) on entities you touched. If you see multiple edges "
            "between the same pair of nodes, read the edge labels and decide:\n"
            "- **Synonyms or specializations** ('developed' and 'led_development_of', "
            "or 'launched' and 'used_launch_vehicle', or 'crew_included' and "
            "'commanded_by'): merge with merge_edges. Keep the MORE SPECIFIC label — "
            "'commanded_by' is better than 'crew_included' because it conveys the role, "
            "not just membership. 'led_development_of' is better than 'developed'.\n"
            "- **Genuinely different relationships** ('arrived_in' and 'died_in' for "
            "the same person and city): do NOT merge — these are distinct events.\n\n"
            "This is important even when no nodes were merged — redundant edges "
            "accumulate from separate ingests and clutter the graph.\n\n"
            "## Bias\n\n"
            "Lean toward merging. Unmerged duplicates fragment knowledge and degrade "
            "every future query. An accidental over-merge is fixable; thousands of "
            "unmerged duplicates are not.\n\n"
            "Return a summary of what you merged and what you left alone."
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
            return await dream_tools.find_similar(ctx.deps.db, record_id, k)
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
        return await dream_tools.explore(ctx.deps.db, record_id, direction, None, depth)

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
        """Merge multiple edges between the same node pair into one. The first
        edge ID becomes the survivor (its table/label is kept), the rest are deleted.
        Put the edge with the MOST SPECIFIC label first.
        You can get edge IDs from explore results (the edge_id field in each path step)."""
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
        record_id: fully-qualified SurrealDB record ID, e.g. 'entity:abc123'."""
        logger.info("dedup: get_node id=%s", record_id)
        if ":" not in record_id:
            return {
                "error": f"Invalid record_id '{record_id}': must be 'table:id' format"
            }
        if record_id not in ctx.deps.touched_ids:
            ctx.deps.touched_ids.append(record_id)
        node = await recall_tools.get_node(ctx.deps.db, record_id)
        if not node:
            return {"error": f"Node {record_id} not found"}
        return make_serializable(node)

    return agent
