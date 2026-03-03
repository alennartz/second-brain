from unittest.mock import AsyncMock, MagicMock

import pytest

from second_brain.db import init_schema, init_vector_indexes
from second_brain.scheduler import DreamScheduler

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


async def test_scheduler_touch_activity_resets_idle(scheduler):
    scheduler.touch_activity()
    assert not scheduler._is_idle()


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
