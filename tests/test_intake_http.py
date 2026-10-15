"""HTTP contracts for synchronous staging through an injected intake pipeline."""

import asyncio
import importlib
from contextlib import suppress
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai import models

from second_brain.agents.ingestion_pipeline import IngestionPipeline
from second_brain.config import settings
from second_brain.db import Storage
from second_brain.models import EnqueueResult, IntakeRequest, PipelineSnapshot

app_module = importlib.import_module("second_brain.app")


@pytest.fixture
async def intake_app(monkeypatch):
    pipeline = Mock(spec=IngestionPipeline)
    pipeline.enqueue.return_value = EnqueueResult(chunks_stored=7)
    pipeline.snapshot.return_value = PipelineSnapshot(
        ready=17,
        leased=2,
        retry_wait=3,
        paused=5,
        oldest_ready_at=datetime(2026, 10, 15, 12, tzinfo=UTC),
        oldest_retry_at=datetime(2026, 10, 15, 11, tzinfo=UTC),
        worker_count=4,
        active_leases=2,
        stuck_intakes=[{"intake_id": "intake-stuck", "last_error": "write failed"}],
        recent_errors=[{"intake_id": "intake-retry", "error": "embedding failed"}],
    )
    pipeline.pause_intake.return_value = None
    pipeline.resume_intake.return_value = None
    pipeline.discard_intake.return_value = 6
    storage = Mock(spec=Storage)
    legacy_ingest = AsyncMock(return_value="The old ingest runner must not run")
    scheduler = Mock()
    background_tasks = set()

    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    # The app must expose this staging seam. Tests do not start its workers.
    monkeypatch.setattr(app_module, "_ingestion_pipeline", pipeline, raising=False)
    monkeypatch.setattr(app_module, "_storage", storage)
    monkeypatch.setattr(app_module, "_scheduler", scheduler)
    monkeypatch.setattr(app_module, "_ingest_agent", Mock(run=legacy_ingest))
    monkeypatch.setattr(app_module, "_background_tasks", background_tasks)

    try:
        yield pipeline, storage, legacy_ingest, scheduler
    finally:
        # Keep any background tasks inside the mocked test scope.
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)


@pytest.fixture
async def client(intake_app):
    async with AsyncClient(
        transport=ASGITransport(app=app_module.app, raise_app_exceptions=False),
        base_url="http://test",
    ) as test_client:
        yield test_client


async def test_post_ingest_stages_synchronously_without_running_ingest_agent(
    client, intake_app
):
    pipeline, _, legacy_ingest, scheduler = intake_app
    response = await client.post("/ingest", json={"text": "Raw intake text."})
    await asyncio.sleep(0)

    assert response.status_code == 200
    assert response.json() == {"chunks_stored": 7}
    assert "location" not in response.headers
    pipeline.enqueue.assert_awaited_once_with(IntakeRequest(text="Raw intake text."))
    legacy_ingest.assert_not_awaited()
    scheduler.touch_activity.assert_called_once_with()


@pytest.mark.parametrize(
    ("payload", "headers", "expected"),
    [
        (
            {"text": "  Original text.\n\nDo not rewrite it.  "},
            {},
            IntakeRequest(text="  Original text.\n\nDo not rewrite it.  "),
        ),
        (
            {
                "text": "First paragraph.\n\nSecond paragraph.",
                "hints": ["entity:one", "note:two"],
                "source": "cli",
            },
            {"Idempotency-Key": "request-1"},
            IntakeRequest(
                text="First paragraph.\n\nSecond paragraph.",
                hints=("entity:one", "note:two"),
                source="cli",
                idempotency_key="request-1",
            ),
        ),
    ],
)
async def test_post_ingest_preserves_staging_request_metadata(
    client, intake_app, payload, headers, expected
):
    pipeline, _, legacy_ingest, _ = intake_app

    response = await client.post("/ingest", json=payload, headers=headers)

    assert response.status_code == 200
    pipeline.enqueue.assert_awaited_once_with(expected)
    legacy_ingest.assert_not_awaited()


