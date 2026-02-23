import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal

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
    """Create a recall agent with search and graph traversal tools.

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
            "Use search_knowledge to search notes and entities by keyword and meaning, "
            "follow graph connections to discover related knowledge, and refine your search "
            "based on what you find. "
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
        tables: list containing 'note', 'entity', or both."""
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
            logger.info("recall: search_knowledge → %d results", len(all_results))
            return all_results
        except Exception as e:
            logger.error("recall: search_knowledge failed: %s", e)
            return [{"error": str(e)}]

    @agent.tool
    async def get_node(ctx: RunContext[RecallDeps], record_id: str) -> dict:
        """Get a single node by ID, e.g. 'note:abc123' or 'entity:sr'."""
        logger.info("recall: get_node id=%s", record_id)
        return await recall_tools.get_node(ctx.deps.db, record_id)

    @agent.tool
    async def get_connections(
        ctx: RunContext[RecallDeps], record_id: str
    ) -> list[dict]:
        """Get all relationships connected to a node."""
        logger.info("recall: get_connections id=%s", record_id)
        return await recall_tools.get_connections(ctx.deps.db, record_id)

    @agent.tool
    async def graph_traverse(
        ctx: RunContext[RecallDeps], record_id: str, depth: int = 2
    ) -> list[dict]:
        """Traverse the knowledge graph from a node up to N hops deep."""
        logger.info("recall: graph_traverse id=%s depth=%d", record_id, depth)
        return await recall_tools.graph_traverse(ctx.deps.db, record_id, depth)

    return agent
