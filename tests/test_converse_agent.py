import asyncio
import json
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from second_brain.agents.converse import ConverseDeps, run_converse_turn
from second_brain.config import settings


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


# ---------------------------------------------------------------------------
# run_converse_turn — fast-path orchestration shared by both API paths
# ---------------------------------------------------------------------------

RECALL_ANSWER = "Spaced repetition improves memory."
INGEST_ANSWER = "Stored."


def routing_model(
    *,
    recall: bool = False,
    ingest: bool = False,
    confidence: dict[str, float] | None = None,
    fail: bool = False,
    seen: list[list[ModelMessage]] | None = None,
) -> FunctionModel:
    """A routing model double: answers the routing questions deterministically
    and carries per-field confidence through provider_details the way the
    TypeSafe decision model does (`provider_details['confidence']` keyed by
    field name)."""

    async def respond(messages: list[ModelMessage], info: Any) -> ModelResponse:
        if seen is not None:
            seen.append(list(messages))
        if fail:
            raise RuntimeError("routing service unavailable")
        args = {"is_pure_recall": recall, "is_pure_ingest": ingest}
        if info.output_tools:
            part = ToolCallPart(info.output_tools[0].name, args)
        else:
            part = TextPart(json.dumps(args))
        return ModelResponse(
            parts=[part], provider_details={"confidence": confidence or {}}
        )

    return FunctionModel(respond)


def echo_converse_model(
    text: str = "fallback", seen: list[list[ModelMessage]] | None = None
) -> FunctionModel:
    """A converse model double: answers with fixed text and records its state."""

    async def respond(messages: list[ModelMessage], info: Any) -> ModelResponse:
        if seen is not None:
            seen.append(list(messages))
        return ModelResponse(parts=[TextPart(text)])

    return FunctionModel(respond)


def relay_converse_model(tool_name: str, arg_name: str) -> FunctionModel:
    """A converse model double: pass the user's message to the given sub-agent
    tool, then relay the tool's return verbatim — what the system prompt
    instructs."""

    async def respond(messages: list[ModelMessage], info: Any) -> ModelResponse:
        for message in reversed(messages):
            for part in message.parts:
                if isinstance(part, ToolReturnPart) and part.tool_name == tool_name:
                    return ModelResponse(parts=[TextPart(str(part.content))])
        question = next(
            part.content
            for message in reversed(messages)
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name, {arg_name: question}, tool_call_id="relay_call_1"
                )
            ]
        )

    return FunctionModel(respond)


def _drain(queue: asyncio.Queue) -> list:
    events = []
    while True:
        try:
            events.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return events


def _state_texts(messages: list[ModelMessage]) -> list[str]:
    """The text contents visible in a model's conversation state."""
    texts: list[str] = []
    for message in messages:
        for part in message.parts:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                texts.append(content)
    return texts


async def test_run_converse_turn_fast_recall_matches_converse_tool_path(storage):
    """A RECALL-routed turn must produce the same response and the same context
    accumulation as a turn where the converse LLM router chose the recall tool."""
    note = await storage.create_note(
        content="Spaced repetition improves memory", source="test"
    )
    entity = await storage.create_entity(name="spaced repetition", type="concept")
    edge = await storage.create_edge(note["id"], "references", entity["id"])
    recall_args = {
        "answer": RECALL_ANSWER,
        "cited_node_ids": [str(note["id"])],
        "cited_edge_ids": [str(edge["id"])],
    }
    history = [
        ModelRequest(parts=[UserPromptPart(content="Hi!")]),
        ModelResponse(parts=[TextPart(content="Hello there.")]),
    ]
    message = "What do I know about spaced repetition?"

    q_fast: asyncio.Queue = asyncio.Queue()
    deps_fast = ConverseDeps(
        storage=storage,
        model_setting=TestModel(call_tools=[], custom_output_args=recall_args),
        progress_queue=q_fast,
    )
    resp_fast = await run_converse_turn(
        message,
        history,
        deps=deps_fast,
        model=echo_converse_model("converse agent must not run"),
        routing_model=routing_model(
            recall=True,
            confidence={"is_pure_recall": 0.99, "is_pure_ingest": 0.01},
        ),
    )

    q_tool: asyncio.Queue = asyncio.Queue()
    deps_tool = ConverseDeps(
        storage=storage,
        model_setting=TestModel(call_tools=[], custom_output_args=recall_args),
        progress_queue=q_tool,
    )
    resp_tool = await run_converse_turn(
        message,
        history,
        deps=deps_tool,
        model=relay_converse_model("recall", "question"),
        routing_model=None,
    )

    assert resp_fast == resp_tool == RECALL_ANSWER

    fast_nodes = sorted(str(n["id"]) for n in deps_fast.context.nodes)
    tool_nodes = sorted(str(n["id"]) for n in deps_tool.context.nodes)
    assert fast_nodes == tool_nodes == [str(note["id"])]
    fast_edges = sorted(str(e["id"]) for e in deps_fast.context.edges)
    tool_edges = sorted(str(e["id"]) for e in deps_tool.context.edges)
    assert fast_edges == tool_edges == [str(edge["id"])]

    statuses_fast = _drain(q_fast)
    statuses_tool = _drain(q_tool)
    assert statuses_fast  # status events are emitted on every path
    assert statuses_fast == statuses_tool