async def test_post_ingest_waits_until_every_chunk_is_searchable(client, intake_app):
    pipeline, _, legacy_ingest, _ = intake_app
    entered = asyncio.Event()
    release = asyncio.Event()
    searchable_chunks = []

    async def enqueue(request):
        assert request == IntakeRequest(text="A complete intake document.")
        entered.set()
        await release.wait()
        searchable_chunks.extend(["intake_chunk:one", "intake_chunk:two"])
        return EnqueueResult(chunks_stored=2)

    pipeline.enqueue.side_effect = enqueue
    request_task = asyncio.create_task(
        client.post("/ingest", json={"text": "A complete intake document."})
    )
    entered_task = asyncio.create_task(entered.wait())
    try:
        await asyncio.wait(
            [request_task, entered_task],
            return_when=asyncio.FIRST_COMPLETED,
            timeout=1,
        )
        assert entered.is_set(), "POST /ingest bypassed synchronous staging"
        assert not request_task.done(), "The response preceded searchable chunks"
        assert searchable_chunks == []
        release.set()
        response = await asyncio.wait_for(request_task, timeout=1)

        assert response.status_code == 200
        assert response.json() == {"chunks_stored": len(searchable_chunks)}
        assert len(searchable_chunks) == 2
        legacy_ingest.assert_not_awaited()
    finally:
        release.set()
        for task in (request_task, entered_task):
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def test_post_ingest_staging_failure_is_not_a_successful_job_receipt(
    client, intake_app
):
    pipeline, _, legacy_ingest, _ = intake_app
    pipeline.enqueue.side_effect = RuntimeError("Embedding provider unavailable")

    response = await client.post("/ingest", json={"text": "Do not partly stage this"})

    assert 500 <= response.status_code < 600
    assert "location" not in response.headers
    assert "chunks_stored" not in response.text
    assert "job_id" not in response.text
    pipeline.enqueue.assert_awaited_once()
    legacy_ingest.assert_not_awaited()


@pytest.mark.parametrize("text", ["", " \n\t", "x" * 33])
async def test_post_ingest_rejects_empty_or_over_limit_intake(
    client, intake_app, monkeypatch, text
):
    pipeline, _, legacy_ingest, _ = intake_app
    monkeypatch.setattr(settings, "intake_max_request_chars", 32)
    pipeline.enqueue.side_effect = ValueError("Empty or over-limit intake text")

    response = await client.post("/ingest", json={"text": text})

    assert response.status_code in {400, 422}
    assert "location" not in response.headers
    assert "chunks_stored" not in response.json()
    assert "job_id" not in response.json()
    legacy_ingest.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"text": None},
        {"text": ["not a string"]},
        {"text": "valid text", "hints": "not a list"},
        {"text": "valid text", "source": {"invalid": "metadata"}},
    ],
)
async def test_post_ingest_rejects_invalid_request_before_staging(
    client, intake_app, payload
):
    pipeline, _, legacy_ingest, _ = intake_app

    response = await client.post("/ingest", json=payload)

    assert response.status_code == 422
    pipeline.enqueue.assert_not_awaited()
    legacy_ingest.assert_not_awaited()


async def test_get_pipeline_snapshot_forwards_aggregate_queue_visibility(
    client, intake_app
):
    pipeline, storage, legacy_ingest, _ = intake_app

    response = await client.get("/ingest/pipeline")

    assert response.status_code == 200
    body = response.json()
    for field, count in {
        "ready": 17,
        "leased": 2,
        "retry_wait": 3,
        "paused": 5,
        "worker_count": 4,
        "active_leases": 2,
    }.items():
        assert body[field] == count
    assert datetime.fromisoformat(body["oldest_ready_at"]) == datetime(
        2026, 10, 15, 12, tzinfo=UTC
    )
    assert datetime.fromisoformat(body["oldest_retry_at"]) == datetime(
        2026, 10, 15, 11, tzinfo=UTC
    )
    assert body["stuck_intakes"] == pipeline.snapshot.return_value.stuck_intakes
    assert body["recent_errors"] == pipeline.snapshot.return_value.recent_errors
    pipeline.snapshot.assert_awaited_once_with()
    assert storage.method_calls == []
    legacy_ingest.assert_not_awaited()


@pytest.mark.parametrize("action", ["pause", "resume", "discard"])
async def test_pipeline_intake_controls_delegate_only_to_the_selected_operation(
    client, intake_app, action
):
    pipeline, storage, legacy_ingest, _ = intake_app

    response = await client.post(f"/ingest/pipeline/intake-1/{action}")

    assert response.status_code == 200
    body = response.json()
    assert body["intake_id"] == "intake-1"
    if action == "discard":
        assert body["chunks_discarded"] == 6
    assert "graph_records_rolled_back" not in body
    for operation in ("pause", "resume", "discard"):
        method = getattr(pipeline, f"{operation}_intake")
        if operation == action:
            method.assert_awaited_once_with("intake-1")
        else:
            method.assert_not_awaited()
    assert storage.method_calls == []
    legacy_ingest.assert_not_awaited()


async def test_old_ingest_job_polling_route_is_removed(client):
    response = await client.get("/ingest/jobs/old-receipt")

    assert response.status_code == 404
    assert "/ingest/jobs/{job_id}" not in app_module.app.openapi()["paths"]
