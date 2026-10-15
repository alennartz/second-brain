"""Behavioral contracts for intake persistence, leases, and search candidates."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from second_brain.db import Storage
from second_brain.models import (
    IntakeChunkDraft,
    IntakeQueueSnapshot,
    MemorySearchCandidates,
    RankedSearchCandidates,
)


@dataclass
class MutableUtcClock:
    current: datetime = datetime(2026, 10, 15, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


class CountingEmbedder:
    """Count embedding requests without imposing a vector ranking."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.texts.append(text)
        return [1.0, 0.0, 0.0, 0.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(text) for text in texts]


class FailingEmbedder:
    """Fail after embedding the first document chunk."""

    async def embed(self, text: str) -> list[float]:
        if text == "second paragraph":
            raise RuntimeError("embedding provider failed")
        return [1.0, 0.0, 0.0, 0.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(text) for text in texts]


@pytest.fixture
def clock() -> MutableUtcClock:
    return MutableUtcClock()


@pytest.fixture
def embedder() -> CountingEmbedder:
    return CountingEmbedder()


@pytest.fixture
async def intake_storage(
    clock: MutableUtcClock, embedder: CountingEmbedder
) -> AsyncIterator[Storage]:
    storage = Storage("mem://", embedder, dimensions=4, clock=clock)
    await storage.init()
    try:
        yield storage
    finally:
        await storage.close()


def _drafts() -> list[IntakeChunkDraft]:
    return [
        IntakeChunkDraft(
            chunk_index=0,
            total_chunks=2,
            content="first paragraph",
            source="cli",
            hints=("entity:one",),
        ),
        IntakeChunkDraft(
            chunk_index=1,
            total_chunks=2,
            content="second paragraph",
            source="cli",
            hints=("entity:one",),
        ),
    ]


async def test_create_intake_chunks_persists_every_chunk_and_returns_count(
    intake_storage: Storage,
):
    drafts = _drafts()
    count = await intake_storage.create_intake_chunks("intake-1", drafts, None)

    assert count == 2
    queued = await intake_storage.search_intake_chunks("paragraph", k=5)
    assert {chunk["chunk_index"] for chunk in queued} == {0, 1}
    assert len({chunk["id"] for chunk in queued}) == 2
    for chunk in queued:
        draft = drafts[chunk["chunk_index"]]
        assert chunk["intake_id"] == "intake-1"
        assert chunk["total_chunks"] == 2
        assert chunk["content"] == draft.content
        assert chunk["source"] == "cli"
        assert tuple(chunk["hints"]) == ("entity:one",)
        assert "embedding" not in chunk


async def test_create_intake_chunks_is_all_or_nothing_when_embedding_fails(
    clock: MutableUtcClock,
):
    storage = Storage("mem://", FailingEmbedder(), dimensions=4, clock=clock)
    await storage.init()
    try:
        with pytest.raises(RuntimeError, match="embedding"):
            await storage.create_intake_chunks("intake-1", _drafts(), None)

        snapshot = await storage.intake_queue_snapshot()
        assert snapshot.ready == 0
        assert snapshot.leased == 0
        assert snapshot.retry_wait == 0
        assert snapshot.paused == 0
        assert await storage.search_intake_chunks("paragraph", k=5) == []
    finally:
        await storage.close()


async def test_idempotency_key_collapses_only_rows_still_in_queue(
    intake_storage: Storage,
):
    drafts = _drafts()
    first = await intake_storage.create_intake_chunks("intake-1", drafts, "request-1")
    duplicate = await intake_storage.create_intake_chunks(
        "intake-2", drafts, "request-1"
    )
    assert first == 2
    assert duplicate == 0
    queued = await intake_storage.search_intake_chunks("paragraph", k=5)
    assert {chunk["intake_id"] for chunk in queued} == {"intake-1"}

    claimed = await intake_storage.claim_intake_batch(
        worker_id="worker-1", max_chars=1000, lease_seconds=60
    )
    assert claimed is not None
    assert await intake_storage.delete_intake_batch(claimed.lease_token) == 2

    accepted_after_delete = await intake_storage.create_intake_chunks(
        "intake-3", drafts, "request-1"
    )
    assert accepted_after_delete == 2
    queued = await intake_storage.search_intake_chunks("paragraph", k=5)
    assert {chunk["intake_id"] for chunk in queued} == {"intake-3"}


