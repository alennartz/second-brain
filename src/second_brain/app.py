from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from second_brain.agents.converse import ConverseDeps, create_converse_agent
from second_brain.agents.ingest import AgentIngestBatchRunner, create_ingest_agent
from second_brain.agents.ingestion_pipeline import IngestionPipeline
from second_brain.agents.recall import (
    NO_EVIDENCE_ANSWER,
    RecallCitationError,
    RecallDeps,
    RecallRunLimitExceeded,
    create_recall_agent,
    fetch_cited_context,
    require_resolved_citations,
    run_recall,
)
from second_brain.config import settings
from second_brain.db import Embedder, IdempotencyConflict, Storage
from second_brain.mcp import configure as configure_mcp
from second_brain.mcp import mcp
from second_brain.models import (
    Context,
    EnqueueResult,
    IntakeRequest,
    PipelineSnapshot,
    normalize_edge,
    normalize_node,
)
from second_brain.scheduler import DreamScheduler
from second_brain.validation import validate_record_id

# Send logs to stdout so the systemd user service owns the journal lifecycle.
_log_fmt = logging.Formatter(
    "%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
_console = logging.StreamHandler()
_console.setFormatter(_log_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_console])
logger = logging.getLogger(__name__)

_storage: Storage | None = None
_model: Any = None
_routing_model: Any = None  # Optional optimization; startup failure leaves this unset.
_scheduler: DreamScheduler | None = None
_ingestion_pipeline: IngestionPipeline | None = None
_ingest_agent = create_ingest_agent()
_recall_agent = create_recall_agent()
_converse_agent = create_converse_agent()

# ── Background dream job store ───────────────────────────────────────────────


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"


_background_tasks: set[asyncio.Task[None]] = set()


class _DummyEmbedder:
    """Zero-vector embedder for test mode."""

    def __init__(self, dimensions: int) -> None:
        self._dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        return [0.0] * self._dimensions

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self._dimensions for _ in texts]


