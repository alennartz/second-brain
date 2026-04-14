import pytest
from pydantic_ai.models.test import TestModel

from second_brain.agents.recall import RecallDeps, RecallOutput, create_recall_agent


@pytest.fixture
async def recall_deps(storage):
    note = await storage.create_note(
        content="Spaced repetition improves memory", source="cli", summary="spaced rep"
    )
    entity = await storage.create_entity(name="spaced repetition", type="concept")
    await storage.create_edge(note["id"], "references", entity["id"])
    return RecallDeps(storage=storage)


async def test_recall_agent_has_tools():
    agent = create_recall_agent()
    tool_names = set(agent._function_toolset.tools)
    assert "search_knowledge" in tool_names
    assert "get_node" in tool_names
    # Removed tools should NOT exist
    assert "get_connections" not in tool_names
    assert "graph_traverse" not in tool_names


async def test_recall_agent_runs(recall_deps):
    agent = create_recall_agent()
    result = await agent.run(
        "What do I know about spaced repetition?",
        deps=recall_deps,
        model=TestModel(),
    )
    # With RecallOutput, result.output should be a RecallOutput instance
    assert isinstance(result.output, RecallOutput)
    assert isinstance(result.output.answer, str)
    assert isinstance(result.output.cited_node_ids, list)
    assert isinstance(result.output.cited_edge_ids, list)
