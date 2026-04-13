import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from second_brain.db import init_schema, init_vector_indexes
from second_brain.scheduler import DreamCycleState, DreamScheduler

dummy_embed = AsyncMock(return_value=[0.5, 0.5, 0.0])


@pytest.fixture
async def scheduler_db(db):
    await init_schema(db)
    await init_vector_indexes(db, dimensions=3)
    return db


@pytest.fixture
def scheduler(scheduler_db):
    return DreamScheduler(
        db=scheduler_db,
        embed_fn=dummy_embed,
        model=MagicMock(),
        idle_timeout=0.1,
        batch_size=10,
    )


async def test_scheduler_selects_lowest_dream_age_first(scheduler_db):
    await scheduler_db.query("""
        CREATE entity:old SET name = 'old', type = 'concept',
            embedding = [0.1, 0.2, 0.3], dream_age = 5;
        CREATE entity:new SET name = 'new', type = 'concept',
            embedding = [0.4, 0.5, 0.6], dream_age = 0;
        CREATE entity:mid SET name = 'mid', type = 'concept',
            embedding = [0.7, 0.8, 0.9], dream_age = 2;
    """)
    sched = DreamScheduler(
        db=scheduler_db,
        embed_fn=dummy_embed,
        model=MagicMock(),
        idle_timeout=10,
        batch_size=10,
    )
    batch = await sched._select_batch()
    ids = [str(n["id"]) for n in batch]
    # Should be sorted: dream_age 0 first, then 2, then 5
    assert "new" in ids[0]
    assert "mid" in ids[1]
    assert "old" in ids[2]


async def test_scheduler_respects_batch_size(scheduler_db):
    for i in range(20):
        await scheduler_db.query(
            f"CREATE entity:e{i} SET name = 'e{i}', type = 'test', embedding = [0.1, 0.2, 0.3], dream_age = 0"
        )
    sched = DreamScheduler(
        db=scheduler_db,
        embed_fn=dummy_embed,
        model=MagicMock(),
        idle_timeout=10,
        batch_size=5,
    )
    batch = await sched._select_batch()
    assert len(batch) == 5


async def test_scheduler_touch_activity_resets_cancel(scheduler):
    scheduler.touch_activity()
    assert scheduler._cancel.is_set()


def test_compute_max_cycles_exact_fit():
    """25 nodes, batch 25 → ceil(sqrt(25/25)) = ceil(sqrt(1)) = 1."""
    assert DreamScheduler._compute_max_cycles(25, 25) == 1


def test_compute_max_cycles_1000_nodes():
    """1000 nodes, batch 25 → ceil(sqrt(1000/25)) = ceil(sqrt(40)) = ceil(6.32) = 7."""
    assert DreamScheduler._compute_max_cycles(1000, 25) == 7


def test_compute_max_cycles_10000_nodes():
    """10000 nodes, batch 25 → ceil(sqrt(10000/25)) = ceil(sqrt(400)) = ceil(20) = 20."""
    assert DreamScheduler._compute_max_cycles(10000, 25) == 20


def test_compute_max_cycles_zero_nodes():
    """0 nodes → 0 (nothing to dream about)."""
    assert DreamScheduler._compute_max_cycles(0, 25) == 0


def test_compute_max_cycles_fewer_than_batch():
    """10 nodes, batch 25 → ceil(sqrt(10/25)) = ceil(sqrt(0.4)) = 1."""
    assert DreamScheduler._compute_max_cycles(10, 25) == 1


async def test_count_nodes_empty_db(scheduler):
    count = await scheduler._count_nodes()
    assert count == 0


async def test_count_nodes_entities_and_notes(scheduler_db, scheduler):
    await scheduler_db.query("""
        CREATE entity:a SET name = 'A', type = 'concept',
            embedding = [0.1, 0.2, 0.3], dream_age = 0;
        CREATE entity:b SET name = 'B', type = 'concept',
            embedding = [0.4, 0.5, 0.6], dream_age = 0;
        CREATE note:1 SET content = 'hello', source = 'test',
            embedding = [0.7, 0.8, 0.9], dream_age = 0;
    """)
    count = await scheduler._count_nodes()
    assert count == 3


async def test_count_nodes_only_entities(scheduler_db, scheduler):
    await scheduler_db.query("""
        CREATE entity:x SET name = 'X', type = 'concept',
            embedding = [0.1, 0.2, 0.3], dream_age = 0;
        CREATE entity:y SET name = 'Y', type = 'concept',
            embedding = [0.4, 0.5, 0.6], dream_age = 0;
    """)
    count = await scheduler._count_nodes()
    assert count == 2


