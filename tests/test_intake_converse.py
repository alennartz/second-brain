"""Converse ingest delegates synchronous staging instead of running the ingest agent."""

import asyncio
import importlib
import json
import re
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai import models
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from second_brain.agents.converse import (
    ConverseDeps,
    create_converse_agent,
    run_converse_turn,
)
from second_brain.agents.ingestion_pipeline import IngestionPipeline
from second_brain.db import Storage
from second_brain.models import Context, EnqueueResult, IntakeRequest
from tests.test_converse_agent import relay_converse_model, routing_model

converse_module = importlib.import_module("second_brain.agents.converse")
app_module = importlib.import_module("second_brain.app")


@pytest.fixture
def converse_staging(monkeypatch):
    pipeline = Mock(spec=IngestionPipeline)
    pipeline.enqueue.return_value = EnqueueResult(chunks_stored=7)
    storage = Mock(spec=Storage)
    legacy_ingest = Mock(run=AsyncMock(return_value=Mock(output="Old agent output")))
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    monkeypatch.setattr(converse_module, "create_ingest_agent", lambda: legacy_ingest)
    return pipeline, storage, legacy_ingest


async def run_ingest_turn(path, text, deps):
    if path == "tool":
        result = await create_converse_agent().run(
            text, deps=deps, model=relay_converse_model("ingest", "text")
        )
        return result.output

    async def forbidden_router(messages, info):
        raise AssertionError("Pure ingest must bypass the conversational router")

    return await run_converse_turn(
        text,
        [],
        deps=deps,
        model=FunctionModel(forbidden_router),
        routing_model=routing_model(
            ingest=True,
            confidence={"is_pure_recall": 0.01, "is_pure_ingest": 0.99},
        ),
    )


@pytest.mark.parametrize("path", ["tool", "fast"])
async def test_converse_ingest_stages_original_text_without_calling_old_agent(
    converse_staging, path
):
    pipeline, storage, legacy_ingest = converse_staging
    existing_context = Context(
        nodes=[{"id": "note:earlier", "table": "note", "content": "Earlier recall"}],
        edges=[
            {"id": "references:earlier", "from": "note:earlier", "to": "entity:topic"}
        ],
        unprocessed=[{"id": "intake_chunk:earlier", "content": "Earlier intake"}],
    )
    queue = asyncio.Queue()
    deps = ConverseDeps(
        storage=storage,
        model_setting=TestModel(call_tools=[]),
        context=existing_context.model_copy(deep=True),
        progress_queue=queue,
        ingestion_pipeline=pipeline,
    )
    text = "  Store this source exactly.\n\nDo not summarize before staging.  "

    result = await run_ingest_turn(path, text, deps)

    legacy_ingest.run.assert_not_awaited()
    pipeline.enqueue.assert_awaited_once_with(
        IntakeRequest(text=text, source="converse")
    )
    assert isinstance(result, str)
    assert re.search(r"\b7\b", result)
    assert "queue" in result.lower() or "unprocessed" in result.lower()
    assert deps.context == existing_context
    assert storage.method_calls == []
    statuses = []
    while not queue.empty():
        statuses.append(queue.get_nowait())
    assert statuses
    assert any(
        "queue" in event["message"].lower() or "unprocessed" in event["message"].lower()
        for event in statuses
    )
    assert not any(event["message"] == "Knowledge stored" for event in statuses)


async def test_converse_ingest_tool_waits_for_searchable_staging_before_acknowledging(
    converse_staging,
):
    pipeline, storage, legacy_ingest = converse_staging
    entered = asyncio.Event()
    release = asyncio.Event()

    async def enqueue(request):
        entered.set()
        await release.wait()
        return EnqueueResult(chunks_stored=2)

    pipeline.enqueue.side_effect = enqueue
    deps = ConverseDeps(
        storage=storage,
        model_setting=TestModel(call_tools=[]),
        ingestion_pipeline=pipeline,
    )
    run_task = asyncio.create_task(
        run_ingest_turn("tool", "Intake from converse", deps)
    )
    entered_task = asyncio.create_task(entered.wait())
    try:
        await asyncio.wait(
            [run_task, entered_task],
            return_when=asyncio.FIRST_COMPLETED,
            timeout=1,
        )
        assert entered.is_set(), "Converse bypassed the staging pipeline"
        assert not run_task.done(), "Converse acknowledged unfinished staging"
        release.set()
        result = await asyncio.wait_for(run_task, timeout=1)

        assert re.search(r"\b2\b", result)
        assert "queue" in result.lower() or "unprocessed" in result.lower()
        legacy_ingest.run.assert_not_awaited()
    finally:
        release.set()
        for task in (run_task, entered_task):
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def test_converse_ingest_staging_failure_does_not_fall_back_to_old_agent(
    converse_staging,
):
    pipeline, storage, legacy_ingest = converse_staging
    pipeline.enqueue.side_effect = RuntimeError("Intake embedding failed")
    deps = ConverseDeps(
        storage=storage,
        model_setting=TestModel(call_tools=[]),
        ingestion_pipeline=pipeline,
    )

    with pytest.raises(RuntimeError, match="Intake embedding failed"):
        await run_ingest_turn("tool", "The intake must fail", deps)

    pipeline.enqueue.assert_awaited_once_with(
        IntakeRequest(text="The intake must fail", source="converse")
    )
    legacy_ingest.run.assert_not_awaited()
    assert storage.method_calls == []


@pytest.mark.parametrize("endpoint", ["/converse", "/converse/stream"])
async def test_http_converse_injects_the_shared_staging_pipeline(
    converse_staging, monkeypatch, endpoint
):
    pipeline, storage, legacy_ingest = converse_staging
    captured_deps = []

    async def converse_turn(message, *args, deps, **kwargs):
        captured_deps.append(deps)
        return "The staging pipeline is available."

    async def converse_run(message, *, deps, **kwargs):
        return SimpleNamespace(output=await converse_turn(message, deps=deps))

    monkeypatch.setattr(
        app_module,
        "run_converse_turn",
        AsyncMock(side_effect=converse_turn),
        raising=False,
    )
    monkeypatch.setattr(app_module, "_storage", storage)
    monkeypatch.setattr(app_module, "_model", None)
    monkeypatch.setattr(app_module, "_scheduler", None)
    monkeypatch.setattr(app_module, "_routing_model", None)
    monkeypatch.setattr(app_module, "_ingestion_pipeline", pipeline, raising=False)
    monkeypatch.setattr(
        app_module, "_converse_agent", Mock(run=AsyncMock(side_effect=converse_run))
    )

    async with AsyncClient(
        transport=ASGITransport(app=app_module.app), base_url="http://test"
    ) as client:
        response = await client.post(
            endpoint, json={"message": "A conversational turn"}
        )

    assert response.status_code == 200
    assert len(captured_deps) == 1
    assert captured_deps[0].ingestion_pipeline is pipeline
    assert captured_deps[0].storage is storage
    if endpoint.endswith("/stream"):
        done = [
            event
            for event in response.text.split("\n\n")
            if event.startswith("event: done\n")
        ]
        assert len(done) == 1
        body = json.loads(done[0].split("data: ", 1)[1])
    else:
        body = response.json()
    assert body["response"] == "The staging pipeline is available."
    pipeline.enqueue.assert_not_awaited()
    legacy_ingest.run.assert_not_awaited()
