from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from surrealdb import AsyncSurreal

from second_brain.agents.converse import ConverseDeps, create_converse_agent
from second_brain.agents.ingest import IngestDeps, create_ingest_agent
from second_brain.agents.recall import RecallDeps, create_recall_agent
from second_brain.config import settings
from second_brain.db import init_schema, init_vector_indexes
from second_brain.models import Context, make_serializable
from second_brain.tools.recall_tools import get_connections, get_node

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_db: Any = None
_model: Any = None
_embed: Any = None
_ingest_agent = create_ingest_agent()
_recall_agent = create_recall_agent()
_converse_agent = create_converse_agent()


def _dummy_embed(dimensions: int):
    """Return an async embed function that produces zero vectors."""

    async def _embed_fn(text: str) -> list[float]:
        return [0.0] * dimensions

    return _embed_fn


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db, _model, _embed
    if settings.test_mode:
        from pydantic_ai.models.test import TestModel

        logger.info("Starting in TEST mode (in-memory DB, TestModel)")
        _db = AsyncSurreal("mem://")
        _model = TestModel()
        _embed = _dummy_embed(settings.embedding_dimensions)
    else:
        from second_brain.providers import create_embed_fn, create_model

        logger.info(
            "Starting with model=%s, embedding=%s",
            settings.reasoning_model,
            settings.embedding_model,
        )
        _db = AsyncSurreal(f"surrealkv://{settings.db_path}")
        _model = create_model(
            settings.reasoning_model,
            settings.reasoning_foundry_url,
            settings.reasoning_auth,
            settings.reasoning_key,
        )
        _embed = create_embed_fn(
            settings.embedding_model,
            settings.embedding_foundry_url,
            settings.embedding_auth,
            settings.embedding_key,
            settings.embedding_dimensions,
        )
    await _db.use("brain", "brain")
    await init_schema(_db)
    await init_vector_indexes(_db)
    logger.info("Database schema initialized")
    yield
    if _db:
        await _db.close()
        _db = None


app = FastAPI(title="Second Brain", lifespan=lifespan)


class IngestRequest(BaseModel):
    text: str
    hints: list[str] = []


class IngestResponse(BaseModel):
    summary: str


class RecallRequest(BaseModel):
    question: str
    hints: list[str] = []


class RecallResponse(BaseModel):
    answer: str
    context: Context | None = None


class ConnectionItem(BaseModel):
    edge: dict
    node: dict


class GraphResponse(BaseModel):
    node: dict
    connections: list[ConnectionItem] = []


class AssistantMessage(BaseModel):
    response: str
    context: Context | None = None


class HistoryTurn(BaseModel):
    user: str
    assistant: AssistantMessage


class ConverseRequest(BaseModel):
    message: str
    history: list[HistoryTurn] = []


class ConverseResponse(BaseModel):
    response: str
    context: Context | None = None


async def run_ingest_agent(text: str, hints: list[str] | None = None) -> str:
    prompt = text
    if hints:
        hint_str = ", ".join(hints)
        prompt = f"Possibly related nodes: {hint_str}\n\n{text}"
    logger.info("Ingest agent starting (text length=%d)", len(text))
    result = await _ingest_agent.run(
        prompt,
        deps=IngestDeps(db=_db, embed_fn=_embed),
        model=_model,
    )
    logger.info("Ingest agent completed")
    return result.output


async def run_recall_agent(
    question: str, hints: list[str] | None = None
) -> RecallResponse:
    prompt = question
    if hints:
        hint_str = ", ".join(hints)
        prompt = f"Possibly related nodes: {hint_str}\n\n{question}"

    logger.info("Recall agent starting (question length=%d)", len(question))
    result = await _recall_agent.run(
        prompt,
        deps=RecallDeps(db=_db, embed_fn=_embed),
        model=_model,
    )
    output = result.output  # RecallOutput
    logger.info(
        "Recall agent completed (cited %d nodes, %d edges)",
        len(output.cited_node_ids),
        len(output.cited_edge_ids),
    )

    # Fetch actual records for cited IDs
    from second_brain.tools.recall_tools import fetch_records_by_ids

    nodes = await fetch_records_by_ids(_db, output.cited_node_ids)
    edges = await fetch_records_by_ids(_db, output.cited_edge_ids)

    ctx = None
    if nodes or edges:
        ctx = Context(
            nodes=[make_serializable(n) for n in nodes],
            edges=[make_serializable(e) for e in edges],
        )

    return RecallResponse(answer=output.answer, context=ctx)


