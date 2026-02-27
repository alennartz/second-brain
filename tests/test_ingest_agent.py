from unittest.mock import AsyncMock

import pytest
from pydantic_ai.models.test import TestModel

from second_brain.agents.ingest import IngestDeps, create_ingest_agent
from second_brain.db import init_schema


@pytest.fixture
async def ingest_deps(db):
    await init_schema(db)
    return IngestDeps(db=db, embed_fn=AsyncMock(return_value=[0.1, 0.2, 0.3]))


async def test_ingest_agent_has_tools():
    agent = create_ingest_agent()
    tool_names = set(agent._function_toolset.tools)
    assert "create_notes" in tool_names
    assert "create_entities" in tool_names
    assert "create_edges" in tool_names
    assert "update_node" in tool_names
    assert "search_knowledge" in tool_names
    assert "get_node" in tool_names
    # Old single-create tools should NOT exist
    assert "create_note" not in tool_names
    assert "create_entity" not in tool_names
    assert "create_edge" not in tool_names


async def test_ingest_agent_runs(ingest_deps):
    agent = create_ingest_agent()
    result = await agent.run(
        "I've been thinking about how spaced repetition could help with my coding practice",
        deps=ingest_deps,
        model=TestModel(),
    )
    assert result.output is not None
