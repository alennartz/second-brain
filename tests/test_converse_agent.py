from pydantic_ai.models.test import TestModel


async def test_converse_agent_has_tools():
    from second_brain.agents.converse import create_converse_agent

    agent = create_converse_agent()
    tool_names = set(agent._function_toolset.tools.keys())
    assert "recall" in tool_names
    assert "ingest" in tool_names


async def test_converse_agent_runs(storage):
    from second_brain.agents.converse import ConverseDeps, create_converse_agent

    deps = ConverseDeps(
        storage=storage,
        model_setting=TestModel(),
    )
    agent = create_converse_agent()
    result = await agent.run(
        "What do I know about testing?",
        deps=deps,
        model=TestModel(),
    )
    assert isinstance(result.output, str)
