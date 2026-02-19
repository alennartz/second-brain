from unittest.mock import AsyncMock

from pydantic_ai.models.test import TestModel

from second_brain.db import init_schema


async def test_converse_agent_has_tools():
    from second_brain.agents.converse import create_converse_agent

    agent = create_converse_agent()
    tool_names = set(agent._function_toolset.tools.keys())
    assert "recall" in tool_names
    assert "ingest" in tool_names


async def test_converse_agent_runs(db):
    from second_brain.agents.converse import ConverseDeps, create_converse_agent

    await init_schema(db)
    deps = ConverseDeps(
        db=db,
        embed_fn=AsyncMock(return_value=[0.1, 0.2, 0.3]),
        model_setting=TestModel(),
    )
    agent = create_converse_agent()
    result = await agent.run(
        "What do I know about testing?",
        deps=deps,
        model=TestModel(),
    )
    assert isinstance(result.output, str)
