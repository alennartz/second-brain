import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal

from second_brain.models import make_serializable
from second_brain.tools import recall_tools

logger = logging.getLogger(__name__)


class RecallOutput(BaseModel):
    answer: str
    cited_node_ids: list[str] = []
    cited_edge_ids: list[str] = []


@dataclass
class RecallDeps:
    db: AsyncSurreal  # pyright: ignore[reportGeneralTypeIssues] - SDK types AsyncSurreal as function
    embed_fn: Callable[[str], Awaitable[list[float]]]


def create_recall_agent() -> Agent[RecallDeps, RecallOutput]:
    """Create a recall agent with search and graph exploration tools.

    The agent is created without a default model so it can be used in tests
    with TestModel(). In production, pass ``settings.reasoning_model`` to
    ``agent.run(..., model=...)``, or override using
    ``PYDANTIC_AI_MODEL`` env var.
    """
    agent = Agent(
        deps_type=RecallDeps,
        output_type=RecallOutput,
        system_prompt=(
            "You are a personal knowledge recall agent. The user asks questions and you "
            "explore their knowledge base using the tools available to you. "
            "Use search_knowledge to search notes and entities by keyword and meaning. "
            "Each result includes its connections — edges with labels, directions, and "
            "adjacent node IDs. Use get_node to follow interesting connections and explore "
            "the graph selectively. "
            "Keep exploring until you have enough context to give a thorough answer. "
            "If you find nothing relevant, say so honestly.\n\n"
            "IMPORTANT: In your response, include the IDs of all nodes and edges you "
            "referenced in your answer in the cited_node_ids and cited_edge_ids fields."
        ),
    )

    @agent.tool
    async def search_knowledge(
        ctx: RunContext[RecallDeps], tables: list[str], query: str, k: int = 5
    ) -> list[dict]:
        """Search the knowledge base using hybrid keyword + semantic search.
        tables: list containing 'note', 'entity', or both.
        Results include a 'connections' list showing edges with labels and adjacent node IDs."""
        logger.info(
            "recall: search_knowledge tables=%s query='%.80s' k=%d", tables, query, k
        )
        try:
            query_embedding = await ctx.deps.embed_fn(query)
            all_results: list[dict] = []
            for table in tables:
                results = await recall_tools.hybrid_search(
                    ctx.deps.db, table, query, query_embedding, k
                )
                all_results.extend(results)
            enriched = []
            for r in all_results:
                e = await recall_tools.enrich_with_connections(ctx.deps.db, r)
                enriched.append(make_serializable(e))
            logger.info("recall: search_knowledge → %d results", len(enriched))
            return enriched
        except Exception as e:
            logger.error("recall: search_knowledge failed: %s", e)
            return [{"error": str(e)}]

    @agent.tool
    async def get_node(ctx: RunContext[RecallDeps], record_id: str) -> dict:
        """Get a single node by ID, e.g. 'note:abc123' or 'entity:sr'.
        Result includes a 'connections' list showing edges with labels and adjacent node IDs."""
        logger.info("recall: get_node id=%s", record_id)
        try:
            node = await recall_tools.get_node(ctx.deps.db, record_id)
            if not node:
                return {"error": f"Node {record_id} not found"}
            enriched = await recall_tools.enrich_with_connections(ctx.deps.db, node)
            return make_serializable(enriched)
        except Exception as e:
            logger.error("recall: get_node failed: %s", e)
            return {"error": str(e)}

    return agent
