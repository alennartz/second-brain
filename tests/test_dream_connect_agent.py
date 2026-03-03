import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.models.test import TestModel

from second_brain.agents.dream_connect import ConnectDeps, create_connect_agent
from second_brain.db import init_schema, init_vector_indexes

dummy_embed = AsyncMock(return_value=[0.5, 0.5, 0.0])


@pytest.fixture
async def connect_db(db):
    await init_schema(db)
    await init_vector_indexes(db, dimensions=3)
    await db.query("""
        CREATE entity:py SET name = 'Python', type = 'language', embedding = [0.9, 0.1, 0.0];
        CREATE entity:fa SET name = 'FastAPI', type = 'framework', embedding = [0.8, 0.2, 0.0];
        CREATE note:1 SET content = 'FastAPI uses Python', source = 'cli', embedding = [0.85, 0.15, 0.0];
        RELATE note:1->references->entity:py;
        RELATE note:1->references->entity:fa;
    """)
    return db


async def test_connect_agent_runs(connect_db):
    """Connect agent can run without crashing."""
    cancel = asyncio.Event()
    agent = create_connect_agent()
    deps = ConnectDeps(db=connect_db, embed_fn=dummy_embed, cancel=cancel)
    result = await agent.run(
        "Explore connections for these nodes: entity:py, entity:fa",
        deps=deps,
        model=TestModel(),
    )
    assert isinstance(result.output, str)
