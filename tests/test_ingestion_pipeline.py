"""Behavioral contracts for searchable intake staging and worker processing."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from second_brain.agents.ingestion_pipeline import IngestBatchOutcome, IngestionPipeline
from second_brain.db import Storage
from second_brain.models import IntakeRequest, PipelineSnapshot

WAIT_SECONDS = 2


@dataclass
class MutableUtcClock:
    current: datetime = datetime(2026, 10, 15, tzinfo=UTC)
    read: asyncio.Event = field(default_factory=asyncio.Event)

    def __call__(self) -> datetime:
        self.read.set()
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


@dataclass
class ActivityRecorder:
    count: int = 0
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    def __call__(self) -> None:
        self.count += 1
        self.changed.set()


class RecordingEmbedder:
    """Expose embedding completion, blocking, and failures at the injected seam."""

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.started = asyncio.Event()
        self.released = asyncio.Event()
        self.released.set()
        self.fail_after: int | None = None

    async def embed(self, text: str) -> list[float]:
        self.started.set()
        await _wait_event(self.released)
        if self.fail_after is not None and len(self.texts) >= self.fail_after:
            raise RuntimeError("embedding provider failed")
        self.texts.append(text)
        return [1.0, 0.0, 0.0, 0.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(text) for text in texts]


@dataclass
class BatchCall:
    text: str
    hints: list[str]
    received_hints: tuple[str, ...]
    concurrent: tuple["BatchCall", ...] = field(default=(), repr=False)
    released: asyncio.Event = field(default_factory=asyncio.Event)
    completed: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: bool = False


class GatedRunner:
    """Hold each run until the test permits its outcome to reach the pipeline."""

    def __init__(self) -> None:
        self.calls: list[BatchCall] = []
        self.changed = asyncio.Event()
        self.outcomes: dict[str, IngestBatchOutcome | Exception] = {}
        self.finish: Callable[[BatchCall], Awaitable[IngestBatchOutcome]] | None = None
        self.auto_release = False

    async def run(self, text: str, hints: list[str]) -> IngestBatchOutcome:
        call = BatchCall(
            text=text,
            hints=hints,
            received_hints=tuple(hints),
            concurrent=tuple(
                prior for prior in self.calls if not prior.completed.is_set()
            ),
        )
        self.calls.append(call)
        self.changed.set()
        if self.auto_release:
            call.released.set()
        try:
            await _wait_event(call.released)
            if self.finish is not None:
                return await self.finish(call)
            outcome = self.outcomes.get(text.strip())
            if isinstance(outcome, Exception):
                raise outcome
            return outcome or IngestBatchOutcome(completed=True, summary="stored")
        except asyncio.CancelledError:
            call.cancelled = True
            raise
        finally:
            call.completed.set()

    def release_all(self) -> None:
        self.auto_release = True
        for call in self.calls:
            call.released.set()


async def _wait_event(event: asyncio.Event) -> None:
    async with asyncio.timeout(WAIT_SECONDS):
        await event.wait()


async def _wait_for_calls(runner: GatedRunner, count: int) -> list[BatchCall]:
    async with asyncio.timeout(WAIT_SECONDS):
        while len(runner.calls) < count:
            runner.changed.clear()
            await runner.changed.wait()
    return runner.calls[:count]


async def _wait_for_activity(activity: ActivityRecorder, count: int) -> None:
    async with asyncio.timeout(WAIT_SECONDS):
        while activity.count < count:
            activity.changed.clear()
            await activity.changed.wait()


async def _wait_for_snapshot(
    pipeline: IngestionPipeline,
    condition: Callable[[PipelineSnapshot], bool],
) -> PipelineSnapshot:
    async with asyncio.timeout(WAIT_SECONDS):
        while True:
            snapshot = await pipeline.snapshot()
            if condition(snapshot):
                return snapshot
            await asyncio.sleep(0.001)


def _queue_size(snapshot: PipelineSnapshot) -> int:
    return snapshot.ready + snapshot.leased + snapshot.retry_wait + snapshot.paused


async def _queued_rows(pipeline: IngestionPipeline) -> list[dict]:
    rows = await pipeline.storage.search_intake_chunks("chunkmarker", k=100)
    return sorted(rows, key=lambda row: (row["intake_id"], row["chunk_index"]))


def _compact(text: str) -> str:
    return "".join(text.split())


def _paragraphs(document: str, count: int = 4) -> str:
    return "\n\n".join(
        f"Chunkmarker {document} section {index} contains distinct source evidence."
        for index in range(count)
    )


def _assert_source_batches(
    calls: list[BatchCall], rows: list[dict], budget: int
) -> list[list[dict]]:
    """Match runner inputs to whole, contiguous source chunks without delimiters."""
    remaining = sorted(rows, key=lambda row: row["chunk_index"])
    batches: list[list[dict]] = []
    for call in calls:
        assert 0 < len(call.text) <= budget
        text = _compact(call.text)
        batch: list[dict] = []
        while text:
            assert remaining, "a batch repeated source text or added non-source context"
            row = remaining.pop(0)
            content = _compact(row["content"])
            assert content
            assert text.startswith(content), (
                "a batch skipped or reordered a source chunk"
            )
            text = text[len(content) :]
            batch.append(row)
        assert batch
        batches.append(batch)
    assert remaining == [], "some source chunks never reached the runner"
    return batches


def _utc(value: str | datetime) -> datetime:
    timestamp = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    assert timestamp.tzinfo is not None
    assert timestamp.utcoffset() == timedelta(0)
    return timestamp


def _make_pipeline(
    storage: Storage,
    runner: GatedRunner,
    clock: MutableUtcClock,
    *,
    chunk_chars: int = 100,
    processing_batch_chars: int = 180,
    worker_concurrency: int = 1,
    retry_base_delay_seconds: float = 5,
    retry_max_delay_seconds: float = 20,
    activity_callback: Callable[[], None] | None = None,
) -> IngestionPipeline:
    return IngestionPipeline(
        storage=storage,
        runner=runner,
        clock=clock,
        max_request_chars=10_000,
        chunk_chars=chunk_chars,
        processing_batch_chars=processing_batch_chars,
        worker_concurrency=worker_concurrency,
        lease_seconds=60,
        poll_interval_seconds=0.001,
        retry_base_delay_seconds=retry_base_delay_seconds,
        retry_max_delay_seconds=retry_max_delay_seconds,
        activity_callback=activity_callback,
    )


@asynccontextmanager
async def _running(
    pipeline: IngestionPipeline, runner: GatedRunner
) -> AsyncIterator[None]:
    await asyncio.wait_for(pipeline.start(), timeout=WAIT_SECONDS)
    try:
        yield
    finally:
        runner.release_all()
        await asyncio.wait_for(pipeline.stop(), timeout=WAIT_SECONDS)


@pytest.fixture
def clock() -> MutableUtcClock:
    return MutableUtcClock()


@pytest.fixture
def embedder() -> RecordingEmbedder:
    return RecordingEmbedder()


@pytest.fixture
async def intake_storage(
    clock: MutableUtcClock, embedder: RecordingEmbedder
) -> AsyncIterator[Storage]:
    storage = Storage("mem://", embedder, dimensions=4, clock=clock)
    await storage.init()
    try:
        yield storage
    finally:
        await storage.close()


@pytest.fixture
def runner() -> GatedRunner:
    return GatedRunner()


@pytest.fixture
def pipeline(intake_storage, runner, clock) -> IngestionPipeline:
    return _make_pipeline(intake_storage, runner, clock)


PARAGRAPHS = (
    "Chunkmarker paragraph zero names a star. Its record stays in this source.",
    "Chunkmarker paragraph one names a lake. Its record stays in this source.",
    "Chunkmarker paragraph two names a grove. Its record stays in this source.",
)
SENTENCES = (
    "Chunkmarker sentence zero describes the riverbank.",
    "Chunkmarker sentence one describes the observatory.",
    "Chunkmarker sentence two describes the library.",
    "Chunkmarker sentence three describes the orchard.",
)
LONG_TEXT = "Chunkmarker" + "".join(f"{index:03d}" for index in range(90))


@pytest.mark.parametrize(
    ("text", "natural_units"),
    [
        ("\n\n".join(PARAGRAPHS), PARAGRAPHS),
        (" ".join(SENTENCES), SENTENCES),
        (LONG_TEXT, ()),
    ],
    ids=["paragraph-boundaries", "sentence-fallback", "overlong-unbroken-text"],
)
async def test_enqueue_creates_bounded_disjoint_searchable_source_chunks(
    pipeline, runner, embedder, text, natural_units
):
    request = IntakeRequest(text=text, hints=("entity:one", "note:two"), source="cli")

    result = await pipeline.enqueue(request)

    rows = await _queued_rows(pipeline)
    assert result.chunks_stored == len(rows)
    assert result.chunks_stored > 1
    assert len({row["id"] for row in rows}) == result.chunks_stored
    assert len({row["intake_id"] for row in rows}) == 1
    assert [row["chunk_index"] for row in rows] == list(range(result.chunks_stored))
    assert _compact("".join(row["content"] for row in rows)) == _compact(text)
    for row in rows:
        assert 0 < len(row["content"]) <= pipeline.chunk_chars
        assert row["total_chunks"] == result.chunks_stored
        assert row["source"] == request.source
        assert tuple(row["hints"]) == request.hints
        assert row["state"] == "ready"
        assert "embedding" not in row
        assert row["content"] in embedder.texts
    for unit in natural_units:
        assert sum(unit in row["content"] for row in rows) == 1
    if not natural_units:
        assert "".join(row["content"] for row in rows) == text
    assert runner.calls == []
    snapshot = await pipeline.snapshot()
    assert snapshot.ready == result.chunks_stored
    assert _queue_size(snapshot) == result.chunks_stored


@pytest.mark.parametrize(
    "intake_request",
    [
        IntakeRequest(text=""),
        IntakeRequest(text="   \n\t"),
        IntakeRequest(text="x" * 10_001),
    ],
    ids=["empty", "whitespace", "over-request-limit"],
)
async def test_enqueue_rejects_invalid_requests_before_embedding_or_persistence(
    pipeline, embedder, intake_request
):
    with pytest.raises(ValueError):
        await pipeline.enqueue(intake_request)

    assert embedder.texts == []
    assert _queue_size(await pipeline.snapshot()) == 0
    assert await _queued_rows(pipeline) == []


async def test_enqueue_waits_for_embedding_and_searchable_persistence(
    pipeline, runner, embedder
):
    embedder.released.clear()
    request = IntakeRequest(text=_paragraphs("synchronous", 3))
    enqueue = asyncio.create_task(pipeline.enqueue(request))
    embedding_started = asyncio.create_task(embedder.started.wait())
    try:
        async with asyncio.timeout(WAIT_SECONDS):
            done, _ = await asyncio.wait(
                {enqueue, embedding_started}, return_when=asyncio.FIRST_COMPLETED
            )
        if enqueue in done:
            await enqueue
            raise AssertionError("enqueue returned before embedding completed")
        assert not enqueue.done()
        assert runner.calls == []
        assert _queue_size(await pipeline.snapshot()) == 0
    finally:
        embedder.released.set()
        embedding_started.cancel()
        with suppress(asyncio.CancelledError):
            await embedding_started
        result = await asyncio.wait_for(enqueue, timeout=WAIT_SECONDS)

    rows = await _queued_rows(pipeline)
    assert result.chunks_stored == len(rows) > 0
    assert all(row["content"] in embedder.texts for row in rows)
    assert _compact("".join(row["content"] for row in rows)) == _compact(request.text)
    assert runner.calls == []


async def test_enqueue_embedding_failure_leaves_no_partial_intake(pipeline, embedder):
    embedder.fail_after = 1
    try:
        with pytest.raises(RuntimeError, match="embedding"):
            await pipeline.enqueue(IntakeRequest(text=_paragraphs("failure", 3)))
    finally:
        embedder.fail_after = None

    assert _queue_size(await pipeline.snapshot()) == 0
    assert await _queued_rows(pipeline) == []


async def test_idempotency_key_collapses_duplicate_requests_while_queued(pipeline):
    request = IntakeRequest(
        text="Chunkmarker duplicate source", idempotency_key="req-1"
    )

    first = await pipeline.enqueue(request)
    before = await _queued_rows(pipeline)
    duplicate = await pipeline.enqueue(request)

    assert first.chunks_stored == len(before) > 0
    assert duplicate.chunks_stored == 0
    after = await _queued_rows(pipeline)
    assert {row["id"] for row in after} == {row["id"] for row in before}
    assert _queue_size(await pipeline.snapshot()) == first.chunks_stored


async def test_concurrent_idempotent_requests_stage_one_intake(pipeline):
    request = IntakeRequest(text=_paragraphs("duplicate", 3), idempotency_key="req-1")

    async with asyncio.timeout(WAIT_SECONDS):
        results = await asyncio.gather(
            pipeline.enqueue(request), pipeline.enqueue(request)
        )

    rows = await _queued_rows(pipeline)
    counts = sorted(result.chunks_stored for result in results)
    assert counts == [0, len(rows)]
    assert len(rows) > 0
    assert len({row["intake_id"] for row in rows}) == 1
    assert _queue_size(await pipeline.snapshot()) == len(rows)


async def test_idempotency_key_collapses_duplicate_when_every_chunk_is_in_flight(
    pipeline, runner
):
    request = IntakeRequest(
        text="Chunkmarker in-flight source", idempotency_key="req-1"
    )
    first = await pipeline.enqueue(request)
    before = await _queued_rows(pipeline)

    async with _running(pipeline, runner):
        [call] = await _wait_for_calls(runner, 1)
        running = await pipeline.snapshot()
        assert not call.completed.is_set()
        assert running.ready == 0
        assert running.leased == first.chunks_stored

        duplicate = await pipeline.enqueue(request)

        assert duplicate.chunks_stored == 0
        after = await _queued_rows(pipeline)
        assert {row["id"] for row in after} == {row["id"] for row in before}
        assert all(row["state"] == "leased" for row in after)
        assert _queue_size(await pipeline.snapshot()) == first.chunks_stored
        call.released.set()
        await _wait_event(call.completed)
        await _wait_for_snapshot(pipeline, lambda snapshot: _queue_size(snapshot) == 0)


async def test_same_idempotency_key_is_new_only_after_final_chunk_deletion(
    intake_storage, runner, clock
):
    pipeline = _make_pipeline(intake_storage, runner, clock, processing_batch_chars=100)
    request = IntakeRequest(text=_paragraphs("reusable", 3), idempotency_key="req-1")
    first = await pipeline.enqueue(request)
    original_ids = {row["intake_id"] for row in await _queued_rows(pipeline)}

    async with _running(pipeline, runner):
        [first_call] = await _wait_for_calls(runner, 1)
        first_call.released.set()
        await _wait_event(first_call.completed)
        calls = await _wait_for_calls(runner, 2)
        assert not calls[1].completed.is_set()
        remaining = await pipeline.snapshot()
        assert 0 < _queue_size(remaining) < first.chunks_stored
        assert (await pipeline.enqueue(request)).chunks_stored == 0

        runner.release_all()
        await _wait_for_snapshot(pipeline, lambda snapshot: _queue_size(snapshot) == 0)

    assert await _queued_rows(pipeline) == []
    second = await pipeline.enqueue(request)
    assert second.chunks_stored == first.chunks_stored
    new_ids = {row["intake_id"] for row in await _queued_rows(pipeline)}
    assert original_ids.isdisjoint(new_ids)


async def test_worker_packs_whole_contiguous_chunks_in_source_order(
    intake_storage, runner, clock
):
    pipeline = _make_pipeline(intake_storage, runner, clock, chunk_chars=70)
    request = IntakeRequest(text=_paragraphs("packing", 4), hints=("entity:one",))
    await pipeline.enqueue(request)
    rows = await _queued_rows(pipeline)

    async with _running(pipeline, runner):
        await _wait_for_calls(runner, 1)
        runner.release_all()
        await _wait_for_snapshot(pipeline, lambda snapshot: _queue_size(snapshot) == 0)

    batches = _assert_source_batches(
        runner.calls, rows, pipeline.processing_batch_chars
    )
    assert len(batches) > 1
    assert any(len(batch) > 1 for batch in batches)
    assert all(call.received_hints == request.hints for call in runner.calls)
    assert all(call.completed.is_set() and not call.cancelled for call in runner.calls)


async def test_processing_batches_receive_independent_text_and_hint_state(
    intake_storage, runner, clock
):
    pipeline = _make_pipeline(intake_storage, runner, clock, processing_batch_chars=100)
    request = IntakeRequest(text=_paragraphs("independent", 4), hints=("entity:one",))
    await pipeline.enqueue(request)
    rows = await _queued_rows(pipeline)

    async def finish(call: BatchCall) -> IngestBatchOutcome:
        call.hints.append("prior-batch-only")
        return IngestBatchOutcome(completed=True, summary="prior-batch-summary")

    runner.finish = finish
    async with _running(pipeline, runner):
        [first] = await _wait_for_calls(runner, 1)
        first.released.set()
        await _wait_event(first.completed)
        calls = await _wait_for_calls(runner, 2)
        assert calls[1].received_hints == request.hints
        assert "prior-batch-summary" not in calls[1].text
        runner.release_all()
        await _wait_for_snapshot(pipeline, lambda snapshot: _queue_size(snapshot) == 0)

    assert len(runner.calls) > 1
    _assert_source_batches(runner.calls, rows, pipeline.processing_batch_chars)
    assert all(call.received_hints == request.hints for call in runner.calls)
    assert request.hints == ("entity:one",)


async def test_success_deletes_chunks_only_after_clean_runner_completion(
    pipeline, runner
):
    request = IntakeRequest(text="Chunkmarker clean batch")
    staged = await pipeline.enqueue(request)
    rows = await _queued_rows(pipeline)

    async with _running(pipeline, runner):
        [call] = await _wait_for_calls(runner, 1)
        running = await pipeline.snapshot()
        assert not call.completed.is_set()
        assert running.leased == staged.chunks_stored
        assert running.active_leases == 1
        in_flight = await _queued_rows(pipeline)
        assert {row["id"] for row in in_flight} == {row["id"] for row in rows}
        assert all(row["state"] == "leased" for row in in_flight)

        call.released.set()
        await _wait_event(call.completed)
        final = await _wait_for_snapshot(
            pipeline, lambda snapshot: _queue_size(snapshot) == 0
        )
        assert final.active_leases == 0
        assert await _queued_rows(pipeline) == []


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        (
            IngestBatchOutcome(completed=False, errors=["provider timeout"]),
            "provider timeout",
        ),
        (IngestBatchOutcome(completed=True, errors=["write failed"]), "write failed"),
        (RuntimeError("runner raised"), "runner raised"),
        (IngestBatchOutcome(completed=False), None),
    ],
    ids=[
        "incomplete-with-errors",
        "completed-with-errors",
        "runner-exception",
        "incomplete",
    ],
)
async def test_unclean_runs_keep_searchable_chunks_and_report_retry_errors(
    pipeline, runner, failure, expected_error
):
    request = IntakeRequest(text="Chunkmarker failing batch")
    runner.outcomes[request.text] = failure
    staged = await pipeline.enqueue(request)
    before = await _queued_rows(pipeline)
    intake_id = before[0]["intake_id"]

    async with _running(pipeline, runner):
        [call] = await _wait_for_calls(runner, 1)
        assert not call.completed.is_set()
        assert (await pipeline.snapshot()).leased == staged.chunks_stored
        call.released.set()
        await _wait_event(call.completed)
        failed = await _wait_for_snapshot(
            pipeline,
            lambda snapshot: (
                snapshot.retry_wait == staged.chunks_stored and snapshot.leased == 0
            ),
        )
        assert failed.ready == 0
        assert failed.active_leases == 0
        assert failed.recent_errors
        errors = [
            error for error in failed.recent_errors if error["intake_id"] == intake_id
        ]
        assert errors
        assert all(error["error"] for error in errors)
        if expected_error is not None:
            assert any(expected_error in error["error"] for error in errors)
        after = await _queued_rows(pipeline)
        assert {row["id"] for row in after} == {row["id"] for row in before}
        assert all(row["state"] == "retry_wait" for row in after)
        assert len(runner.calls) == 1


async def test_retry_delays_double_and_remain_at_the_configured_cap(
    intake_storage, runner, clock
):
    pipeline = _make_pipeline(
        intake_storage,
        runner,
        clock,
        retry_base_delay_seconds=2,
        retry_max_delay_seconds=5,
    )
    request = IntakeRequest(text="Chunkmarker exponential retry")
    runner.outcomes[request.text] = IngestBatchOutcome(
        completed=False, errors=["retry me"]
    )
    staged = await pipeline.enqueue(request)

    async with _running(pipeline, runner):
        for attempt, delay in enumerate((2, 4, 5, 5), start=1):
            calls = await _wait_for_calls(runner, attempt)
            call = calls[-1]
            assert not call.completed.is_set()
            failed_at = clock()
            call.released.set()
            await _wait_event(call.completed)
            await _wait_for_snapshot(
                pipeline,
                lambda snapshot: (
                    snapshot.retry_wait == staged.chunks_stored and snapshot.leased == 0
                ),
            )
            rows = await _queued_rows(pipeline)
            assert all(row["attempt_count"] == attempt for row in rows)
            retry_at = {_utc(row["next_attempt_at"]) for row in rows}
            assert retry_at == {failed_at + timedelta(seconds=delay)}
            assert len(runner.calls) == attempt
            if attempt < 4:
                clock.advance(delay - 0.001)
                assert await intake_storage.claim_intake_batch("probe", 180, 60) is None
                assert len(runner.calls) == attempt
                clock.advance(0.001)


async def test_ready_intake_runs_while_another_intake_waits_for_retry(pipeline, runner):
    failing = IntakeRequest(text="Chunkmarker poisoned source")
    healthy = IntakeRequest(text="Chunkmarker healthy source")
    runner.outcomes[failing.text] = IngestBatchOutcome(
        completed=False, errors=["bad intake"]
    )
    failed_count = (await pipeline.enqueue(failing)).chunks_stored
    failed_id = (await _queued_rows(pipeline))[0]["intake_id"]

    async with _running(pipeline, runner):
        [failed_call] = await _wait_for_calls(runner, 1)
        failed_call.released.set()
        await _wait_event(failed_call.completed)
        await _wait_for_snapshot(
            pipeline, lambda snapshot: snapshot.retry_wait == failed_count
        )

        healthy_count = (await pipeline.enqueue(healthy)).chunks_stored
        calls = await _wait_for_calls(runner, 2)
        healthy_call = next(call for call in calls if call.text.strip() == healthy.text)
        assert not healthy_call.completed.is_set()
        working = await pipeline.snapshot()
        assert working.retry_wait == failed_count
        assert working.leased == healthy_count
        healthy_call.released.set()
        await _wait_event(healthy_call.completed)
        await _wait_for_snapshot(
            pipeline,
            lambda snapshot: (
                snapshot.retry_wait == failed_count
                and snapshot.ready == 0
                and snapshot.leased == 0
            ),
        )
        assert {row["intake_id"] for row in await _queued_rows(pipeline)} == {failed_id}
        assert {call.text.strip() for call in runner.calls} == {
            failing.text,
            healthy.text,
        }


async def test_different_intakes_run_concurrently_without_overlapping_one_intake(
    intake_storage, runner, clock
):
    pipeline = _make_pipeline(
        intake_storage, runner, clock, worker_concurrency=2, processing_batch_chars=100
    )
    alpha = IntakeRequest(text=_paragraphs("alpha", 4), source="alpha")
    beta = IntakeRequest(
        text="Chunkmarker beta source completes independently.", source="beta"
    )
    await pipeline.enqueue(alpha)
    await pipeline.enqueue(beta)
    rows = await _queued_rows(pipeline)
    alpha_rows = [row for row in rows if row["source"] == "alpha"]
    beta_rows = [row for row in rows if row["source"] == "beta"]

    async with _running(pipeline, runner):
        calls = await _wait_for_calls(runner, 2)
        assert all(not call.completed.is_set() for call in calls)
        assert sum("alpha" in call.text for call in calls) == 1
        assert sum("beta" in call.text for call in calls) == 1
        working = await pipeline.snapshot()
        assert working.worker_count == 2
        assert working.active_leases == 2
        assert working.ready > 0
        beta_call = next(call for call in calls if "beta" in call.text)
        alpha_call = next(call for call in calls if "alpha" in call.text)
        beta_call.released.set()
        await _wait_event(beta_call.completed)
        await _wait_for_snapshot(pipeline, lambda snapshot: snapshot.active_leases == 1)
        assert not alpha_call.completed.is_set()
        clock.read.clear()
        await _wait_event(clock.read)
        assert len(runner.calls) == 2
        runner.release_all()
        await _wait_for_snapshot(pipeline, lambda snapshot: _queue_size(snapshot) == 0)

    alpha_calls = [call for call in runner.calls if "alpha" in call.text]
    beta_calls = [call for call in runner.calls if "beta" in call.text]
    assert any(call.concurrent for call in runner.calls)
    for call in runner.calls:
        for concurrent in call.concurrent:
            assert ("alpha" in call.text) != ("alpha" in concurrent.text)
    _assert_source_batches(alpha_calls, alpha_rows, pipeline.processing_batch_chars)
    _assert_source_batches(beta_calls, beta_rows, pipeline.processing_batch_chars)


@pytest.mark.parametrize("state", ["ready", "retry_wait"])
async def test_pause_and_resume_change_only_the_selected_intake(
    pipeline, runner, state
):
    selected = IntakeRequest(text="Chunkmarker selected intake", source="selected")
    other = IntakeRequest(text="Chunkmarker unrelated intake", source="other")
    selected_count = (await pipeline.enqueue(selected)).chunks_stored
    selected_id = (await _queued_rows(pipeline))[0]["intake_id"]
    if state == "retry_wait":
        runner.outcomes[selected.text] = IngestBatchOutcome(
            completed=False, errors=["paused retry"]
        )
        async with _running(pipeline, runner):
            [call] = await _wait_for_calls(runner, 1)
            call.released.set()
            await _wait_event(call.completed)
            await _wait_for_snapshot(
                pipeline, lambda snapshot: snapshot.retry_wait == selected_count
            )
    other_count = (await pipeline.enqueue(other)).chunks_stored
    other_rows = [
        row for row in await _queued_rows(pipeline) if row["source"] == "other"
    ]

    await pipeline.pause_intake(selected_id)

    paused = await pipeline.snapshot()
    assert paused.paused == selected_count
    assert paused.ready == other_count
    assert paused.retry_wait == 0
    rows = await _queued_rows(pipeline)
    assert all(
        row["state"] == "paused" for row in rows if row["intake_id"] == selected_id
    )
    assert {row["id"] for row in rows if row["source"] == "other"} == {
        row["id"] for row in other_rows
    }
    assert all(row["state"] == "ready" for row in rows if row["source"] == "other")

    await pipeline.resume_intake(selected_id)

    resumed = await pipeline.snapshot()
    assert resumed.paused == 0
    assert resumed.retry_wait == 0
    assert resumed.ready == selected_count + other_count
    assert all(row["state"] == "ready" for row in await _queued_rows(pipeline))


async def test_discard_removes_remaining_chunks_but_retains_processed_graph_records(
    intake_storage, runner, clock
):
    pipeline = _make_pipeline(intake_storage, runner, clock, processing_batch_chars=100)
    request = IntakeRequest(text=_paragraphs("discard", 4), source="selected")
    stored = await pipeline.enqueue(request)
    intake_id = (await _queued_rows(pipeline))[0]["intake_id"]
    graph: list[dict] = []

    async def store_graph(call: BatchCall) -> IngestBatchOutcome:
        note = await intake_storage.create_note(call.text, source="organized")
        entity = await intake_storage.create_entity("Retained knowledge", "concept")
        edge = await intake_storage.create_edge(note["id"], "references", entity["id"])
        graph.extend([note, entity, edge])
        return IngestBatchOutcome(completed=True)

    runner.finish = store_graph
    async with _running(pipeline, runner):
        [call] = await _wait_for_calls(runner, 1)
        await pipeline.pause_intake(intake_id)
        assert (await pipeline.snapshot()).paused > 0
        call.released.set()
        await _wait_event(call.completed)
        await _wait_for_snapshot(
            pipeline, lambda snapshot: snapshot.leased == 0 and snapshot.paused > 0
        )

    remaining = await _queued_rows(pipeline)
    assert 0 < len(remaining) < stored.chunks_stored
    assert len(graph) == 3
    note, entity, edge = graph
    note_before = await intake_storage.get_node(note["id"])
    entity_before = await intake_storage.get_node(entity["id"])
    edge_before = await intake_storage.get_edge(edge["id"])
    assert note_before and entity_before and edge_before
    other_count = (
        await pipeline.enqueue(
            IntakeRequest(text="Chunkmarker keep this intake", source="other")
        )
    ).chunks_stored
    other_rows = [
        row for row in await _queued_rows(pipeline) if row["source"] == "other"
    ]

    discarded = await pipeline.discard_intake(intake_id)

    assert discarded == len(remaining)
    final = await pipeline.snapshot()
    assert final.ready == other_count
    assert final.leased == 0
    assert final.retry_wait == 0
    assert final.paused == 0
    after = await _queued_rows(pipeline)
    assert {row["id"] for row in after} == {row["id"] for row in other_rows}
    assert await intake_storage.get_node(note["id"]) == note_before
    assert await intake_storage.get_node(entity["id"]) == entity_before
    assert await intake_storage.get_edge(edge["id"]) == edge_before


async def test_snapshot_reports_live_leases_workers_and_identified_stuck_work(
    pipeline, runner
):
    request = IntakeRequest(text="Chunkmarker visible failure")
    staged = await pipeline.enqueue(request)
    intake_id = (await _queued_rows(pipeline))[0]["intake_id"]
    runner.outcomes[request.text] = IngestBatchOutcome(
        completed=False, errors=["visible error"]
    )

    async with _running(pipeline, runner):
        [call] = await _wait_for_calls(runner, 1)
        snapshot = await pipeline.snapshot()
        assert isinstance(snapshot, PipelineSnapshot)
        assert snapshot.worker_count == pipeline.worker_concurrency
        assert snapshot.active_leases == 1
        assert snapshot.leased == staged.chunks_stored
        assert snapshot.stuck_intakes == []
        call.released.set()
        await _wait_event(call.completed)
        failed = await _wait_for_snapshot(
            pipeline, lambda snapshot: snapshot.retry_wait > 0
        )
        assert failed.worker_count == pipeline.worker_concurrency
        assert failed.active_leases == 0
        assert failed.oldest_retry_at is not None
        assert 0 < len(failed.stuck_intakes) <= 100
        assert any(item["intake_id"] == intake_id for item in failed.stuck_intakes)
        assert any(
            error["intake_id"] == intake_id and "visible error" in error["error"]
            for error in failed.recent_errors
        )

    stopped = await pipeline.snapshot()
    assert stopped.worker_count == 0
    assert stopped.active_leases == 0
    assert stopped.retry_wait == staged.chunks_stored


async def test_stop_waits_for_inflight_completion_without_claiming_more_work(
    intake_storage, runner, clock
):
    pipeline = _make_pipeline(intake_storage, runner, clock, processing_batch_chars=100)
    staged = await pipeline.enqueue(IntakeRequest(text=_paragraphs("shutdown", 4)))
    await asyncio.wait_for(pipeline.start(), timeout=WAIT_SECONDS)
    stopping: asyncio.Task[None] | None = None
    stop_entered = asyncio.Event()

    async def stop_pipeline() -> None:
        stop_entered.set()
        await pipeline.stop()

    try:
        [call] = await _wait_for_calls(runner, 1)
        before = await pipeline.snapshot()
        assert before.leased > 0
        assert before.ready > 0
        stopping = asyncio.create_task(stop_pipeline())
        await _wait_event(stop_entered)
        assert not stopping.done()
        assert not call.completed.is_set()
        assert (await pipeline.snapshot()).leased == before.leased

        call.released.set()
        await _wait_event(call.completed)
        await asyncio.wait_for(asyncio.shield(stopping), timeout=WAIT_SECONDS)
    finally:
        runner.release_all()
        if stopping is None:
            await asyncio.wait_for(pipeline.stop(), timeout=WAIT_SECONDS)
        else:
            await asyncio.wait_for(asyncio.shield(stopping), timeout=WAIT_SECONDS)

    assert not call.cancelled
    assert runner.calls == [call]
    final = await pipeline.snapshot()
    assert final.worker_count == 0
    assert final.active_leases == 0
    assert final.leased == 0
    assert final.ready == staged.chunks_stored - before.leased > 0
    assert _queue_size(final) == len(await _queued_rows(pipeline))


async def test_activity_callback_marks_batch_start_and_clean_completion(
    intake_storage, runner, clock
):
    activity = ActivityRecorder()
    pipeline = _make_pipeline(intake_storage, runner, clock, activity_callback=activity)
    await pipeline.enqueue(IntakeRequest(text="Chunkmarker touch scheduler"))
    assert activity.count == 0

    async with _running(pipeline, runner):
        [call] = await _wait_for_calls(runner, 1)
        assert not call.completed.is_set()
        assert activity.count == 1
        call.released.set()
        await _wait_event(call.completed)
        await _wait_for_snapshot(pipeline, lambda snapshot: _queue_size(snapshot) == 0)
        await _wait_for_activity(activity, 2)
        assert activity.count == 2

    assert activity.count == 2


async def test_retry_backoff_emits_no_activity_until_the_next_batch_starts(
    intake_storage, runner, clock
):
    activity = ActivityRecorder()
    pipeline = _make_pipeline(intake_storage, runner, clock, activity_callback=activity)
    request = IntakeRequest(text="Chunkmarker delayed retry activity")
    runner.outcomes[request.text] = IngestBatchOutcome(
        completed=False, errors=["try later"]
    )
    await pipeline.enqueue(request)

    async with _running(pipeline, runner):
        [first] = await _wait_for_calls(runner, 1)
        assert activity.count == 1
        first.released.set()
        await _wait_event(first.completed)
        await _wait_for_snapshot(pipeline, lambda snapshot: snapshot.retry_wait > 0)
        await _wait_for_activity(activity, 2)
        assert activity.count == 2

        clock.advance(pipeline.retry_base_delay_seconds - 1)
        clock.read.clear()
        await _wait_event(clock.read)
        waiting = await pipeline.snapshot()
        assert waiting.retry_wait > 0
        assert waiting.active_leases == 0
        assert len(runner.calls) == 1
        assert activity.count == 2

        runner.outcomes.pop(request.text)
        clock.advance(1)
        calls = await _wait_for_calls(runner, 2)
        assert not calls[1].completed.is_set()
        assert activity.count == 3
        calls[1].released.set()
        await _wait_event(calls[1].completed)
        await _wait_for_snapshot(pipeline, lambda snapshot: _queue_size(snapshot) == 0)
        await _wait_for_activity(activity, 4)
        assert activity.count == 4

    assert activity.count == 4
