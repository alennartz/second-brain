from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model
from surrealdb import AsyncSurreal  # pyright: ignore[reportGeneralTypeIssues]

from second_brain.agents.ingest import IngestDeps, create_ingest_agent
from second_brain.agents.recall import RecallDeps, RecallOutput, create_recall_agent
from second_brain.models import Context, make_serializable
from second_brain.tools.recall_tools import fetch_records_by_ids


@dataclass
class ConverseDeps:
    db: AsyncSurreal  # pyright: ignore[reportGeneralTypeIssues]
    embed_fn: Callable[[str], Awaitable[list[float]]]
    model_setting: Model | str  # model string or TestModel for sub-agent calls
    context: Context = field(default_factory=Context)  # mutable accumulator


def create_converse_agent() -> Agent[ConverseDeps, str]:
    """Create a conversation agent that wraps recall and ingest as tools."""
    agent = Agent(
        deps_type=ConverseDeps,
        output_type=str,
        system_prompt=(
            "You are a conversational router for a personal knowledge base. Your only job "
            "is to decide whether each user message requires recall (answering a question), "
            "ingest (storing new knowledge), or both — then delegate.\n\n"
            "Your tools — recall and ingest — are full AI agent pipelines, not simple "
            "database operations. They handle all searching, reasoning, entity extraction, "
            "and relationship building internally. Do not rewrite, summarize, or rephrase "
            "what the user said. Pass the user's message (or the relevant part of it) "
            "directly to the appropriate tool with minimal modification.\n\n"
            "After receiving a tool's response, relay it back to the user. You may lightly "
            "frame it conversationally (e.g. acknowledging a follow-up) but do not "
            "resynthesize or rewrite the answer. The sub-agents have already done the work."
        ),
    )

    _recall_agent = create_recall_agent()
    _ingest_agent = create_ingest_agent()

    @agent.tool
    async def recall(ctx: RunContext[ConverseDeps], question: str) -> str:
        """Delegate a question to the recall agent, which will search the knowledge
        base, follow graph connections, and synthesize an answer. Pass the user's
        question as-is — the recall agent handles all reasoning internally."""
        result = await _recall_agent.run(
            question,
            deps=RecallDeps(db=ctx.deps.db, embed_fn=ctx.deps.embed_fn),
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
        """Delegate new knowledge to the ingest agent, which will parse it into
        notes and entities, find connections, and store everything. Pass the user's
        input as-is — the ingest agent handles all structuring internally."""
        result = await _ingest_agent.run(
            text,
            deps=IngestDeps(db=ctx.deps.db, embed_fn=ctx.deps.embed_fn),
            model=ctx.deps.model_setting,
        )
        return result.output

    return agent
