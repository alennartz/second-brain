"""Behavioral tests for the intake-chunk Storage boundary.

The queue methods are interface stubs in this phase. These tests describe the
contracts that the storage implementation must satisfy.
"""

from datetime import UTC, datetime, timedelta

from second_brain.db import Storage
from second_brain.models import IntakeChunkDraft, IntakeQueueSnapshot


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
    storage: Storage,
):
    count = await storage.create_intake_chunks("intake-1", _drafts(), None)

    assert count == 2
    queued = await storage.search_intake_chunks("first paragraph", k=5)
    assert len(queued) == 1
    assert queued[0]["intake_id"] == "intake-1"
    assert queued[0]["chunk_index"] == 0
    assert queued[0]["source"] == "cli"
    assert "embedding" not in queued[0]


async def test_create_intake_chunks_is_all_or_nothing_when_embedding_fails(
    storage: Storage,
):
    drafts = _drafts()
    storage._embedder.embed_batch = _failing_embed_batch  # type: ignore[method-assign]

    try:
        await storage.create_intake_chunks("intake-1", drafts, None)
    except RuntimeError as exc:
        assert "embedding" in str(exc).lower()
    else:
        raise AssertionError("embedding failure must be reported")

    snapshot = await storage.intake_queue_snapshot()
    assert snapshot.ready == 0
    assert snapshot.leased == 0
    assert snapshot.retry_wait == 0
    assert snapshot.paused == 0


async def _failing_embed_batch(texts: list[str]) -> list[list[float]]:
    raise RuntimeError("embedding provider failed")


async def test_idempotency_key_collapses_only_rows_still_in_queue(storage: Storage):
    drafts = _drafts()
    first = await storage.create_intake_chunks("intake-1", drafts, "request-1")
    duplicate = await storage.create_intake_chunks("intake-1", drafts, "request-1")
    assert first == 2
    assert duplicate == 0

    claimed = await storage.claim_intake_batch(
        worker_id="worker-1", max_chars=1000, lease_seconds=60
    )
    assert claimed is not None
    await storage.delete_intake_batch(claimed.lease_token)

    accepted_after_delete = await storage.create_intake_chunks(
        "intake-1", drafts, "request-1"
    )
    assert accepted_after_delete == 2


async def test_claim_returns_contiguous_chunks_with_a_lease(storage: Storage):
    await storage.create_intake_chunks("intake-1", _drafts(), None)

    claimed = await storage.claim_intake_batch(
        worker_id="worker-1", max_chars=len("first paragraph"), lease_seconds=30
    )

    assert claimed is not None
    assert claimed.lease_token
    assert claimed.intake_id == "intake-1"
    assert [chunk["chunk_index"] for chunk in claimed.chunks] == [0]
    assert all(chunk["state"] == "leased" for chunk in claimed.chunks)


async def test_claim_replays_an_expired_lease(storage: Storage):
    await storage.create_intake_chunks("intake-1", _drafts(), None)
    first = await storage.claim_intake_batch(
        worker_id="worker-1", max_chars=1000, lease_seconds=0.001
    )
    assert first is not None

    replay = await storage.claim_intake_batch(
        worker_id="worker-2", max_chars=1000, lease_seconds=60
    )
    assert replay is not None
    assert replay.lease_token != first.lease_token
    assert replay.intake_id == first.intake_id


async def test_release_returns_batch_to_retry_wait_with_error(storage: Storage):
    await storage.create_intake_chunks("intake-1", _drafts(), None)
    claimed = await storage.claim_intake_batch(
        worker_id="worker-1", max_chars=1000, lease_seconds=60
    )
    assert claimed is not None
    retry_at = datetime.now(UTC) + timedelta(seconds=5)

    await storage.release_intake_batch(
        claimed.lease_token, error="agent failed", next_attempt_at=retry_at
    )
    snapshot = await storage.intake_queue_snapshot()
    assert snapshot.leased == 0
    assert snapshot.retry_wait == 2
    assert snapshot.recent_errors[-1]["error"] == "agent failed"
    assert snapshot.recent_errors[-1]["intake_id"] == "intake-1"


async def test_delete_intake_batch_removes_only_successful_lease(storage: Storage):
    await storage.create_intake_chunks("intake-1", _drafts(), None)
    await storage.create_intake_chunks("intake-2", _drafts(), None)
    claimed = await storage.claim_intake_batch(
        worker_id="worker-1", max_chars=1000, lease_seconds=60
    )
    assert claimed is not None

    deleted = await storage.delete_intake_batch(claimed.lease_token)

    assert deleted == 2
    snapshot = await storage.intake_queue_snapshot()
    assert snapshot.ready == 2


async def test_queue_snapshot_reports_counts_oldest_work_and_bounded_stuck_intakes(
    storage: Storage,
):
    await storage.create_intake_chunks("intake-1", _drafts(), None)
    snapshot = await storage.intake_queue_snapshot()

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
    storage: Storage,
):
    await storage.create_intake_chunks("intake-1", _drafts(), None)

    results = await storage.search_intake_chunks("paragraph", k=1)

    assert len(results) <= 1
    assert results[0]["table"] == "intake_chunk"
    assert results[0]["state"] in {"ready", "retry_wait", "paused", "leased"}
    assert results[0]["chunk_index"] in {0, 1}
