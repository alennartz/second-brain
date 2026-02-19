from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel
from surrealdb import AsyncSurreal

from second_brain.agents.ingest import IngestDeps, create_ingest_agent
from second_brain.agents.recall import RecallDeps, create_recall_agent
from second_brain.config import settings
from second_brain.db import init_schema
from second_brain.embedding import embed_text, init_vector_indexes
from second_brain.models import Context, make_serializable

_db: Any = None
_ingest_agent = create_ingest_agent()
_recall_agent = create_recall_agent()


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
        deps=RecallDeps(db=_db),
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
