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

from second_brain.agents.ingestion_pipeline import IngestionPipeline
from second_brain.agents.recall import (
    RecallDeps,
    RecallOutput,
    create_recall_agent,
    fetch_cited_context,
)
from second_brain.db import Storage
from second_brain.models import Context, EnqueueResult, IntakeRequest

logger = logging.getLogger(__name__)

# Status messages for recall sub-agent tool calls
_RECALL_STATUS: dict[str, str] = {
    "search_knowledge": "Running hybrid search...",
    "get_node": "Fetching node...",
    "get_connections": "Following connections...",
    "graph_traverse": "Traversing graph...",
}


@dataclass
class ConverseDeps:
    storage: Storage
    model_setting: Model | str  # model string or TestModel for sub-agent calls
    context: Context = field(default_factory=Context)  # mutable accumulator
    progress_queue: asyncio.Queue[dict | None] | None = None
    ingestion_pipeline: IngestionPipeline | None = None


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


async def stage_converse_ingest(deps: ConverseDeps, text: str) -> str:
    """Stage a conversational intake through the shared pipeline."""
    pipeline = deps.ingestion_pipeline
    if pipeline is None:
        return "Intake staging is unavailable."

    await _push(deps.progress_queue, "Staging intake...")
    result: EnqueueResult = await pipeline.enqueue(
        IntakeRequest(text=text, source="converse")
    )
    await _push(
        deps.progress_queue,
        f"Queued {result.chunks_stored} chunks as unprocessed intake",
    )
    return (
        f"Queued {result.chunks_stored} chunks for background processing. "
        "They are searchable now as unprocessed evidence."
    )


def create_converse_agent() -> Agent[ConverseDeps, str]:
    """Create a conversation agent that wraps recall and ingest as tools."""
    agent = Agent(
        deps_type=ConverseDeps,
        output_type=str,
        system_prompt=(
            "You are a conversational router for a personal knowledge base. Your only job "
            "is to decide whether each user message requires recall (answering a question), "
            "ingest (storing new knowledge), or both — then delegate.\n\n"
            "Recall searches, follows graph connections, and synthesizes answers. "
            "Ingest stages the user's raw text for immediate search; a background worker "
            "later extracts entities, notes, and relationships. Do not rewrite, summarize, "
            "or rephrase "
            "what the user said. Pass the user's message (or the relevant part of it) "
            "directly to the appropriate tool with minimal modification.\n\n"
            "After receiving a tool's response, relay it back to the user. You may lightly "
            "frame it conversationally (e.g. acknowledging a follow-up) but do not "
            "resynthesize or rewrite the answer. The sub-agents have already done the work."
        ),
    )

    _recall_agent = create_recall_agent()

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

        # Fetch actual records and accumulate onto deps.context (deduplicated).
        # Malformed cited IDs and deleted intake chunks are skipped; agent output
        # is not trusted.
        fetched = await fetch_cited_context(ctx.deps.storage, output)
        existing_node_ids = {str(node["id"]) for node in ctx.deps.context.nodes}
        existing_edge_ids = {str(edge["id"]) for edge in ctx.deps.context.edges}
        existing_unprocessed_ids = {
            str(chunk["id"]) for chunk in ctx.deps.context.unprocessed
        }
        ctx.deps.context.nodes.extend(
            node
            for node in fetched.nodes
            if str(node.get("id")) not in existing_node_ids
        )
        ctx.deps.context.edges.extend(
            edge
            for edge in fetched.edges
            if str(edge.get("id")) not in existing_edge_ids
        )
        ctx.deps.context.unprocessed.extend(
            chunk
            for chunk in fetched.unprocessed
            if str(chunk.get("id")) not in existing_unprocessed_ids
        )

        return output.answer

    @agent.tool
    async def ingest(ctx: RunContext[ConverseDeps], text: str) -> str:
        """Stage raw knowledge for immediate search and background organization.

        Pass the user's input as-is. Staging preserves the source text and makes
        it searchable before the ingest agent organizes it.
        """
        return await stage_converse_ingest(ctx.deps, text)

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