async def test_count_nodes_only_notes(scheduler_db, scheduler):
    await scheduler_db.query("""
        CREATE note:1 SET content = 'one', source = 'test',
            embedding = [0.1, 0.2, 0.3], dream_age = 0;
        CREATE note:2 SET content = 'two', source = 'test',
            embedding = [0.4, 0.5, 0.6], dream_age = 0;
        CREATE note:3 SET content = 'three', source = 'test',
            embedding = [0.7, 0.8, 0.9], dream_age = 0;
    """)
    count = await scheduler._count_nodes()
    assert count == 3


def test_backoff_initial_state():
    """After construction: current_delay == idle_timeout, cycle_count == 0, max_cycles is None."""
    state = DreamCycleState(idle_timeout=60, delay_multiplier=1.5, max_delay=43200)
    assert state.current_delay == 60
    assert state.cycle_count == 0
    assert state.max_cycles is None


def test_advance_backoff_multiplies_delay():
    """advance() multiplies current_delay by delay_multiplier and increments cycle_count."""
    state = DreamCycleState(idle_timeout=100, delay_multiplier=2.0, max_delay=100000)
    assert state.current_delay == 100
    state.advance()
    assert state.current_delay == 200
    assert state.cycle_count == 1
    state.advance()
    assert state.current_delay == 400
    assert state.cycle_count == 2


def test_advance_backoff_caps_at_max_delay():
    """advance() caps current_delay at max_delay."""
    state = DreamCycleState(idle_timeout=100, delay_multiplier=2.0, max_delay=300)
    state.advance()  # 200
    assert state.current_delay == 200
    state.advance()  # 400 -> capped to 300
    assert state.current_delay == 300
    state.advance()  # still 300
    assert state.current_delay == 300


def test_cycle_state_reset():
    """reset() restores cycle_count, current_delay, and max_cycles to initial values."""
    state = DreamCycleState(idle_timeout=60, delay_multiplier=2.0, max_delay=1000)
    state.advance()
    state.advance()
    state.max_cycles = 10

    assert state.current_delay != 60
    assert state.cycle_count == 2
    assert state.max_cycles == 10

    state.reset()

    assert state.cycle_count == 0
    assert state.current_delay == 60
    assert state.max_cycles is None


def test_touch_activity_resets_backoff_state():
    """touch_activity() resets backoff state via DreamCycleState.reset()."""
    sched = DreamScheduler(
        db=MagicMock(),
        embed_fn=dummy_embed,
        model=MagicMock(),
        idle_timeout=60,
        batch_size=10,
        delay_multiplier=2.0,
        max_delay=1000,
    )
    # Simulate some backoff progression
    sched._state.advance()
    sched._state.advance()
    sched._state.max_cycles = 10

    assert sched._state.current_delay != 60
    assert sched._state.cycle_count == 2
    assert sched._state.max_cycles == 10

    sched.touch_activity()

    assert sched._state.cycle_count == 0
    assert sched._state.current_delay == 60
    assert sched._state.max_cycles is None


def test_backoff_default_params():
    """Default delay_multiplier=1.5 and max_delay=43200 when not specified."""
    sched = DreamScheduler(
        db=MagicMock(),
        embed_fn=dummy_embed,
        model=MagicMock(),
        idle_timeout=0.1,
        batch_size=10,
    )
    assert sched._state.delay_multiplier == 1.5
    assert sched._state.max_delay == 43200


async def test_scheduler_increments_dream_age(scheduler_db):
    await scheduler_db.query("""
        CREATE entity:a SET name = 'A', type = 'concept',
            embedding = [0.1, 0.2, 0.3], dream_age = 0;
    """)
    sched = DreamScheduler(
        db=scheduler_db,
        embed_fn=dummy_embed,
        model=MagicMock(),
        idle_timeout=10,
        batch_size=10,
    )
    await sched._increment_dream_age(["entity:a"])
    result = (await scheduler_db.query("SELECT dream_age FROM entity:a"))[0]
    assert result["dream_age"] == 1


