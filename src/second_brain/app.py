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
    source: str = "api"


class IngestResponse(BaseModel):
    summary: str


class RecallRequest(BaseModel):
    question: str


class RecallResponse(BaseModel):
    answer: str


async def run_ingest_agent(text: str, source: str) -> str:
    result = await _ingest_agent.run(
        f"Source: {source}\n\n{text}",
        deps=IngestDeps(db=_db, embed_fn=embed_text),
        model=settings.reasoning_model,
    )
    return result.output


async def run_recall_agent(question: str) -> str:
    result = await _recall_agent.run(
        question,
        deps=RecallDeps(db=_db),
        model=settings.reasoning_model,
    )
    return result.output


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest):
    summary = await run_ingest_agent(req.text, req.source)
    return IngestResponse(summary=summary)


@app.post("/recall", response_model=RecallResponse)
async def recall(req: RecallRequest):
    answer = await run_recall_agent(req.question)
    return RecallResponse(answer=answer)
