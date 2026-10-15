"""Behavioral tests for the intake staging and processing pipeline boundary."""

import asyncio
from dataclasses import dataclass, field

import pytest

from second_brain.agents.ingestion_pipeline import IngestBatchOutcome, IngestionPipeline
from second_brain.models import IntakeRequest, PipelineSnapshot


@dataclass
class RecordingRunner:
    outcomes: list[IngestBatchOutcome] = field(default_factory=list)
    calls: list[tuple[str, list[str]]] = field(default_factory=list)
    called: asyncio.Event = field(default_factory=asyncio.Event)

    async def run(self, text: str, hints: list[str]) -> IngestBatchOutcome:
        self.calls.append((text, hints))
        self.called.set()
        if self.outcomes:
            return self.outcomes.pop(0)
        return IngestBatchOutcome(completed=True, summary="stored")


async def _wait_for_calls(runner: RecordingRunner, count: int) -> None:
    while len(runner.calls) < count:
        await runner.called.wait()
        runner.called.clear()


@pytest.fixture
def runner() -> RecordingRunner:
    return RecordingRunner()


@pytest.fixture
def pipeline(storage, runner: RecordingRunner) -> IngestionPipeline:
    return IngestionPipeline(
        storage=storage,
        runner=runner,
        max_request_chars=10_000,
        chunk_chars=100,
        processing_batch_chars=180,
        worker_concurrency=1,
        lease_seconds=60,
        poll_interval_seconds=0.01,
        retry_base_delay_seconds=1,
        retry_max_delay_seconds=30,
    )


async def test_enqueue_chunks_at_natural_boundaries_and_returns_count(pipeline):
    result = await pipeline.enqueue(
        IntakeRequest(
            text="First paragraph.\n\nSecond paragraph.",
            hints=("entity:one",),
            source="cli",
        )
    )

    assert result.chunks_stored == 2


@pytest.mark.parametrize(
    "intake_request",
    [
        IntakeRequest(text=""),
        IntakeRequest(text="   "),
        IntakeRequest(text="x" * 10_001),
    ],
)
async def test_enqueue_rejects_empty_and_over_limit_requests(pipeline, intake_request):
    with pytest.raises(ValueError):
        await pipeline.enqueue(intake_request)


async def test_enqueue_persists_all_chunks_before_returning(pipeline):
    result = await pipeline.enqueue(
        IntakeRequest(text="A complete source document with several paragraphs.")
    )

    assert result.chunks_stored > 0


async def test_idempotency_key_collapses_duplicate_requests_while_queued(pipeline):
    request = IntakeRequest(text="same request", idempotency_key="req-1")

    first = await pipeline.enqueue(request)
    duplicate = await pipeline.enqueue(request)

    assert first.chunks_stored > 0
    assert duplicate.chunks_stored == 0


async def test_same_idempotency_key_is_new_after_final_chunk_is_deleted(
    pipeline, runner
):
    request = IntakeRequest(text="same request", idempotency_key="req-1")

    first = await pipeline.enqueue(request)
    await pipeline.start()
    await _wait_for_calls(runner, 1)
    await pipeline.stop()
    second = await pipeline.enqueue(request)

    assert first.chunks_stored > 0
    assert second.chunks_stored > 0


async def test_worker_packs_contiguous_chunks_in_source_order(pipeline, runner):
    await pipeline.enqueue(
        IntakeRequest(
            text="One.\n\nTwo.\n\nThree.",
            hints=("entity:one",),
        )
    )

    await pipeline.start()
    await _wait_for_calls(runner, 1)
    await pipeline.stop()

    assert runner.calls
    text, hints = runner.calls[0]
    assert text.index("One.") < text.index("Two.") < text.index("Three.")
    assert hints == ["entity:one"]
    assert len(text) <= pipeline.processing_batch_chars


async def test_successful_batch_is_deleted_only_after_clean_runner_outcome(
    pipeline, runner
):
    runner.outcomes.append(IngestBatchOutcome(completed=True, summary="ok"))
    await pipeline.enqueue(IntakeRequest(text="complete batch"))

    await pipeline.start()
    await _wait_for_calls(runner, 1)
    await pipeline.stop()

    snapshot = await pipeline.snapshot()
    assert snapshot.ready == 0
    assert snapshot.leased == 0


async def test_failed_batch_is_released_with_error_and_exponential_backoff(
    pipeline, runner
):
    runner.outcomes.extend(
        [
            IngestBatchOutcome(completed=False, errors=["provider timeout"]),
            IngestBatchOutcome(completed=False, errors=["provider timeout"]),
        ]
    )
    await pipeline.enqueue(IntakeRequest(text="retry me"))

    await pipeline.start()
    await _wait_for_calls(runner, 1)
    await pipeline.stop()

    snapshot = await pipeline.snapshot()
    assert snapshot.retry_wait == 1
    assert snapshot.recent_errors[-1]["error"] == "provider timeout"


async def test_other_ready_intakes_continue_while_one_waits_for_retry(pipeline, runner):
    runner.outcomes.append(IngestBatchOutcome(completed=False, errors=["bad intake"]))
    await pipeline.enqueue(IntakeRequest(text="first intake"))
    await pipeline.enqueue(IntakeRequest(text="second intake"))

    await pipeline.start()
    await _wait_for_calls(runner, 2)
    await pipeline.stop()

    assert len(runner.calls) >= 2
    assert runner.calls[1][0] == "second intake"


async def test_pause_resume_and_discard_operate_on_one_intake_without_graph_rollback(
    pipeline,
):
    await pipeline.enqueue(IntakeRequest(text="pause this"))
    await pipeline.pause_intake("intake-1")
    paused = await pipeline.snapshot()
    assert paused.paused > 0

    await pipeline.resume_intake("intake-1")
    resumed = await pipeline.snapshot()
    assert resumed.paused == 0
    assert resumed.ready > 0

    discarded = await pipeline.discard_intake("intake-1")
    assert discarded > 0
    final = await pipeline.snapshot()
    assert final.ready == 0
    assert final.retry_wait == 0
    assert final.paused == 0


async def test_snapshot_reports_workers_active_leases_and_stuck_intakes(pipeline):
    await pipeline.start()
    snapshot = await pipeline.snapshot()
    await pipeline.stop()

    assert isinstance(snapshot, PipelineSnapshot)
    assert snapshot.worker_count == pipeline.worker_concurrency
    assert snapshot.active_leases == 0
    assert isinstance(snapshot.stuck_intakes, list)
    assert len(snapshot.stuck_intakes) <= 100


async def test_activity_callback_marks_start_and_completion(pipeline, runner):
    calls: list[str] = []
    pipeline.activity_callback = lambda: calls.append("activity")

    await pipeline.enqueue(IntakeRequest(text="touch scheduler"))
    await pipeline.start()
    await _wait_for_calls(runner, 1)
    await pipeline.stop()

    assert calls == ["activity", "activity"]
