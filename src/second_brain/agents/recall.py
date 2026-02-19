from dataclasses import dataclass

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal

from second_brain.tools import recall_tools


class RecallOutput(BaseModel):
    answer: str
    cited_node_ids: list[str] = []
    cited_edge_ids: list[str] = []


@dataclass
class RecallDeps:
    db: AsyncSurreal  # pyright: ignore[reportGeneralTypeIssues] - SDK types AsyncSurreal as function


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
            "Use search tools to find relevant notes and entities, follow graph connections "
            "to discover related knowledge, and refine your search based on what you find. "
            "Keep exploring until you have enough context to give a thorough answer. "
            "If you find nothing relevant, say so honestly.\n\n"
            "IMPORTANT: In your response, include the IDs of all nodes and edges you "
            "referenced in your answer in the cited_node_ids and cited_edge_ids fields."
        ),
    )

    @agent.tool
    async def full_text_search(
        ctx: RunContext[RecallDeps], table: str, query: str
    ) -> list[dict]:
        """Search notes or entities by keyword. Table must be 'note' or 'entity'."""
        return await recall_tools.full_text_search(ctx.deps.db, table, query)

    @agent.tool
    async def vector_search(
        ctx: RunContext[RecallDeps],
        table: str,
        query_embedding: list[float],
        k: int = 5,
    ) -> list[dict]:
        """Find the k nearest notes/entities by semantic similarity."""
        return await recall_tools.vector_search(ctx.deps.db, table, query_embedding, k)

    @agent.tool
    async def get_node(ctx: RunContext[RecallDeps], record_id: str) -> dict:
        """Get a single node by ID, e.g. 'note:abc123' or 'entity:sr'."""
        return await recall_tools.get_node(ctx.deps.db, record_id)

    @agent.tool
    async def get_connections(
        ctx: RunContext[RecallDeps], record_id: str
    ) -> list[dict]:
        """Get all relationships connected to a node."""
        return await recall_tools.get_connections(ctx.deps.db, record_id)

    @agent.tool
    async def graph_traverse(
        ctx: RunContext[RecallDeps], record_id: str, depth: int = 2
    ) -> list[dict]:
        """Traverse the knowledge graph from a node up to N hops deep."""
        return await recall_tools.graph_traverse(ctx.deps.db, record_id, depth)

    return agent