async def test_idempotency_key_protects_inflight_and_partially_processed_intake(
    intake_storage: Storage,
):
    drafts = _drafts()
    await intake_storage.create_intake_chunks("intake-1", drafts, "request-1")
    claimed = await intake_storage.claim_intake_batch(
        worker_id="worker-1", max_chars=len(drafts[0].content), lease_seconds=60
    )
    assert claimed is not None

    assert (
        await intake_storage.create_intake_chunks("intake-2", drafts, "request-1") == 0
    )
    snapshot = await intake_storage.intake_queue_snapshot()
    assert snapshot.leased == 1
    assert snapshot.ready == 1

    assert await intake_storage.delete_intake_batch(claimed.lease_token) == 1
    assert (
        await intake_storage.create_intake_chunks("intake-3", drafts, "request-1") == 0
    )
    remaining = await intake_storage.claim_intake_batch(
        worker_id="worker-2", max_chars=1000, lease_seconds=60
    )
    assert remaining is not None
    assert [chunk["chunk_index"] for chunk in remaining.chunks] == [1]
    assert await intake_storage.delete_intake_batch(remaining.lease_token) == 1
    assert (
        await intake_storage.create_intake_chunks("intake-4", drafts, "request-1") == 2
    )


async def test_idempotency_key_collapses_duplicates_when_every_row_is_leased(
    intake_storage: Storage,
):
    await intake_storage.create_intake_chunks("intake-1", _drafts(), "request-1")
    claimed = await intake_storage.claim_intake_batch(
        worker_id="worker-1", max_chars=1000, lease_seconds=60
    )
    assert claimed is not None

    duplicate = await intake_storage.create_intake_chunks(
        "intake-2", _drafts(), "request-1"
    )

    assert duplicate == 0
    snapshot = await intake_storage.intake_queue_snapshot()
    assert snapshot.ready == 0
    assert snapshot.leased == 2


async def test_concurrent_idempotent_staging_stores_one_intake(
    intake_storage: Storage,
):
    counts = await asyncio.gather(
        intake_storage.create_intake_chunks("intake-1", _drafts(), "request-1"),
        intake_storage.create_intake_chunks("intake-2", _drafts(), "request-1"),
    )

    assert sorted(counts) == [0, 2]
    queued = await intake_storage.search_intake_chunks("paragraph", k=5)
    assert len(queued) == 2
    assert len({chunk["intake_id"] for chunk in queued}) == 1


async def test_claim_returns_contiguous_chunks_with_a_lease(
    intake_storage: Storage, clock: MutableUtcClock
):
    await intake_storage.create_intake_chunks("intake-1", _drafts(), None)

    claimed = await intake_storage.claim_intake_batch(
        worker_id="worker-1", max_chars=len("first paragraph"), lease_seconds=30
    )

    assert claimed is not None
    assert claimed.lease_token
    assert claimed.intake_id == "intake-1"
    assert [chunk["chunk_index"] for chunk in claimed.chunks] == [0]
    for chunk in claimed.chunks:
        assert chunk["state"] == "leased"
        assert chunk["lease_token"] == claimed.lease_token
        expiry = datetime.fromisoformat(chunk["lease_expires_at"])
        assert expiry == clock() + timedelta(seconds=30)