class _EmbedFnAdapter:
    """Wraps a bare embed callable into the Embedder protocol."""

    def __init__(self, embed_fn: Any) -> None:
        self._embed_fn = embed_fn

    async def embed(self, text: str) -> list[float]:
        return await self._embed_fn(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if hasattr(self._embed_fn, "embed_batch"):
            return await self._embed_fn.embed_batch(texts)
        return [await self._embed_fn(t) for t in texts]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _storage, _model, _ingestion_pipeline
    if settings.test_mode:
        from pydantic_ai.models.test import TestModel

        logger.info("Starting in TEST mode (in-memory DB, TestModel)")
        _model = TestModel()
        embedder: Embedder = _DummyEmbedder(settings.embedding_dimensions)
        _storage = Storage(
            url="mem://",
            embedder=embedder,
            dimensions=settings.embedding_dimensions,
        )
    else:
        from second_brain.providers import create_embed_fn, create_model

        logger.info(
            "Starting with model=%s, effort=%s, embedding=%s",
            settings.reasoning_model,
            settings.reasoning_effort or "provider default",
            settings.embedding_model,
        )
        _model = create_model(
            settings.reasoning_model,
            settings.reasoning_foundry_url,
            settings.reasoning_auth,
            settings.reasoning_key,
            base_url=settings.reasoning_base_url,
            reasoning_effort=settings.reasoning_effort,
            chat_template_kwargs=settings.reasoning_chat_template_kwargs,
            temperature=settings.reasoning_temperature,
        )
        embed_fn = create_embed_fn(
            settings.embedding_model,
            settings.embedding_foundry_url,
            settings.embedding_auth,
            settings.embedding_key,
            settings.embedding_dimensions,
            base_url=settings.embedding_base_url,
        )
        embedder = _EmbedFnAdapter(embed_fn)
        _storage = Storage(
            url=f"surrealkv://{settings.db_path}",
            embedder=embedder,
            dimensions=settings.embedding_dimensions,
        )
    try:
        await _storage.init()
        logger.info("Database schema initialized")

        global _scheduler
        if not settings.test_mode and settings.dream_enabled:
            if settings.dream_batch_size <= 0:
                logger.warning(
                    "Dream scheduler disabled: batch_size=%d is not positive",
                    settings.dream_batch_size,
                )
            else:
                assert _storage is not None
                _scheduler = DreamScheduler(
                    storage=_storage,
                    model=_model,
                    idle_timeout=settings.dream_idle_timeout_minutes
                    * 60,  # convert minutes to seconds
                    batch_size=settings.dream_batch_size,
                    delay_multiplier=settings.dream_delay_multiplier,
                    max_delay=settings.dream_max_delay_minutes
                    * 60,  # convert minutes to seconds
                )
                _scheduler.start()
                logger.info("Dream scheduler started")

        assert _storage is not None
        _ingestion_pipeline = IngestionPipeline(
            storage=_storage,
            runner=AgentIngestBatchRunner(_ingest_agent, _storage, _model),
            max_request_chars=settings.intake_max_request_chars,
            chunk_chars=settings.intake_chunk_chars,
            processing_batch_chars=settings.intake_processing_batch_chars,
            worker_concurrency=settings.intake_worker_concurrency,
            lease_seconds=settings.intake_lease_seconds,
            poll_interval_seconds=settings.intake_poll_interval_seconds,
            retry_base_delay_seconds=settings.intake_retry_base_delay_seconds,
            retry_max_delay_seconds=settings.intake_retry_max_delay_seconds,
            shutdown_grace_seconds=settings.intake_shutdown_grace_seconds,
            activity_callback=(
                _scheduler.touch_activity if _scheduler is not None else None
            ),
        )
        await _ingestion_pipeline.start()
        logger.info("Ingestion pipeline started")

        configure_mcp(
            run_recall=run_recall_agent,
            run_ingest=stage_mcp_ingest,
            get_graph=get_graph_data,
        )

        # Create a fresh MCP ASGI app each startup so the session manager
        # is never reused (it is single-use by design).
        mcp_app = mcp.http_app(path="/", stateless_http=True, json_response=True)
        # Remove any stale /mcp mount from a previous lifespan cycle (e.g. tests)
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", None) != "/mcp"
        ]
        app.mount("/mcp", mcp_app)
    except Exception:
        if _ingestion_pipeline is not None:
            with contextlib.suppress(Exception):
                await _ingestion_pipeline.stop()
            _ingestion_pipeline = None
        if _scheduler is not None:
            with contextlib.suppress(Exception):
                await _scheduler.stop()
            _scheduler = None
        await _storage.close()
        _storage = None
        raise

    try:
        async with mcp_app.router.lifespan_context(app):
            yield
    finally:
        pipeline = _ingestion_pipeline
        _ingestion_pipeline = None
        try:
            if pipeline is not None:
                await pipeline.stop()
        finally:
            if _scheduler:
                await _scheduler.stop()
                _scheduler = None
            if _storage:
                await _storage.close()
                _storage = None


app = FastAPI(title="Second Brain", lifespan=lifespan)


class IngestRequest(BaseModel):
    text: str
    hints: list[str] = []
    source: str = "api"


class IngestResponse(BaseModel):
    chunks_stored: int


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


async def stage_mcp_ingest(text: str, hints: list[str] | None = None) -> EnqueueResult:
    """Stage an intake submitted through the MCP server."""
    pipeline = _ingestion_pipeline
    if pipeline is None:
        raise RuntimeError("Intake staging is unavailable")
    return await pipeline.enqueue(
        IntakeRequest(text=text, hints=tuple(hints or ()), source="mcp")
    )


