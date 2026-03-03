import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.models.test import TestModel

from second_brain.agents.dream_dedup import DedupDeps, create_dedup_agent
from second_brain.db import init_schema, init_vector_indexes

dummy_embed = AsyncMock(return_value=[0.5, 0.5, 0.0])


@pytest.fixture
async def dedup_db(db):
    await init_schema(db)
    await init_vector_indexes(db, dimensions=3)
    await db.query("""
        CREATE entity:py SET name = 'Python', type = 'language',
            description = 'A programming language', embedding = [0.9, 0.1, 0.0], dream_age = 0;
        CREATE entity:py3 SET name = 'Python 3', type = 'language',
            description = 'Third version of Python', embedding = [0.85, 0.15, 0.0], dream_age = 0;
    """)
    return db


async def test_dedup_agent_runs(dedup_db):
    """Dedup agent can run without crashing."""
    cancel = asyncio.Event()
    agent = create_dedup_agent()
    deps = DedupDeps(db=dedup_db, embed_fn=dummy_embed, cancel=cancel)
    result = await agent.run(
        "Process this batch of nodes for deduplication: entity:py, entity:py3",
        deps=deps,
        model=TestModel(),
    )
    assert isinstance(result.output, str)