async def test_concurrent_claims_cannot_lease_two_batches_from_one_intake(
    intake_storage: Storage,
):
    await intake_storage.create_intake_chunks("intake-1", _drafts(), None)

    claims = await asyncio.gather(
        intake_storage.claim_intake_batch("worker-1", len("first paragraph"), 60),
        intake_storage.claim_intake_batch("worker-2", len("first paragraph"), 60),
    )

    claimed = [claim for claim in claims if claim is not None]
    assert len(claimed) == 1
    assert [chunk["chunk_index"] for chunk in claimed[0].chunks] == [0]
    assert await intake_storage.claim_intake_batch("worker-3", 1000, 60) is None
    snapshot = await intake_storage.intake_queue_snapshot()
    assert snapshot.ready == 1
    assert snapshot.leased == 1
    assert snapshot.active_leases == 1


async def test_concurrent_claims_can_lease_different_intakes(
    intake_storage: Storage,
):
    await intake_storage.create_intake_chunks("intake-1", _drafts(), None)
    await intake_storage.create_intake_chunks("intake-2", _drafts(), None)

    claims = await asyncio.gather(
        intake_storage.claim_intake_batch("worker-1", len("first paragraph"), 60),
        intake_storage.claim_intake_batch("worker-2", len("first paragraph"), 60),
    )

    assert all(claim is not None for claim in claims)
    claimed = [claim for claim in claims if claim is not None]
    assert {claim.intake_id for claim in claimed} == {"intake-1", "intake-2"}
    assert len({claim.lease_token for claim in claimed}) == 2
    assert all(
        [chunk["chunk_index"] for chunk in claim.chunks] == [0] for claim in claimed
    )


async def test_claim_replays_only_after_the_injected_clock_passes_lease_expiry(
    intake_storage: Storage, clock: MutableUtcClock
):
    await intake_storage.create_intake_chunks("intake-1", _drafts(), None)
    first = await intake_storage.claim_intake_batch("worker-1", 1000, 30)
    assert first is not None
    assert await intake_storage.claim_intake_batch("worker-2", 1000, 60) is None

    clock.advance(29)
    assert await intake_storage.claim_intake_batch("worker-2", 1000, 60) is None
    clock.advance(2)
    replay = await intake_storage.claim_intake_batch("worker-2", 1000, 60)

    assert replay is not None
    assert replay.lease_token != first.lease_token
    assert replay.intake_id == first.intake_id
    assert {chunk["id"] for chunk in replay.chunks} == {
        chunk["id"] for chunk in first.chunks
    }


@pytest.mark.parametrize("stale_operation", ["delete", "release"])
async def test_stale_lease_cannot_delete_or_release_reclaimed_rows(
    intake_storage: Storage, clock: MutableUtcClock, stale_operation: str
):
    await intake_storage.create_intake_chunks("intake-1", _drafts(), None)
    expired = await intake_storage.claim_intake_batch("worker-1", 1000, 30)
    assert expired is not None
    clock.advance(31)
    replay = await intake_storage.claim_intake_batch("worker-2", 1000, 60)
    assert replay is not None
    assert replay.lease_token != expired.lease_token

    if stale_operation == "delete":
        assert await intake_storage.delete_intake_batch(expired.lease_token) == 0
    else:
        await intake_storage.release_intake_batch(
            expired.lease_token, "stale failure", clock() + timedelta(seconds=30)
        )

    snapshot = await intake_storage.intake_queue_snapshot()
    assert snapshot.leased == 2
    assert snapshot.ready == 0
    assert snapshot.retry_wait == 0
    assert snapshot.active_leases == 1
    rows = await intake_storage.get_intake_chunks(
        [chunk["id"] for chunk in replay.chunks]
    )
    assert len(rows) == 2
    assert all(row["lease_token"] == replay.lease_token for row in rows)
    assert all(row.get("last_error") != "stale failure" for row in rows)
    assert await intake_storage.delete_intake_batch(replay.lease_token) == 2


