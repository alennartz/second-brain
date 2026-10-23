from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from pydantic_ai import UsageLimits
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models.test import TestModel

from second_brain.agents.recall import (
    RECALL_MAX_NODE_FETCHES,
    RECALL_RECORD_ID_MAX_CHARS,
    RECALL_SEARCH_QUERY_MAX_CHARS,
    RECALL_TOOL_CALL_LIMIT,
    RecallDeps,
    RecallOutput,
    RecallOutputError,
    RecallRunLimitExceeded,
    _parse_recall_json,
    create_recall_agent,
    run_recall,
)


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
    output = await run_recall(
        "What do I know about spaced repetition?",
        deps=recall_deps,
        model=TestModel(
            call_tools=[],
            custom_output_text=(
                'thought\n{"answer": null, "has_evidence": false, '
                '"cited_node_ids": [], "cited_edge_ids": [], '
                '"cited_unprocessed_ids": []}'
            ),
        ),
        agent=agent,
    )
    assert isinstance(output, RecallOutput)
    assert output.answer is None or isinstance(output.answer, str)
    assert isinstance(output.cited_node_ids, list)
    assert isinstance(output.cited_edge_ids, list)
    assert isinstance(output.cited_unprocessed_ids, list)


async def test_recall_answer_turn_is_plain_text_not_an_output_tool():
    agent = create_recall_agent()
    # TextOutput mode: the final reply is parsed from text, not a synthetic tool.
    assert agent._output_schema.mode == "text"
    assert agent._output_schema.toolset is None
    # Exploration tools stay real; no synthetic final_result tool is registered.
    assert "final_result" not in agent._function_toolset.tools


def test_recall_output_requires_citation_fields():
    schema = RecallOutput.model_json_schema()
    assert set(schema["required"]) == {
        "answer",
        "has_evidence",
        "cited_node_ids",
        "cited_edge_ids",
        "cited_unprocessed_ids",
    }
    assert schema["properties"]["cited_node_ids"]["maxItems"] == 20
    assert schema["properties"]["cited_edge_ids"]["maxItems"] == 40
    assert schema["properties"]["cited_unprocessed_ids"]["maxItems"] == 20


def test_recall_output_requires_evidence_for_substantive_answers():
    with pytest.raises(ValidationError, match="at least one citation"):
        RecallOutput(
            answer="A factual answer without evidence.",
            has_evidence=True,
            cited_node_ids=[],
            cited_edge_ids=[],
            cited_unprocessed_ids=[],
        )


def test_recall_output_leaves_citation_resolution_to_storage():
    output = RecallOutput(
        answer="A possible answer.",
        has_evidence=True,
        cited_node_ids=["not-a-record-id"],
        cited_edge_ids=["entity:not-an-edge"],
        cited_unprocessed_ids=["note:not-an-intake-chunk"],
    )
    assert output.cited_node_ids == ["not-a-record-id"]
    assert output.cited_edge_ids == ["entity:not-an-edge"]
    assert output.cited_unprocessed_ids == ["note:not-an-intake-chunk"]


def test_recall_output_allows_an_explicit_no_evidence_answer():
    output = RecallOutput(
        answer=None,
        has_evidence=False,
        cited_node_ids=[],
        cited_edge_ids=[],
        cited_unprocessed_ids=[],
    )
    assert not output.has_evidence
    assert output.answer is None


async def test_recall_limits_tool_calls_and_disables_parallel_tools(storage):
    agent = create_recall_agent()
    assert agent.model_settings == {"parallel_tool_calls": False}

    fake_agent = Mock()
    fake_agent.run = AsyncMock(
        return_value=SimpleNamespace(
            output=RecallOutput(
                answer=None,
                has_evidence=False,
                cited_node_ids=[],
                cited_edge_ids=[],
                cited_unprocessed_ids=[],
            )
        )
    )
    await run_recall(
        "A question",
        deps=RecallDeps(storage=storage),
        model=TestModel(),
        agent=fake_agent,
    )
    usage_limits = fake_agent.run.await_args.kwargs["usage_limits"]
    assert isinstance(usage_limits, UsageLimits)
    assert usage_limits.tool_calls_limit == RECALL_TOOL_CALL_LIMIT
    assert usage_limits.request_limit < 50


async def test_recall_translates_tool_limit_to_domain_error(storage):
    fake_agent = Mock()
    fake_agent.run = AsyncMock(side_effect=UsageLimitExceeded("tool limit"))

    with pytest.raises(RecallRunLimitExceeded, match="tool limit"):
        await run_recall(
            "A question",
            deps=RecallDeps(storage=storage),
            model=TestModel(),
            agent=fake_agent,
        )


async def test_recall_no_evidence_reply_falls_back_to_stable_text(recall_deps):
    output = await run_recall(
        "Unknown topic?",
        deps=recall_deps,
        model=TestModel(
            call_tools=[],
            custom_output_text=(
                'thought\n{"answer": null, "has_evidence": false, '
                '"cited_node_ids": [], "cited_edge_ids": [], '
                '"cited_unprocessed_ids": []}'
            ),
        ),
    )
    assert output.has_evidence is False
    assert output.answer is None


def test_recall_tool_schemas_bound_arguments():
    agent = create_recall_agent()
    search_schema = agent._function_toolset.tools[
        "search_knowledge"
    ].function_schema.json_schema
    node_schema = agent._function_toolset.tools["get_node"].function_schema.json_schema

    assert (
        search_schema["properties"]["query"]["maxLength"]
        == RECALL_SEARCH_QUERY_MAX_CHARS
    )
    assert search_schema["properties"]["k"]["minimum"] == 1
    assert search_schema["properties"]["k"]["maximum"] == 5
    assert (
        node_schema["properties"]["record_id"]["maxLength"]
        == RECALL_RECORD_ID_MAX_CHARS
    )
    assert "pattern" not in repr(search_schema)
    assert "pattern" not in repr(node_schema)


def test_recall_dependencies_bound_searches_and_node_reads(storage):
    deps = RecallDeps(storage=storage)
    assert deps.search_denial("Saturn V", 5) is None
    assert deps.search_denial(" saturn   v ", 5) == "duplicate"
    assert deps.search_denial("Moon race", 5) is None
    assert deps.search_denial("V-2 rocket", 5) == "budget"

    deps.remember_graph_nodes(
        [{"id": "entity:saturn", "connections": [{"adjacent_id": "entity:apollo"}]}]
    )
    assert deps.node_fetch_denial("entity:saturn") is None
    assert deps.node_fetch_denial("entity:saturn") == "duplicate"
    assert deps.node_fetch_denial("entity:invented") == "unknown"
    assert deps.node_fetch_denial("entity:apollo") is None

    more_nodes = [
        {"id": f"entity:{index}", "connections": []}
        for index in range(RECALL_MAX_NODE_FETCHES + 1)
    ]
    deps.remember_graph_nodes(more_nodes)
    for index in range(2, RECALL_MAX_NODE_FETCHES):
        assert deps.node_fetch_denial(f"entity:{index}") is None
    assert deps.node_fetch_denial(f"entity:{RECALL_MAX_NODE_FETCHES}") == "budget"


def test_recall_output_parse_error_is_logged_without_raw_text(caplog):
    private_text = '{"answer":"private marker","has_evidence":false,}'

    with pytest.raises(RecallOutputError, match="not valid JSON"):
        _parse_recall_json(private_text)

    assert "invalid JSON" in caplog.text
    assert "private marker" not in caplog.text
