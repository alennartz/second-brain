import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from surrealdb import AsyncSurreal, RecordID

logger = logging.getLogger(__name__)


def _to_str(val: Any) -> str:
    if isinstance(val, RecordID):
        return f"{val.table_name}:{val.id}"
    return str(val)


class DreamScheduler:
    def __init__(
        self,
        db: AsyncSurreal,  # pyright: ignore[reportGeneralTypeIssues]
        embed_fn: Callable[[str], Awaitable[list[float]]],
        model: Any,
        idle_timeout: float = 600,  # seconds
        batch_size: int = 10,
    ):
        self.db = db
        self.embed_fn = embed_fn
        self.model = model
        self.idle_timeout = idle_timeout
        self.batch_size = batch_size
        self._last_activity: float = time.monotonic()
        self._cancel = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def touch_activity(self) -> None:
        """Record that user activity (ingest/recall) occurred. Wakes up dreaming."""
        self._last_activity = time.monotonic()
        self._cancel.set()

    def _is_idle(self) -> bool:
        return (time.monotonic() - self._last_activity) >= self.idle_timeout

    async def _select_batch(self) -> list[dict[str, Any]]:
        """Select nodes with lowest dream_age, breaking ties by newest created_at."""
        nodes: list[dict[str, Any]] = []
        for table in ("entity", "note"):
            result = await self.db.query(
                f"SELECT * FROM {table} ORDER BY dream_age ASC, created_at DESC LIMIT {self.batch_size}"
            )
            if isinstance(result, list):
                nodes.extend(result)

        # Sort combined results by dream_age ASC, created_at DESC (newest first
        # within same dream_age). created_at may be datetime or string.
        nodes.sort(
            key=lambda n: (
                n.get("dream_age", 0),
                # Negate timestamp for DESC sort; fallback to 0 for missing created_at
                -(
                    n["created_at"].timestamp()
                    if hasattr(n.get("created_at"), "timestamp")
                    else 0
                ),
            )
        )
        return nodes[: self.batch_size]

    async def _increment_dream_age(self, record_ids: list[str]) -> None:
        """Increment dream_age by 1 on all given record IDs."""
        for rid in record_ids:
            await self.db.query(f"UPDATE {rid} SET dream_age = dream_age + 1")

    async def _run_cycle(self) -> None:
        """Run one dream cycle: dedup then connect."""
        from second_brain.agents.dream_connect import ConnectDeps, create_connect_agent
        from second_brain.agents.dream_dedup import DedupDeps, create_dedup_agent

        self._cancel.clear()

        batch = await self._select_batch()
        if not batch:
            logger.info("dream: no nodes to process, skipping cycle")
            return

        batch_ids = [_to_str(n["id"]) for n in batch]
        logger.info("dream: starting cycle with %d nodes", len(batch_ids))

        # Cancellation is checked between phases, not between individual tool calls,
        # because PydanticAI does not expose a mid-run interruption hook.

        # Phase 1: Dedup
        if self._cancel.is_set():
            logger.info("dream: woke up before dedup phase")
            return

        dedup_agent = create_dedup_agent()
        dedup_deps = DedupDeps(db=self.db, embed_fn=self.embed_fn, cancel=self._cancel)
        prompt = (
            f"Process this batch of nodes for deduplication: {', '.join(batch_ids)}"
        )
        try:
            await dedup_agent.run(prompt, deps=dedup_deps, model=self.model)
        except Exception:
            logger.exception("dream: dedup agent failed")
            return

        # Result set = everything dedup touched (minus deleted nodes which are gone)
        result_set_ids = list(set(dedup_deps.touched_ids))
        # Add batch IDs that weren't touched by dedup
        for bid in batch_ids:
            if bid not in result_set_ids:
                result_set_ids.append(bid)

        logger.info("dream: dedup complete, result set has %d IDs", len(result_set_ids))

        # Phase 2: Connect
        if self._cancel.is_set():
            logger.info("dream: woke up before connect phase")
            await self._increment_dream_age(result_set_ids)
            return

        connect_agent = create_connect_agent()
        connect_deps = ConnectDeps(
            db=self.db, embed_fn=self.embed_fn, cancel=self._cancel
        )
        prompt = f"Explore connections for these nodes: {', '.join(result_set_ids)}"
        try:
            await connect_agent.run(prompt, deps=connect_deps, model=self.model)
        except Exception:
            logger.exception("dream: connect agent failed")

        # Final: increment dream_age on the full result set
        final_ids = list(set(result_set_ids + connect_deps.touched_ids))
        await self._increment_dream_age(final_ids)
        logger.info(
            "dream: cycle complete, incremented dream_age on %d records", len(final_ids)
        )

    async def run_forever(self) -> None:
        """Main loop: wait for idle, run dream cycle, repeat."""
        logger.info(
            "dream: scheduler started (idle_timeout=%.0fs, batch_size=%d)",
            self.idle_timeout,
            self.batch_size,
        )
        while True:
            # Wait until idle
            while not self._is_idle():
                await asyncio.sleep(1)

            # Check cancel wasn't set while we were checking
            if self._cancel.is_set():
                self._cancel.clear()
                continue

            logger.info("dream: server idle, starting dream cycle")
            await self._run_cycle()

    def start(self) -> None:
        """Start the scheduler as a background asyncio task."""
        self._task = asyncio.create_task(self.run_forever())
        logger.info("dream: background task started")

    def stop(self) -> None:
        """Cancel the background task."""
        if self._task:
            self._task.cancel()
            self._task = None
            logger.info("dream: background task stopped")