async def test_release_returns_batch_to_retry_wait_until_the_injected_retry_time(
    intake_storage: Storage, clock: MutableUtcClock
):
    await intake_storage.create_intake_chunks("intake-1", _drafts(), None)
    claimed = await intake_storage.claim_intake_batch("worker-1", 1000, 60)
    assert claimed is not None
    retry_at = clock() + timedelta(seconds=5)

    await intake_storage.release_intake_batch(
        claimed.lease_token, error="agent failed", next_attempt_at=retry_at
    )

    snapshot = await intake_storage.intake_queue_snapshot()
    assert snapshot.leased == 0
    assert snapshot.retry_wait == 2
    assert snapshot.recent_errors[-1]["error"] == "agent failed"
    assert snapshot.recent_errors[-1]["intake_id"] == "intake-1"
    assert await intake_storage.claim_intake_batch("worker-2", 1000, 60) is None
    clock.advance(4)
    assert await intake_storage.claim_intake_batch("worker-2", 1000, 60) is None
    clock.advance(2)
    retried = await intake_storage.claim_intake_batch("worker-2", 1000, 60)
    assert retried is not None
    assert retried.lease_token != claimed.lease_token
    assert {chunk["id"] for chunk in retried.chunks} == {
        chunk["id"] for chunk in claimed.chunks
    }


async def test_claim_cannot_skip_a_retrying_leading_chunk(
    intake_storage: Storage, clock: MutableUtcClock
):
    await intake_storage.create_intake_chunks("intake-1", _drafts(), None)
    claimed = await intake_storage.claim_intake_batch(
        "worker-1", len("first paragraph"), 60
    )
    assert claimed is not None
    await intake_storage.release_intake_batch(
        claimed.lease_token, "agent failed", clock() + timedelta(seconds=5)
    )

    assert await intake_storage.claim_intake_batch("worker-2", 1000, 60) is None
    clock.advance(6)
    retried = await intake_storage.claim_intake_batch("worker-2", 1000, 60)
    assert retried is not None
    assert retried.chunks[0]["chunk_index"] == 0


async def test_delete_intake_batch_removes_only_its_lease_and_search_evidence(
    intake_storage: Storage,
):
    await intake_storage.create_intake_chunks("intake-1", _drafts(), None)
    await intake_storage.create_intake_chunks("intake-2", _drafts(), None)
    before = await intake_storage.search_intake_chunks("paragraph", k=10)
    claimed = await intake_storage.claim_intake_batch("worker-1", 1000, 60)
    assert claimed is not None
    deleted_ids = {chunk["id"] for chunk in claimed.chunks}
    remaining_ids = {chunk["id"] for chunk in before} - deleted_ids
    assert len(remaining_ids) == 2

    deleted = await intake_storage.delete_intake_batch(claimed.lease_token)

    assert deleted == 2
    assert await intake_storage.delete_intake_batch(claimed.lease_token) == 0
    snapshot = await intake_storage.intake_queue_snapshot()
    assert snapshot.ready == 2
    assert snapshot.leased == 0
    after = await intake_storage.search_intake_chunks("paragraph", k=10)
    assert {chunk["id"] for chunk in after} == remaining_ids
    candidates = await intake_storage.search_memory_candidates("paragraph", k=10)
    for path in (candidates.intake_chunk.bm25, candidates.intake_chunk.vector):
        assert {chunk["id"] for chunk in path} == remaining_ids


async def test_get_intake_chunks_skips_deleted_and_missing_rows_without_embeddings(
    intake_storage: Storage,
):
    await intake_storage.create_intake_chunks("intake-1", _drafts(), None)
    before = await intake_storage.search_intake_chunks("paragraph", k=5)
    claimed = await intake_storage.claim_intake_batch(
        "worker-1", len("first paragraph"), 60
    )
    assert claimed is not None
    deleted_ids = {chunk["id"] for chunk in claimed.chunks}
    remaining_ids = {chunk["id"] for chunk in before} - deleted_ids
    assert len(remaining_ids) == 1
    assert await intake_storage.delete_intake_batch(claimed.lease_token) == 1

    records = await intake_storage.get_intake_chunks(
        [chunk["id"] for chunk in before] + ["intake_chunk:missing"]
    )

    assert {record["id"] for record in records} == remaining_ids
    assert all("embedding" not in record for record in records)
    assert all(record["table"] == "intake_chunk" for record in records)


