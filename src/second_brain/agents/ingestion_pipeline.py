"""Synchronous intake staging and continuous processing pipeline interfaces."""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from second_brain.db import Storage
from second_brain.models import (
    ClaimedBatch,
    EnqueueResult,
    IntakeChunkDraft,
    IntakeRequest,
    PipelineSnapshot,
)

logger = logging.getLogger(__name__)


@dataclass
class IngestBatchOutcome:
    """Outcome reported by one independent ingest-agent batch run."""

    completed: bool
    summary: str | None = None
    errors: list[str] = field(default_factory=list)


class IngestBatchRunner(Protocol):
    """Adapter for the tool-driven ingest agent."""

    async def run(self, text: str, hints: list[str]) -> IngestBatchOutcome: ...


def _paragraph_units(text: str) -> list[str]:
    """Split text at blank lines, keeping each separator on the prior unit."""
    # A blank line is a run of at least two line breaks, with indentation
    # between them. Include all separator whitespace in the preceding unit.
    boundary = re.compile(r"(?:\r?\n[ \t]*){2,}")
    units: list[str] = []
    start = 0
    for match in boundary.finditer(text):
        end = match.end()
        units.append(text[start:end])
        start = end
    units.append(text[start:])
    return [unit for unit in units if unit and unit.strip()]


def _sentence_units(text: str) -> list[str]:
    """Split text at sentence punctuation and retain following whitespace."""
    units: list[str] = []
    start = 0
    index = 0
    while index < len(text):
        if text[index] in ".!?" and index + 1 < len(text):
            next_index = index + 1
            if text[next_index].isspace():
                while next_index < len(text) and text[next_index].isspace():
                    next_index += 1
                units.append(text[start:next_index])
                start = next_index
                index = next_index
                continue
        index += 1
    units.append(text[start:])
    return [unit for unit in units if unit and unit.strip()]


def _split_long_unit(unit: str, max_chars: int) -> list[str]:
    """Split one oversized unit without dropping characters."""
    pieces: list[str] = []
    start = 0
    while start < len(unit):
        remaining = unit[start:]
        if len(remaining) <= max_chars:
            pieces.append(remaining)
            break

        window = unit[start : start + max_chars]
        split_at = -1
        for index, character in enumerate(window):
            if character.isspace():
                split_at = index
        # Keep the separator attached to the preceding piece.
        cut = max_chars if split_at <= 0 else split_at + 1
        pieces.append(unit[start : start + cut])
        start += cut
    return [piece for piece in pieces if piece and piece.strip()]


