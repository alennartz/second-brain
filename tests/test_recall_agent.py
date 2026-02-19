import pytest
from pydantic_ai.models.test import TestModel

from second_brain.agents.recall import RecallDeps, RecallOutput, create_recall_agent
from second_brain.db import init_schema


@pytest.fixture
async def recall_deps(db):
    await init_schema(db)
    await db.query("""
        CREATE note:1 SET content = 'Spaced repetition improves memory',
            summary = 'spaced rep', source = 'cli';
        CREATE entity:sr SET name = 'spaced repetition', type = 'concept';
        RELATE note:1->references->entity:sr;
    """)
    return RecallDeps(db=db)


async def test_recall_agent_has_tools():
    agent = create_recall_agent()
    tool_names = set(agent._function_toolset.tools)
    assert "full_text_search" in tool_names
    assert "get_node" in tool_names
    assert "get_connections" in tool_names
    assert "graph_traverse" in tool_names


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
