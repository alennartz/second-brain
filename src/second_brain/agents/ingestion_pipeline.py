"""Synchronous intake staging and continuous processing pipeline interfaces."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from second_brain.db import Storage
from second_brain.models import (
    EnqueueResult,
    IntakeRequest,
    PipelineSnapshot,
)


@dataclass
class IngestBatchOutcome:
    """Outcome reported by one independent ingest-agent batch run."""

    completed: bool
    summary: str | None = None
    errors: list[str] = field(default_factory=list)


class IngestBatchRunner(Protocol):
    """Adapter for the tool-driven ingest agent."""

    async def run(self, text: str, hints: list[str]) -> IngestBatchOutcome: ...


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
        pause_dream: bool = False,
        activity_callback: Callable[[], None] | None = None,
    ) -> None:
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
        self.pause_dream = pause_dream
        self.activity_callback = activity_callback

    async def enqueue(self, request: IntakeRequest) -> EnqueueResult:
        """Chunk, embed, and atomically stage one intake request."""
        raise NotImplementedError("not implemented")

    async def start(self) -> None:
        """Start the configured background worker pool."""
        raise NotImplementedError("not implemented")

    async def stop(self) -> None:
        """Stop workers and await their completion."""
        raise NotImplementedError("not implemented")

    async def snapshot(self) -> PipelineSnapshot:
        """Return an aggregate pipeline snapshot."""
        raise NotImplementedError("not implemented")

    async def pause_intake(self, intake_id: str) -> None:
        """Pause ready and retry-wait chunks for one intake."""
        raise NotImplementedError("not implemented")

    async def resume_intake(self, intake_id: str) -> None:
        """Resume paused chunks for one intake."""
        raise NotImplementedError("not implemented")

    async def discard_intake(self, intake_id: str) -> int:
        """Delete remaining chunks for one intake without changing graph records."""
        raise NotImplementedError("not implemented")
