from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from surrealdb import AsyncSurreal

from second_brain.agents.converse import ConverseDeps, create_converse_agent
from second_brain.agents.ingest import IngestDeps, create_ingest_agent
from second_brain.agents.recall import RecallDeps, create_recall_agent
from second_brain.config import settings
from second_brain.db import init_schema
from second_brain.embedding import embed_text, init_vector_indexes
from second_brain.models import Context, make_serializable
from second_brain.tools.recall_tools import get_connections, get_node

_db: Any = None
_ingest_agent = create_ingest_agent()
_recall_agent = create_recall_agent()
_converse_agent = create_converse_agent()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db
    _db = AsyncSurreal(f"surrealkv://{settings.db_path}")
    await _db.use("brain", "brain")
    await init_schema(_db)
    await init_vector_indexes(_db)
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
    result = await _ingest_agent.run(
        prompt,
        deps=IngestDeps(db=_db, embed_fn=embed_text),
        model=settings.reasoning_model,
    )
    return result.output


async def run_recall_agent(
    question: str, hints: list[str] | None = None
) -> RecallResponse:
    prompt = question
    if hints:
        hint_str = ", ".join(hints)
        prompt = f"Possibly related nodes: {hint_str}\n\n{question}"

    result = await _recall_agent.run(
        prompt,
        deps=RecallDeps(db=_db, embed_fn=embed_text),
        model=settings.reasoning_model,
    )
    output = result.output  # RecallOutput

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
        embed_fn=embed_text,
        model_setting=settings.reasoning_model,
    )

    # Build PydanticAI message history
    pydantic_history = []
    for turn in history:
        pydantic_history.append(ModelRequest(parts=[UserPromptPart(content=turn.user)]))
        pydantic_history.append(
            ModelResponse(parts=[TextPart(content=turn.assistant.response)])
        )

    result = await _converse_agent.run(
        message,
        deps=deps,
        model=settings.reasoning_model,
        message_history=pydantic_history,
    )

    ctx = deps.context if (deps.context.nodes or deps.context.edges) else None
    return ConverseResponse(response=result.output, context=ctx)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest):
    summary = await run_ingest_agent(req.text, req.hints if req.hints else None)
    return IngestResponse(summary=summary)


@app.post("/recall", response_model=RecallResponse)
async def recall(req: RecallRequest):
    return await run_recall_agent(req.question, req.hints if req.hints else None)


@app.post("/converse", response_model=ConverseResponse)
async def converse(req: ConverseRequest):
    return await run_converse_agent(req.message, req.history)


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
