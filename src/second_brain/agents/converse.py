from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    ModelRequest,
    ModelResponse,
)
from pydantic_ai.models import Model

from second_brain.agents.ingest import IngestDeps, create_ingest_agent
from second_brain.agents.recall import RecallDeps, RecallOutput, create_recall_agent
from second_brain.db import Storage
from second_brain.models import (
    Context,
    normalize_edge,
    normalize_node,
)

logger = logging.getLogger(__name__)

# Status messages for recall sub-agent tool calls
_RECALL_STATUS: dict[str, str] = {
    "search_knowledge": "Running hybrid search...",
    "get_node": "Fetching node...",
    "get_connections": "Following connections...",
    "graph_traverse": "Traversing graph...",
}

# Status messages for ingest sub-agent tool calls
_INGEST_STATUS: dict[str, str] = {
    "create_note": "Creating note...",
    "create_entity": "Extracting entity...",
    "create_edge": "Linking knowledge...",
    "update_node": "Updating node...",
    "search_knowledge": "Checking existing knowledge...",
}


@dataclass
class ConverseDeps:
    storage: Storage
    model_setting: Model | str  # model string or TestModel for sub-agent calls
    context: Context = field(default_factory=Context)  # mutable accumulator
    progress_queue: asyncio.Queue[dict | None] | None = None


async def _push(queue: asyncio.Queue[dict | None] | None, msg: str) -> None:
    """Push a status event to the queue if it exists."""
    if queue is not None:
        await queue.put({"type": "status", "message": msg})


def _make_stream_handler(
    queue: asyncio.Queue[dict | None],
    status_map: dict[str, str],
):  # type: ignore[type-arg]
    """Create an event_stream_handler that forwards tool call events to the queue."""

    async def handler(ctx: object, events):  # type: ignore[type-arg]
        async for event in events:
            if isinstance(event, FunctionToolCallEvent):
                msg = status_map.get(event.part.tool_name, event.part.tool_name)
                await queue.put({"type": "status", "message": msg})

    return handler


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
        queue = ctx.deps.progress_queue
        logger.info("Converse → recall sub-agent starting")
        await _push(queue, "Searching knowledge base...")

        kwargs: dict = dict(
            deps=RecallDeps(storage=ctx.deps.storage),
            model=ctx.deps.model_setting,
        )
        if queue is not None:
            kwargs["event_stream_handler"] = _make_stream_handler(queue, _RECALL_STATUS)

        result = await _recall_agent.run(question, **kwargs)
        output: RecallOutput = result.output
        logger.info("Converse → recall sub-agent completed")
        await _push(queue, "Search complete")

        # Fetch actual records and accumulate onto deps.context (deduplicated)
        nodes = await ctx.deps.storage.get_nodes(output.cited_node_ids)
        edges = [
            e
            for eid in output.cited_edge_ids
            if (e := await ctx.deps.storage.get_edge(eid))
        ]
        existing_node_ids = {str(n["id"]) for n in ctx.deps.context.nodes}
        existing_edge_ids = {str(e["id"]) for e in ctx.deps.context.edges}
        ctx.deps.context.nodes.extend(
            normalize_node(n)
            for n in nodes
            if str(n.get("id")) not in existing_node_ids
        )
        ctx.deps.context.edges.extend(
            normalize_edge(e)
            for e in edges
            if str(e.get("id")) not in existing_edge_ids
        )

        return output.answer

    @agent.tool
    async def ingest(ctx: RunContext[ConverseDeps], text: str) -> str:
        """Delegate new knowledge to the ingest agent, which will parse it into
        notes and entities, find connections, and store everything. Pass the user's
        input as-is — the ingest agent handles all structuring internally."""
        queue = ctx.deps.progress_queue
        logger.info("Converse → ingest sub-agent starting")
        await _push(queue, "Storing new knowledge...")

        kwargs: dict = dict(
            deps=IngestDeps(storage=ctx.deps.storage),
            model=ctx.deps.model_setting,
        )
        if queue is not None:
            kwargs["event_stream_handler"] = _make_stream_handler(queue, _INGEST_STATUS)

        result = await _ingest_agent.run(text, **kwargs)
        logger.info("Converse → ingest sub-agent completed")
        await _push(queue, "Knowledge stored")
        return result.output

    return agent


async def run_converse_turn(
    message: str,
    message_history: list[ModelRequest | ModelResponse],
    *,
    deps: ConverseDeps,
    model: Model | str,
    routing_model: Model | str | None = None,
) -> str:
    """Single entry point for one conversational turn.

    routing_model is not None -> try the fast path first:
        Route.RECALL  -> run the recall pipeline directly (today's recall tool body)
        Route.INGEST  -> run the ingest pipeline directly (today's ingest tool body)
        None/CONVERSE -> run the converse agent exactly as today
    routing_model is None -> always the converse agent.

    Side effects identical on every path: status events on deps.progress_queue,
    cited nodes/edges accumulated (deduplicated) onto deps.context.
    """
    raise NotImplementedError("not implemented")