async def run_recall_agent(
    question: str, hints: list[str] | None = None
) -> RecallResponse:
    assert _storage is not None
    prompt = question
    if hints:
        hint_str = ", ".join(hints)
        prompt = f"Possibly related nodes: {hint_str}\n\n{question}"

    logger.info("Recall agent starting (question length=%d)", len(question))
    try:
        output = await run_recall(
            prompt,
            deps=RecallDeps(storage=_storage),
            model=_model,
            agent=_recall_agent,
        )
    except RecallRunLimitExceeded as exc:
        logger.warning("Recall did not produce a valid answer: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    logger.info(
        "Recall agent completed (cited %d nodes, %d edges, %d unprocessed chunks)",
        len(output.cited_node_ids),
        len(output.cited_edge_ids),
        len(output.cited_unprocessed_ids),
    )

    # Fetch actual records for cited IDs. Malformed IDs and intake chunks deleted
    # while the answer was being generated are skipped.
    assert _storage is not None
    context = await fetch_cited_context(_storage, output)
    try:
        require_resolved_citations(output, context)
    except RecallCitationError as exc:
        logger.error("Recall citations could not be resolved: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return RecallResponse(
        answer=output.answer if output.answer is not None else NO_EVIDENCE_ANSWER,
        context=context if output.has_evidence else None,
    )


