import asyncio

import pytest
from pydantic_ai.models.test import TestModel

from second_brain.agents.dream_connect import ConnectDeps, create_connect_agent


@pytest.fixture
async def connect_storage(storage):
    py = await storage.create_entity(name="Python", type="language")
    fa = await storage.create_entity(name="FastAPI", type="framework")
    note = await storage.create_note(content="FastAPI uses Python", source="cli")
    await storage.create_edge(note["id"], "references", py["id"])
    await storage.create_edge(note["id"], "references", fa["id"])
    return storage


async def test_connect_agent_runs(connect_storage):
    """Connect agent can run without crashing."""
    cancel = asyncio.Event()
    agent = create_connect_agent()
    deps = ConnectDeps(storage=connect_storage, cancel=cancel)
    result = await agent.run(
        "Explore connections for these nodes: entity:py, entity:fa",
        deps=deps,
        model=TestModel(),
    )
    assert isinstance(result.output, str)
