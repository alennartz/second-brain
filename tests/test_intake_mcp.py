"""MCP contracts with configured staging callbacks and no ASGI lifespan."""

import importlib
import json
import re
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic_ai import models

from second_brain.agents.ingestion_pipeline import IngestionPipeline
from second_brain.app import RecallResponse
from second_brain.models import Context, EnqueueResult, IntakeRequest

mcp_module = importlib.import_module("second_brain.mcp")
app_module = importlib.import_module("second_brain.app")


@pytest.fixture
def configured_mcp(monkeypatch):
    pipeline = Mock(spec=IngestionPipeline)
    pipeline.enqueue.return_value = EnqueueResult(chunks_stored=7)

    async def stage_ingest(text, hints=None):
        return await pipeline.enqueue(
            IntakeRequest(text=text, hints=tuple(hints or ()), source="mcp")
        )

    staging = AsyncMock(side_effect=stage_ingest)
    recall = AsyncMock()
    graph = AsyncMock()
    legacy_ingest = AsyncMock(side_effect=AssertionError("The old agent must not run"))
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    monkeypatch.setattr(app_module, "run_ingest_agent", legacy_ingest)
    for name in ("_run_ingest", "_run_recall", "_get_graph"):
        monkeypatch.setattr(mcp_module, name, None)
    mcp_module.configure(run_ingest=staging, run_recall=recall, get_graph=graph)
    return pipeline, staging, recall, legacy_ingest


@pytest.mark.parametrize("hints", [None, ["entity:one", "note:two"]])
async def test_mcp_ingest_reports_queued_count_from_configured_staging(
    configured_mcp, hints
):
    pipeline, staging, _, legacy_ingest = configured_mcp

    result = await mcp_module.ingest(text="Original MCP intake text.", hints=hints)

    if isinstance(result, EnqueueResult):
        assert result.chunks_stored == 7
    elif isinstance(result, dict):
        assert result["chunks_stored"] == 7
        assert "job_id" not in result
    else:
        assert isinstance(result, str)
        try:
            payload = json.loads(result)
        except json.JSONDecodeError:
            assert re.search(r"\b7\b", result)
            assert "queue" in result.lower() or "unprocessed" in result.lower()
            assert "job_id" not in result
        else:
            assert payload["chunks_stored"] == 7
            assert "job_id" not in payload
    staging.assert_awaited_once_with("Original MCP intake text.", hints)
    pipeline.enqueue.assert_awaited_once_with(
        IntakeRequest(
            text="Original MCP intake text.",
            hints=tuple(hints or ()),
            source="mcp",
        )
    )
    legacy_ingest.assert_not_awaited()


@pytest.mark.parametrize("unprocessed_only", [False, True])
async def test_mcp_recall_labels_unprocessed_citations_separately(
    configured_mcp, unprocessed_only
):
    _, _, recall, _ = configured_mcp
    recall.return_value = RecallResponse(
        answer="The intake evidence is not organized yet.",
        context=Context(
            nodes=[] if unprocessed_only else [{"id": "note:organized"}],
            edges=[],
            unprocessed=[
                {
                    "id": "intake_chunk:pending",
                    "intake_id": "intake-1",
                    "chunk_index": 1,
                    "total_chunks": 3,
                    "content": "Pending source evidence",
                    "source": "mcp",
                    "unprocessed": True,
                }
            ],
        ),
    )

    result = await mcp_module.recall("What did I submit?", ["note:hint"])

    assert result.startswith(recall.return_value.answer)
    recall.assert_awaited_once_with("What did I submit?", ["note:hint"])
    citation_lines = result.splitlines()[1:]
    unprocessed_lines = [
        line for line in citation_lines if "unprocessed" in line.lower()
    ]
    assert len(unprocessed_lines) == 1
    assert "intake_chunk:pending" in unprocessed_lines[0]
    node_lines = [line for line in citation_lines if line.startswith("Cited nodes:")]
    if unprocessed_only:
        assert node_lines == []
    else:
        assert len(node_lines) == 1
        assert "note:organized" in node_lines[0]
    assert not any("intake_chunk:" in line for line in node_lines)
    assert not any("note:organized" in line for line in unprocessed_lines)