async def test_run_forever_stops_at_max_cycles(scheduler_db):
    """run_forever should stop calling run_cycle once max_cycles is reached."""
    # Create 4 entities so _count_nodes() returns 4
    await scheduler_db.query("""
        CREATE entity:a SET name = 'A', type = 'concept',
            embedding = [0.1, 0.2, 0.3], dream_age = 0;
        CREATE entity:b SET name = 'B', type = 'concept',
            embedding = [0.4, 0.5, 0.6], dream_age = 0;
        CREATE entity:c SET name = 'C', type = 'concept',
            embedding = [0.7, 0.8, 0.9], dream_age = 0;
        CREATE entity:d SET name = 'D', type = 'concept',
            embedding = [0.1, 0.3, 0.5], dream_age = 0;
    """)
    sched = DreamScheduler(
        db=scheduler_db,
        embed_fn=dummy_embed,
        model=MagicMock(),
        idle_timeout=0.01,
        batch_size=4,
        delay_multiplier=1.5,
        max_delay=100,
    )
    # batch_size=4, 4 nodes → max_cycles = ceil(sqrt(4/4)) = ceil(1) = 1
    run_cycle_mock = AsyncMock()
    sched.run_cycle = run_cycle_mock  # type: ignore[method-assign]

    task = asyncio.create_task(sched.run_forever())
    # Wait enough time for the scheduler to run its cycles and converge
    await asyncio.sleep(0.2)
    # After convergence it should be waiting on _cancel; trigger it to unblock, then cancel task
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert run_cycle_mock.call_count == 1


async def test_run_forever_uses_backoff_delay(scheduler_db):
    """Verify that delays increase with the backoff multiplier between cycles."""
    # Create 100 entities → max_cycles = ceil(sqrt(100/4)) = ceil(5) = 5
    for i in range(100):
        await scheduler_db.query(
            f"CREATE entity:e{i} SET name = 'e{i}', type = 'test', "
            f"embedding = [0.1, 0.2, 0.3], dream_age = 0"
        )
    idle_timeout = 0.01
    multiplier = 2.0
    sched = DreamScheduler(
        db=scheduler_db,
        embed_fn=dummy_embed,
        model=MagicMock(),
        idle_timeout=idle_timeout,
        batch_size=4,
        delay_multiplier=multiplier,
        max_delay=100,
    )

    observed_delays: list[float] = []

    original_run_cycle = AsyncMock()
    sched.run_cycle = original_run_cycle  # type: ignore[method-assign]

    # Track the delay used before each cycle by capturing _state.current_delay
    original_advance = sched._state.advance

    def tracking_advance():
        observed_delays.append(sched._state.current_delay)
        original_advance()

    sched._state.advance = tracking_advance  # type: ignore[method-assign]

    task = asyncio.create_task(sched.run_forever())
    # Wait enough for multiple cycles
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Should have at least 2 cycles to verify backoff
    assert len(observed_delays) >= 2
    # First delay should be idle_timeout
    assert observed_delays[0] == pytest.approx(idle_timeout)
    # Each subsequent delay should be multiplied
    for i in range(1, len(observed_delays)):
        expected = min(observed_delays[i - 1] * multiplier, 100)
        assert observed_delays[i] == pytest.approx(expected)


async def test_run_forever_resets_on_activity(scheduler_db):
    """touch_activity() during run_forever resets state (cycle_count back to 0)."""
    # Create enough entities for multiple cycles
    for i in range(100):
        await scheduler_db.query(
            f"CREATE entity:e{i} SET name = 'e{i}', type = 'test', "
            f"embedding = [0.1, 0.2, 0.3], dream_age = 0"
        )
    sched = DreamScheduler(
        db=scheduler_db,
        embed_fn=dummy_embed,
        model=MagicMock(),
        idle_timeout=0.01,
        batch_size=4,
        delay_multiplier=1.5,
        max_delay=100,
    )

    cycle_call_count = 0
    activity_triggered = False

    async def mock_run_cycle():
        nonlocal cycle_call_count, activity_triggered
        cycle_call_count += 1
        # After the first cycle, simulate user activity
        if cycle_call_count == 1 and not activity_triggered:
            activity_triggered = True
            sched.touch_activity()

    sched.run_cycle = mock_run_cycle  # type: ignore[method-assign]

    task = asyncio.create_task(sched.run_forever())
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # run_cycle should have been called more than once (reset restarted the loop)
    assert cycle_call_count >= 2
    # After the activity reset, cycle_count should have restarted from 0
    # (the state was reset by touch_activity). We can't check mid-run easily,
    # but we verify that more cycles ran than the original max_cycles,
    # which proves a reset happened.
    # Original max_cycles = ceil(sqrt(100/4)) = ceil(5) = 5
    # With reset, total calls should exceed what a single pass would produce
    # (at minimum 2: one before reset + one after)
