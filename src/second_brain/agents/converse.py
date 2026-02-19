from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal  # pyright: ignore[reportGeneralTypeIssues]

from second_brain.agents.ingest import IngestDeps, create_ingest_agent
from second_brain.agents.recall import RecallDeps, RecallOutput, create_recall_agent
from second_brain.models import Context, make_serializable
from second_brain.tools.recall_tools import fetch_records_by_ids


@dataclass
class ConverseDeps:
    db: AsyncSurreal  # pyright: ignore[reportGeneralTypeIssues]
    embed_fn: Callable[[str], Awaitable[list[float]]]
    model_setting: str  # model string for sub-agent calls, e.g. "openai:gpt-4o-mini"
    context: Context = field(default_factory=Context)  # mutable accumulator


def create_converse_agent() -> Agent[ConverseDeps, str]:
    """Create a conversation agent that wraps recall and ingest as tools."""
    agent = Agent(
        deps_type=ConverseDeps,
        output_type=str,
        system_prompt=(
            "You are a conversational knowledge assistant. You have access to the user's "
            "personal knowledge base. You can recall information using the recall tool "
            "and store new information using the ingest tool.\n\n"
            "When the user asks a question, use recall to search their knowledge base. "
            "When the user shares new information or ideas, use ingest to store them. "
            "Be conversational and helpful. Synthesize information naturally."
        ),
    )

    _recall_agent = create_recall_agent()
    _ingest_agent = create_ingest_agent()

    @agent.tool
    async def recall(ctx: RunContext[ConverseDeps], question: str) -> str:
        """Search the knowledge base for information relevant to the question."""
        result = await _recall_agent.run(
            question,
            deps=RecallDeps(db=ctx.deps.db),
            model=ctx.deps.model_setting,
        )
        output: RecallOutput = result.output

        # Fetch actual records and accumulate onto deps.context
        nodes = await fetch_records_by_ids(ctx.deps.db, output.cited_node_ids)
        edges = await fetch_records_by_ids(ctx.deps.db, output.cited_edge_ids)
        ctx.deps.context.nodes.extend([make_serializable(n) for n in nodes])
        ctx.deps.context.edges.extend([make_serializable(e) for e in edges])

        return output.answer

    @agent.tool
    async def ingest(ctx: RunContext[ConverseDeps], text: str) -> str:
        """Store new information in the knowledge base."""
        result = await _ingest_agent.run(
            text,
            deps=IngestDeps(db=ctx.deps.db, embed_fn=ctx.deps.embed_fn),
            model=ctx.deps.model_setting,
        )
        return result.output

    return agent
