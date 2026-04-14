import asyncio

import pytest
from pydantic_ai.models.test import TestModel

from second_brain.agents.dream_dedup import DedupDeps, create_dedup_agent


@pytest.fixture
async def dedup_storage(storage):
    await storage.create_entity(
        name="Python", type="language", description="A programming language"
    )
    await storage.create_entity(
        name="Python 3", type="language", description="Third version of Python"
    )
    return storage


async def test_dedup_agent_runs(dedup_storage):
    """Dedup agent can run without crashing."""
    cancel = asyncio.Event()
    agent = create_dedup_agent()
    deps = DedupDeps(storage=dedup_storage, cancel=cancel)
    result = await agent.run(
        "Process this batch of nodes for deduplication: entity:py, entity:py3",
        deps=deps,
        model=TestModel(),
    )
    assert isinstance(result.output, str)
