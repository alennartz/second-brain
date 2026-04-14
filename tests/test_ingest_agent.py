import pytest
from pydantic_ai.models.test import TestModel

from second_brain.agents.ingest import IngestDeps, create_ingest_agent


@pytest.fixture
async def ingest_deps(storage):
    return IngestDeps(storage=storage)


async def test_ingest_agent_has_tools():
    agent = create_ingest_agent()
    tool_names = set(agent._function_toolset.tools)
    # New consolidated tool
    assert "store_knowledge" in tool_names
    # Retained tools
    assert "update_node" in tool_names
    assert "search_knowledge" in tool_names
    assert "get_node" in tool_names
    # Old granular create tools should NOT exist
    assert "create_notes" not in tool_names
    assert "create_entities" not in tool_names
    assert "create_edges" not in tool_names


async def test_ingest_agent_runs(ingest_deps):
    agent = create_ingest_agent()
    result = await agent.run(
        "I've been thinking about how spaced repetition could help with my coding practice",
        deps=ingest_deps,
        model=TestModel(),
    )
    assert result.output is not None
