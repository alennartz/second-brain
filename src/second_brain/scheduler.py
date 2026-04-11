import asyncio
import contextlib
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

    async def _select_batch(
        self, table_filter: str | None = None
    ) -> list[dict[str, Any]]:
        """Select nodes with lowest dream_age, breaking ties by newest created_at.

        If table_filter is set (e.g. 'entity'), only that table is queried.
        """
        tables = (table_filter,) if table_filter else ("entity", "note")
        nodes: list[dict[str, Any]] = []
        for table in tables:
            result = await self.db.query(
                f"SELECT * OMIT embedding FROM {table} ORDER BY dream_age ASC, created_at DESC LIMIT {self.batch_size}"
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

    async def run_cycle(self) -> None:
        """Run one dream cycle: dedup then connect."""
        from second_brain.agents.dream_connect import ConnectDeps, create_connect_agent
        from second_brain.agents.dream_dedup import DedupDeps, create_dedup_agent

        self._cancel.clear()

        # Phase 1: Dedup — entities only, larger batch for better duplicate coverage
        if self._cancel.is_set():
            logger.info("dream: woke up before dedup phase")
            return

        dedup_batch = await self._select_batch(table_filter="entity")
        if dedup_batch:
            dedup_ids = [_to_str(n["id"]) for n in dedup_batch]
            logger.info("dream: dedup phase with %d entities", len(dedup_ids))

            dedup_agent = create_dedup_agent()
            dedup_deps = DedupDeps(
                db=self.db, embed_fn=self.embed_fn, cancel=self._cancel
            )
            prompt = (
                f"Process this batch of entities for deduplication: "
                f"{', '.join(dedup_ids)}"
            )
            try:
                await dedup_agent.run(prompt, deps=dedup_deps, model=self.model)
            except Exception:
                logger.exception("dream: dedup agent failed")
                if dedup_deps.touched_ids:
                    await self._increment_dream_age(list(set(dedup_deps.touched_ids)))
                return

            logger.info(
                "dream: dedup complete, touched %d IDs", len(dedup_deps.touched_ids)
            )
        else:
            dedup_deps = DedupDeps(
                db=self.db, embed_fn=self.embed_fn, cancel=self._cancel
            )
            dedup_ids = []

        # Phase 2: Connect — mixed batch (entities + notes)
        connect_batch = await self._select_batch()
        if not connect_batch:
            logger.info("dream: no nodes to process for connect, skipping")
            if dedup_deps.touched_ids:
                await self._increment_dream_age(list(set(dedup_deps.touched_ids)))
            return

        batch_ids = [_to_str(n["id"]) for n in connect_batch]
        logger.info("dream: connect phase with %d nodes", len(batch_ids))

        # Build result set from both phases
        result_set_ids = list(set(dedup_deps.touched_ids))
        for bid in batch_ids:
            if bid not in result_set_ids:
                result_set_ids.append(bid)
        for did in dedup_ids:
            if did not in result_set_ids:
                result_set_ids.append(did)

        node_ids = [
            rid
            for rid in result_set_ids
            if rid.startswith("entity:") or rid.startswith("note:")
        ]

        if self._cancel.is_set():
            logger.info("dream: woke up before connect phase")
            await self._increment_dream_age(result_set_ids)
            return

        connect_agent = create_connect_agent()
        connect_deps = ConnectDeps(
            db=self.db, embed_fn=self.embed_fn, cancel=self._cancel
        )
        prompt = f"Explore connections for these nodes: {', '.join(node_ids)}"
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
            await self.run_cycle()

    def start(self) -> None:
        """Start the scheduler as a background asyncio task."""
        self._task = asyncio.create_task(self.run_forever())
        logger.info("dream: background task started")

    async def stop(self) -> None:
        """Cancel the background task and await its completion."""
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("dream: background task stopped")