async def run_converse_agent(
    message: str, history: list[HistoryTurn]
) -> ConverseResponse:
    assert _storage is not None
    deps = ConverseDeps(
        storage=_storage,
        model_setting=_model,
        ingestion_pipeline=_ingestion_pipeline,
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

    ctx = (
        deps.context
        if (deps.context.nodes or deps.context.edges or deps.context.unprocessed)
        else None
    )
    return ConverseResponse(response=result.output, context=ctx)


@app.get("/health")
async def health():
    return {"status": "ok"}


class DreamJobResponse(BaseModel):
    job_id: str
    status: JobStatus
    error: str | None = None


_dream_jobs: dict[str, dict[str, Any]] = {}


@app.post("/dream", status_code=202, response_model=DreamJobResponse)
async def dream(response: Response):
    """Manually trigger one dream cycle as a background task."""
    logger.info("POST /dream")
    scheduler = _scheduler
    if scheduler is None:
        assert _storage is not None
        scheduler = DreamScheduler(
            storage=_storage,
            model=_model,
            idle_timeout=0,
            batch_size=settings.dream_batch_size,
            delay_multiplier=settings.dream_delay_multiplier,
            max_delay=settings.dream_max_delay_minutes
            * 60,  # convert minutes to seconds
        )
    else:
        scheduler.touch_activity()  # pause any in-progress auto-dream

    job_id = str(uuid.uuid4())
    _dream_jobs[job_id] = {"status": JobStatus.pending, "error": None}

    async def _run_dream() -> None:
        _dream_jobs[job_id]["status"] = JobStatus.running
        try:
            await scheduler.run_cycle()
            _dream_jobs[job_id]["status"] = JobStatus.complete
        except Exception as exc:
            logger.exception("Dream job %s failed", job_id)
            _dream_jobs[job_id]["status"] = JobStatus.failed
            _dream_jobs[job_id]["error"] = str(exc)

    task = asyncio.create_task(_run_dream())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    response.headers["Location"] = f"/dream/jobs/{job_id}"
    return DreamJobResponse(job_id=job_id, status=JobStatus.pending)


@app.get("/dream/jobs/{job_id}", response_model=DreamJobResponse)
async def get_dream_job(job_id: str):
    job = _dream_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return DreamJobResponse(job_id=job_id, status=job["status"], error=job["error"])


@app.post("/ingest", response_model=IngestResponse)
async def ingest(
    req: IngestRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> IngestResponse:
    """Synchronously stage intake chunks for search and background processing."""
    pipeline = _ingestion_pipeline
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Intake staging is unavailable")
    if _scheduler:
        _scheduler.touch_activity()
    logger.info("POST /ingest (text length=%d)", len(req.text))
    try:
        result = await pipeline.enqueue(
            IntakeRequest(
                text=req.text,
                hints=tuple(req.hints),
                source=req.source,
                idempotency_key=idempotency_key,
            )
        )
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IngestResponse(chunks_stored=result.chunks_stored)


@app.get("/ingest/pipeline", response_model=PipelineSnapshot)
async def get_ingestion_pipeline_snapshot() -> PipelineSnapshot:
    """Return aggregate queue and worker visibility."""
    pipeline = _ingestion_pipeline
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Intake pipeline is unavailable")
    return await pipeline.snapshot()


@app.post("/ingest/pipeline/{intake_id}/pause")
async def pause_ingestion(intake_id: str) -> dict[str, str]:
    """Pause ready and retrying chunks for one intake."""
    pipeline = _ingestion_pipeline
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Intake pipeline is unavailable")
    changed = await pipeline.pause_intake(intake_id)
    if changed == 0:
        raise HTTPException(status_code=404, detail=f"Intake {intake_id} not found")
    return {"intake_id": intake_id}


@app.post("/ingest/pipeline/{intake_id}/resume")
async def resume_ingestion(intake_id: str) -> dict[str, str]:
    """Resume paused chunks for one intake."""
    pipeline = _ingestion_pipeline
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Intake pipeline is unavailable")
    changed = await pipeline.resume_intake(intake_id)
    if changed == 0:
        raise HTTPException(status_code=404, detail=f"Intake {intake_id} not found")
    return {"intake_id": intake_id}


@app.post("/ingest/pipeline/{intake_id}/discard")
async def discard_ingestion(intake_id: str) -> dict[str, str | int]:
    """Discard remaining chunks for one intake."""
    pipeline = _ingestion_pipeline
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Intake pipeline is unavailable")
    chunks_discarded = await pipeline.discard_intake(intake_id)
    if chunks_discarded == 0:
        raise HTTPException(status_code=404, detail=f"Intake {intake_id} not found")
    return {"intake_id": intake_id, "chunks_discarded": chunks_discarded}


@app.post("/recall", response_model=RecallResponse)
async def recall(req: RecallRequest):
    if _scheduler:
        _scheduler.touch_activity()
    logger.info("POST /recall")
    return await run_recall_agent(req.question, req.hints if req.hints else None)


@app.post("/converse", response_model=ConverseResponse)
async def converse(req: ConverseRequest):
    if _scheduler:
        _scheduler.touch_activity()
    logger.info("POST /converse")
    return await run_converse_agent(req.message, req.history)


async def get_graph_data(record_id: str) -> GraphResponse | None:
    """Fetch a node and its connections. Returns None if not found."""
    assert _storage is not None
    validate_record_id(record_id)
    node = await _storage.get_node(record_id)
    if not node:
        return None

    out_edges = await _storage.get_outgoing_edges(record_id)
    in_edges = await _storage.get_incoming_edges(record_id)
    raw_edges = out_edges + in_edges

    connections = []
    for edge in raw_edges:
        raw_in = edge.get("in")
        raw_out = edge.get("out")
        if raw_in is None or raw_out is None:
            continue
        other_id = raw_in if raw_out == record_id else raw_out
        if other_id:
            other_node = await _storage.get_node(str(other_id))
            if other_node:
                connections.append(
                    ConnectionItem(
                        edge=normalize_edge(edge),
                        node=normalize_node(other_node),
                    )
                )
    return GraphResponse(node=normalize_node(node), connections=connections)


@app.post("/converse/stream")
async def converse_stream(req: ConverseRequest):
    logger.info("POST /converse/stream")
    assert _storage is not None
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    deps = ConverseDeps(
        storage=_storage,
        model_setting=_model,
        progress_queue=queue,
        ingestion_pipeline=_ingestion_pipeline,
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
            ctx = (
                deps.context
                if (
                    deps.context.nodes or deps.context.edges or deps.context.unprocessed
                )
                else None
            )
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
    result = await get_graph_data(record_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Node {record_id} not found")
    return result