async def run_converse_agent(
    message: str, history: list[HistoryTurn]
) -> ConverseResponse:
    deps = ConverseDeps(
        db=_db,
        embed_fn=_embed,
        model_setting=_model,
    )

    # Build PydanticAI message history
    pydantic_history = []
    for turn in history:
        pydantic_history.append(ModelRequest(parts=[UserPromptPart(content=turn.user)]))
        pydantic_history.append(
            ModelResponse(parts=[TextPart(content=turn.assistant.response)])
        )

    logger.info(
        "Converse agent starting (message length=%d, history turns=%d)",
        len(message),
        len(history),
    )
    result = await _converse_agent.run(
        message,
        deps=deps,
        model=_model,
        message_history=pydantic_history,
    )
    logger.info("Converse agent completed")

    ctx = deps.context if (deps.context.nodes or deps.context.edges) else None
    return ConverseResponse(response=result.output, context=ctx)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest):
    logger.info("POST /ingest")
    summary = await run_ingest_agent(req.text, req.hints if req.hints else None)
    return IngestResponse(summary=summary)


@app.post("/recall", response_model=RecallResponse)
async def recall(req: RecallRequest):
    logger.info("POST /recall")
    return await run_recall_agent(req.question, req.hints if req.hints else None)


@app.post("/converse", response_model=ConverseResponse)
async def converse(req: ConverseRequest):
    logger.info("POST /converse")
    return await run_converse_agent(req.message, req.history)


@app.post("/converse/stream")
async def converse_stream(req: ConverseRequest):
    logger.info("POST /converse/stream")
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    deps = ConverseDeps(
        db=_db,
        embed_fn=_embed,
        model_setting=_model,
        progress_queue=queue,
    )

    # Build PydanticAI message history
    pydantic_history: list = []
    for turn in req.history:
        pydantic_history.append(ModelRequest(parts=[UserPromptPart(content=turn.user)]))
        pydantic_history.append(
            ModelResponse(parts=[TextPart(content=turn.assistant.response)])
        )

    async def _run_agent() -> None:
        try:
            result = await _converse_agent.run(
                req.message,
                deps=deps,
                model=_model,
                message_history=pydantic_history,
            )
            ctx = deps.context if (deps.context.nodes or deps.context.edges) else None
            resp = ConverseResponse(response=result.output, context=ctx)
            await queue.put(
                {"type": "done", "data": json.loads(resp.model_dump_json())}
            )
        except Exception as exc:
            logger.exception("Converse stream agent error")
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put(None)  # sentinel

    async def _event_generator() -> AsyncGenerator[str]:
        task = asyncio.create_task(_run_agent())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                event_type = event.get("type", "status")
                if event_type == "done":
                    yield f"event: done\ndata: {json.dumps(event['data'])}\n\n"
                elif event_type == "error":
                    yield f"event: error\ndata: {json.dumps({'message': event['message']})}\n\n"
                else:
                    yield f"event: status\ndata: {json.dumps({'message': event['message']})}\n\n"
        except asyncio.CancelledError:
            task.cancel()
            raise
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/graph/{record_id:path}", response_model=GraphResponse)
async def get_graph(record_id: str):
    node = await get_node(_db, record_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node {record_id} not found")

    raw_edges = await get_connections(_db, record_id)
    connections = []
    for edge in raw_edges:
        edge_s = make_serializable(edge)
        # Determine "other" node: if out matches record_id, other is in; else out
        other_id = (
            str(edge_s.get("in"))
            if str(edge_s.get("out")) == record_id
            else str(edge_s.get("out"))
        )
        if other_id:
            other_node = await get_node(_db, str(other_id))
            if other_node:
                connections.append(
                    ConnectionItem(
                        edge=edge_s,
                        node=make_serializable(other_node),
                    )
                )
    return GraphResponse(node=make_serializable(node), connections=connections)