def split_intake_text(text: str, max_chars: int) -> list[str]:
    """Return disjoint, bounded chunks that preserve stripped intake text.

    Paragraph boundaries are preferred. Oversized paragraphs fall back to
    sentence boundaries, then to the last whitespace within the limit.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    stripped = text.strip()
    if not stripped:
        return []

    units: list[str] = []
    for paragraph in _paragraph_units(stripped):
        if len(paragraph) <= max_chars:
            units.append(paragraph)
            continue
        sentences = _sentence_units(paragraph)
        if len(sentences) == 1 and sentences[0] == paragraph:
            units.extend(_split_long_unit(paragraph, max_chars))
            continue
        for sentence in sentences:
            if len(sentence) <= max_chars:
                units.append(sentence)
            else:
                units.extend(_split_long_unit(sentence, max_chars))

    chunks: list[str] = []
    current = ""
    for unit in units:
        if not unit or not unit.strip():
            continue
        # This is defensive. All units are split above, but retaining the
        # invariant here keeps the packing point easy to reason about.
        pieces = _split_long_unit(unit, max_chars) if len(unit) > max_chars else [unit]
        for piece in pieces:
            if not piece or not piece.strip():
                continue
            if current and len(current) + len(piece) > max_chars:
                chunks.append(current)
                current = ""
            current += piece
    if current:
        chunks.append(current)
    return chunks


def retry_delay(failed_attempts: int, base: float, cap: float) -> float:
    """Return capped exponential delay without overflowing large attempts."""
    if failed_attempts <= 0 or base <= 0 or cap <= 0:
        return 0.0
    if base >= cap:
        return cap
    exponent = failed_attempts - 1
    if math.isfinite(cap) and math.isfinite(base):
        saturation = math.ceil(math.log2(cap / base))
        if exponent >= saturation:
            return cap
    try:
        value = math.ldexp(base, exponent)
    except (OverflowError, ValueError):
        return cap
    return min(value, cap)


class IngestionPipeline:
    """Application-facing interface for intake staging and worker processing."""

    def __init__(
        self,
        storage: Storage,
        runner: IngestBatchRunner,
        *,
        max_request_chars: int,
        chunk_chars: int,
        processing_batch_chars: int,
        worker_concurrency: int = 1,
        lease_seconds: float = 300,
        poll_interval_seconds: float = 1,
        retry_base_delay_seconds: float = 5,
        retry_max_delay_seconds: float = 3_600,
        shutdown_grace_seconds: float = 10,
        activity_callback: Callable[[], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Inject a timezone-aware UTC clock for retry deadlines, or use UTC now."""
        self.storage = storage
        self.runner = runner
        self.max_request_chars = max_request_chars
        self.chunk_chars = chunk_chars
        self.processing_batch_chars = processing_batch_chars
        self.worker_concurrency = worker_concurrency
        self.lease_seconds = lease_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.retry_base_delay_seconds = retry_base_delay_seconds
        self.retry_max_delay_seconds = retry_max_delay_seconds
        self.shutdown_grace_seconds = shutdown_grace_seconds
        self.activity_callback = activity_callback
        self.clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._pipeline_id = uuid4().hex
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._stop_event = asyncio.Event()

    async def enqueue(self, request: IntakeRequest) -> EnqueueResult:
        """Chunk, embed, and atomically stage one intake request."""
        if not request.text.strip():
            raise ValueError("intake text must not be empty")
        if len(request.text) > self.max_request_chars:
            raise ValueError("intake text exceeds the maximum request size")

        contents = split_intake_text(request.text, self.chunk_chars)
        intake_id = uuid4().hex
        total_chunks = len(contents)
        drafts = [
            IntakeChunkDraft(
                chunk_index=index,
                total_chunks=total_chunks,
                content=content,
                source=request.source,
                hints=request.hints,
            )
            for index, content in enumerate(contents)
        ]
        chunks_stored = await self.storage.create_intake_chunks(
            intake_id, drafts, request.idempotency_key
        )
        return EnqueueResult(chunks_stored=chunks_stored)

    async def start(self) -> None:
        """Start the configured background worker pool."""
        if self._worker_tasks:
            return
        self._stop_event.clear()
        self._worker_tasks = [
            asyncio.create_task(
                self._worker_loop(f"{self._pipeline_id}-{number}"),
                name=f"ingestion-worker-{self._pipeline_id}-{number}",
            )
            for number in range(max(0, self.worker_concurrency))
        ]

    async def stop(self) -> None:
        """Stop workers, bounding shutdown when a provider call is stuck."""
        if not self._worker_tasks:
            return
        self._stop_event.set()
        tasks = list(self._worker_tasks)
        try:
            done, pending = await asyncio.wait(
                tasks, timeout=max(0.0, self.shutdown_grace_seconds)
            )
            await asyncio.gather(*done, return_exceptions=True)
            if pending:
                logger.warning(
                    "cancelling %d ingestion workers after shutdown grace period",
                    len(pending),
                )
                for task in pending:
                    task.cancel()
                # Normal provider calls honor cancellation. Do not let a
                # provider that suppresses cancellation block application exit.
                finished, still_pending = await asyncio.wait(
                    pending, timeout=max(0.1, self.shutdown_grace_seconds)
                )
                await asyncio.gather(*finished, return_exceptions=True)
                if still_pending:
                    logger.error(
                        "%d ingestion workers ignored shutdown cancellation",
                        len(still_pending),
                    )
        finally:
            self._worker_tasks = []

    async def snapshot(self) -> PipelineSnapshot:
        """Return an aggregate pipeline snapshot."""
        queue = await self.storage.intake_queue_snapshot()
        workers = sum(1 for task in self._worker_tasks if not task.done())
        return PipelineSnapshot(
            ready=queue.ready,
            leased=queue.leased,
            retry_wait=queue.retry_wait,
            paused=queue.paused,
            oldest_ready_at=queue.oldest_ready_at,
            oldest_retry_at=queue.oldest_retry_at,
            worker_count=workers,
            active_leases=queue.active_leases,
            stuck_intakes=list(queue.stuck_intakes),
            recent_errors=list(queue.recent_errors),
        )

    async def pause_intake(self, intake_id: str) -> int:
        """Pause every remaining chunk for one intake and return its row count."""
        return await self.storage.set_intake_paused(intake_id, True)

    async def resume_intake(self, intake_id: str) -> int:
        """Resume every paused chunk for one intake and return its row count."""
        return await self.storage.set_intake_paused(intake_id, False)

    async def discard_intake(self, intake_id: str) -> int:
        """Delete remaining chunks for one intake without changing graph records."""
        return await self.storage.delete_intake(intake_id)

    async def _worker_loop(self, worker_id: str) -> None:
        """Claim and process work until the pipeline stop signal is set."""
        while not self._stop_event.is_set():
            try:
                batch = await self.storage.claim_intake_batch(
                    worker_id,
                    self.processing_batch_chars,
                    self.lease_seconds,
                )
            except Exception:
                logger.exception(
                    "ingestion worker %s failed to claim a batch", worker_id
                )
                if await self._wait_for_poll_or_stop():
                    break
                continue

            if batch is None:
                if await self._wait_for_poll_or_stop():
                    break
                continue
            try:
                await self._process_batch(batch)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "ingestion worker %s failed while processing lease %s",
                    worker_id,
                    batch.lease_token,
                )
                if await self._wait_for_poll_or_stop():
                    break

    async def _wait_for_poll_or_stop(self) -> bool:
        """Wait for either a stop signal or the next queue poll."""
        try:
            await asyncio.wait_for(
                self._stop_event.wait(), timeout=max(0.0, self.poll_interval_seconds)
            )
        except TimeoutError:
            return False
        return True

    def _touch_activity(self) -> None:
        """Notify the host scheduler without allowing it to kill a worker."""
        if self.activity_callback is None:
            return
        try:
            self.activity_callback()
        except Exception:
            logger.exception("ingestion activity callback failed")

    async def _renew_lease_loop(
        self,
        batch: ClaimedBatch,
        runner_task: asyncio.Task[IngestBatchOutcome],
        stop_event: asyncio.Event,
        lease_lost: asyncio.Event,
    ) -> None:
        """Renew a live lease and cancel the runner when ownership is lost."""
        interval = max(0.01, self.lease_seconds / 3)
        expiry = min(
            (
                datetime.fromisoformat(str(chunk["lease_expires_at"]))
                for chunk in batch.chunks
                if chunk.get("lease_expires_at") is not None
            ),
            default=self.clock() + timedelta(seconds=self.lease_seconds),
        )
        while True:
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=min(
                        interval, max(0.01, (expiry - self.clock()).total_seconds())
                    ),
                )
                return
            except TimeoutError:
                pass
            try:
                renewed = await self.storage.renew_intake_batch(
                    batch.lease_token, self.lease_seconds
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "failed to renew ingestion lease %s", batch.lease_token
                )
                if self.clock() < expiry:
                    continue
                lease_lost.set()
                runner_task.cancel()
                return
            if renewed != len(batch.chunks):
                logger.error(
                    "lost ingestion lease %s for intake %s (%d/%d rows renewed)",
                    batch.lease_token,
                    batch.intake_id,
                    renewed,
                    len(batch.chunks),
                )
                lease_lost.set()
                runner_task.cancel()
                return
            expiry = self.clock() + timedelta(seconds=self.lease_seconds)

    async def _process_batch(self, batch: ClaimedBatch) -> None:
        """Run one leased batch and acknowledge or release it."""
        self._touch_activity()
        heartbeat_stop = asyncio.Event()
        lease_lost = asyncio.Event()
        runner_task: asyncio.Task[IngestBatchOutcome] | None = None
        heartbeat_task: asyncio.Task[None] | None = None
        try:
            outcome: IngestBatchOutcome | None = None
            failure: BaseException | None = None
            try:
                text = "".join(chunk["content"] for chunk in batch.chunks)
                hints = list(batch.chunks[0]["hints"]) if batch.chunks else []
                runner_task = asyncio.create_task(self.runner.run(text, hints))
                heartbeat_task = asyncio.create_task(
                    self._renew_lease_loop(
                        batch, runner_task, heartbeat_stop, lease_lost
                    )
                )
                outcome = await runner_task
            except asyncio.CancelledError:
                if not lease_lost.is_set():
                    raise
            except Exception as exc:
                failure = exc

            if lease_lost.is_set():
                return
            clean = (
                failure is None
                and outcome is not None
                and outcome.completed
                and not outcome.errors
            )
            heartbeat_stop.set()
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                await asyncio.wait({heartbeat_task}, timeout=0.1)
                heartbeat_task = None
            if lease_lost.is_set():
                return

            if clean:
                try:
                    deleted = await self.storage.delete_intake_batch(batch.lease_token)
                    if deleted != len(batch.chunks):
                        logger.error(
                            "lost ingestion lease %s for intake %s during acknowledgement "
                            "(%d/%d rows deleted)",
                            batch.lease_token,
                            batch.intake_id,
                            deleted,
                            len(batch.chunks),
                        )
                except Exception:
                    logger.exception(
                        "failed to delete completed ingestion batch %s",
                        batch.lease_token,
                    )
            else:
                if failure is not None:
                    message = str(failure)
                elif outcome is not None and outcome.errors:
                    message = "\n".join(str(error) for error in outcome.errors)
                else:
                    message = "ingest batch did not complete"
                failed_attempts = (
                    max(
                        (
                            int(chunk.get("attempt_count", 0) or 0)
                            for chunk in batch.chunks
                        ),
                        default=0,
                    )
                    + 1
                )
                deadline = self.clock() + timedelta(
                    seconds=retry_delay(
                        failed_attempts,
                        self.retry_base_delay_seconds,
                        self.retry_max_delay_seconds,
                    )
                )
                try:
                    await self.storage.release_intake_batch(
                        batch.lease_token, message, deadline
                    )
                except Exception:
                    logger.exception(
                        "failed to release ingestion batch %s",
                        batch.lease_token,
                    )
        finally:
            heartbeat_stop.set()
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                finished, _pending = await asyncio.wait({heartbeat_task}, timeout=0.1)
                if not finished:
                    logger.error("ingestion lease heartbeat ignored cancellation")
            if runner_task is not None and not runner_task.done():
                runner_task.cancel()
                finished, _pending = await asyncio.wait(
                    {runner_task}, timeout=max(0.1, self.shutdown_grace_seconds)
                )
                if not finished:
                    logger.error("ingestion runner ignored cancellation")
            self._touch_activity()