async def test_run_converse_turn_fast_ingest_matches_converse_tool_path(storage):
    """An INGEST-routed turn is a shortcut to the same pipeline the converse
    ingest tool runs."""
    ingest_text = "Spaced repetition improves memory."

    q_fast: asyncio.Queue = asyncio.Queue()
    deps_fast = ConverseDeps(
        storage=storage,
        model_setting=TestModel(call_tools=[], custom_output_text=INGEST_ANSWER),
        progress_queue=q_fast,
    )
    resp_fast = await run_converse_turn(
        ingest_text,
        [],
        deps=deps_fast,
        model=echo_converse_model("converse agent must not run"),
        routing_model=routing_model(
            ingest=True,
            confidence={"is_pure_recall": 0.01, "is_pure_ingest": 0.99},
        ),
    )

    q_tool: asyncio.Queue = asyncio.Queue()
    deps_tool = ConverseDeps(
        storage=storage,
        model_setting=TestModel(call_tools=[], custom_output_text=INGEST_ANSWER),
        progress_queue=q_tool,
    )
    resp_tool = await run_converse_turn(
        ingest_text,
        [],
        deps=deps_tool,
        model=relay_converse_model("ingest", "text"),
        routing_model=None,
    )

    assert resp_fast == resp_tool == INGEST_ANSWER
    assert deps_fast.context.nodes == deps_tool.context.nodes
    assert deps_fast.context.edges == deps_tool.context.edges

    statuses_fast = _drain(q_fast)
    statuses_tool = _drain(q_tool)
    assert statuses_fast
    assert statuses_fast == statuses_tool


async def test_run_converse_turn_mixed_intent_falls_back_to_converse(storage):
    deps = ConverseDeps(storage=storage, model_setting=TestModel())
    resp = await run_converse_turn(
        "Remember that spaced repetition improves memory. What do I know about it?",
        [],
        deps=deps,
        model=echo_converse_model("fallback"),
        routing_model=routing_model(
            recall=True,
            ingest=True,
            confidence={"is_pure_recall": 1.0, "is_pure_ingest": 1.0},
        ),
    )
    assert resp == "fallback"


async def test_run_converse_turn_routing_failure_falls_back_to_converse(storage):
    deps = ConverseDeps(storage=storage, model_setting=TestModel())
    resp = await run_converse_turn(
        "What do I know about spaced repetition?",
        [],
        deps=deps,
        model=echo_converse_model("fallback"),
        routing_model=routing_model(fail=True),
    )
    assert resp == "fallback"


async def test_run_converse_turn_without_routing_model_always_uses_converse_agent(
    storage,
):
    # Even a message that reads like pure recall goes to the converse agent when
    # no routing model exists (test mode / jev disabled).
    deps = ConverseDeps(storage=storage, model_setting=TestModel())
    resp = await run_converse_turn(
        "What do I know about spaced repetition?",
        [],
        deps=deps,
        model=echo_converse_model("fallback"),
        routing_model=None,
    )
    assert resp == "fallback"


async def test_run_converse_turn_converse_fallback_gets_full_history(storage):
    history = [
        ModelRequest(parts=[UserPromptPart(content="What is memory?")]),
        ModelResponse(parts=[TextPart(content="Memory is retention.")]),
        ModelRequest(parts=[UserPromptPart(content="And forgetting?")]),
        ModelResponse(parts=[TextPart(content="Forgetting is loss.")]),
    ]
    message = "Tell me more."
    seen_converse: list[list[ModelMessage]] = []
    deps = ConverseDeps(storage=storage, model_setting=TestModel())
    resp = await run_converse_turn(
        message,
        history,
        deps=deps,
        model=echo_converse_model("fallback", seen=seen_converse),
        routing_model=routing_model(
            recall=False,
            ingest=False,
            confidence={"is_pure_recall": 0.9, "is_pure_ingest": 0.9},
        ),
    )
    assert resp == "fallback"
    texts = _state_texts(seen_converse[0])
    for expected in [
        "What is memory?",
        "Memory is retention.",
        "And forgetting?",
        "Forgetting is loss.",
        message,
    ]:
        assert expected in texts


async def test_run_converse_turn_routing_state_is_bounded_by_configured_window(
    storage, monkeypatch
):
    monkeypatch.setattr(settings, "jev_history_turns", 2)
    history_contents = [
        text for i in range(12) for text in (f"history {i}", f"reply {i}")
    ]
    history = [
        part
        for i, text in enumerate(history_contents)
        for part in (
            [ModelRequest(parts=[UserPromptPart(content=text)])]
            if i % 2 == 0
            else [ModelResponse(parts=[TextPart(content=text)])]
        )
    ]
    message = "latest message"
    seen_routing: list[list[ModelMessage]] = []
    deps = ConverseDeps(storage=storage, model_setting=TestModel())
    await run_converse_turn(
        message,
        history,
        deps=deps,
        model=echo_converse_model("fallback"),
        routing_model=routing_model(
            recall=False,
            ingest=False,
            confidence={"is_pure_recall": 0.9, "is_pure_ingest": 0.9},
            seen=seen_routing,
        ),
    )
    texts = _state_texts(seen_routing[0])
    assert message in texts
    retained = [t for t in texts if t != message]
    # At most the configured number of user/assistant turns (2 messages each) of
    # history, and never anything but the most recent contiguous stretch.
    assert len(retained) <= 2 * settings.jev_history_turns
    if retained:
        assert retained == history_contents[-len(retained) :]