async def test_queue_snapshot_reports_counts_oldest_work_and_bounded_stuck_intakes(
    intake_storage: Storage,
):
    await intake_storage.create_intake_chunks("intake-1", _drafts(), None)
    snapshot = await intake_storage.intake_queue_snapshot()

    assert isinstance(snapshot, IntakeQueueSnapshot)
    assert snapshot.ready == 2
    assert snapshot.leased == 0
    assert snapshot.retry_wait == 0
    assert snapshot.paused == 0
    assert snapshot.oldest_ready_at is not None
    assert snapshot.worker_count == 0
    assert snapshot.active_leases == 0
    assert len(snapshot.stuck_intakes) <= 100


async def test_search_intake_chunks_respects_k_and_returns_unprocessed_evidence(
    intake_storage: Storage,
):
    await intake_storage.create_intake_chunks("intake-1", _drafts(), None)

    results = await intake_storage.search_intake_chunks("paragraph", k=1)

    assert len(results) == 1
    assert results[0]["table"] == "intake_chunk"
    assert results[0]["state"] in {"ready", "retry_wait", "paused", "leased"}
    assert results[0]["chunk_index"] in {0, 1}
    assert "embedding" not in results[0]


async def test_search_memory_candidates_embeds_query_once_for_all_three_tables(
    intake_storage: Storage, embedder: CountingEmbedder
):
    note = await intake_storage.create_note("paragraph memory")
    entity = await intake_storage.create_entity("paragraph", "concept")
    await intake_storage.create_intake_chunks("intake-1", _drafts(), None)
    previous_calls = len(embedder.texts)

    candidates = await intake_storage.search_memory_candidates("paragraph", k=5)

    assert embedder.texts[previous_calls:] == ["paragraph"]
    assert isinstance(candidates, MemorySearchCandidates)
    for table, paths, expected_id in (
        ("note", candidates.note, note["id"]),
        ("entity", candidates.entity, entity["id"]),
        ("intake_chunk", candidates.intake_chunk, None),
    ):
        assert isinstance(paths, RankedSearchCandidates)
        for records in (paths.bm25, paths.vector):
            assert 0 < len(records) <= 5
            assert all(record["id"].startswith(f"{table}:") for record in records)
            assert all("embedding" not in record for record in records)
            if expected_id is not None:
                assert {record["id"] for record in records} == {expected_id}
            else:
                assert {record["chunk_index"] for record in records} == {0, 1}


async def test_search_memory_candidates_caps_each_table_and_search_path(
    intake_storage: Storage,
):
    await intake_storage.create_notes(
        [{"content": "paragraph first"}, {"content": "paragraph second"}]
    )
    await intake_storage.create_entities(
        [
            {"name": "paragraph first", "type": "concept"},
            {"name": "paragraph second", "type": "concept"},
        ]
    )
    await intake_storage.create_intake_chunks("intake-1", _drafts(), None)

    candidates = await intake_storage.search_memory_candidates("paragraph", k=1)

    for paths in (candidates.note, candidates.entity, candidates.intake_chunk):
        assert len(paths.bm25) == 1
        assert len(paths.vector) == 1
        assert all("embedding" not in record for record in paths.bm25 + paths.vector)


async def test_search_memory_candidates_returns_empty_ranked_paths(
    intake_storage: Storage, embedder: CountingEmbedder
):
    candidates = await intake_storage.search_memory_candidates("missing", k=5)

    assert candidates == MemorySearchCandidates()
    assert embedder.texts == ["missing"]
