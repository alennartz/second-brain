"""Behavioral tests for the fast-path routing decision module (`agents/routing.py`)."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel

from second_brain.agents.routing import (
    Route,
    RoutingDecision,
    create_routing_agent,
    decide_route,
    route_message,
)
from second_brain.config import settings


def routing_model(
    *,
    recall: bool = False,
    ingest: bool = False,
    confidence: dict[str, float] | None = None,
    fail: bool = False,
    seen: list[list[ModelMessage]] | None = None,
) -> FunctionModel:
    """A routing model double: answers the RoutingDecision questions
    deterministically and carries per-field confidence through provider_details
    the way the TypeSafe decision model does (`provider_details['confidence']`
    keyed by field name)."""

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


def _state_texts(messages: list[ModelMessage]) -> list[str]:
    """The text contents visible in a model's conversation state."""
    texts: list[str] = []
    for message in messages:
        for part in message.parts:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                texts.append(content)
    return texts


# ---------------------------------------------------------------------------
# decide_route — pure interpretation of a decision + confidences
# ---------------------------------------------------------------------------


def test_decide_route_confident_pure_recall_routes_recall():
    decision = RoutingDecision(is_pure_recall=True, is_pure_ingest=False)
    route = decide_route(
        decision, {"is_pure_recall": 0.95, "is_pure_ingest": 0.05}, threshold=0.9
    )
    assert route is Route.RECALL


def test_decide_route_confident_pure_ingest_routes_ingest():
    decision = RoutingDecision(is_pure_recall=False, is_pure_ingest=True)
    route = decide_route(
        decision, {"is_pure_recall": 0.05, "is_pure_ingest": 0.95}, threshold=0.9
    )
    assert route is Route.INGEST


def test_decide_route_mixed_intent_is_never_fast_pathed():
    # Both flags claim purity — that contradiction must land on CONVERSE
    # no matter how confident each answer claims to be.
    decision = RoutingDecision(is_pure_recall=True, is_pure_ingest=True)
    route = decide_route(
        decision, {"is_pure_recall": 1.0, "is_pure_ingest": 1.0}, threshold=0.9
    )
    assert route is Route.CONVERSE


def test_decide_route_small_talk_goes_converse():
    decision = RoutingDecision(is_pure_recall=False, is_pure_ingest=False)
    route = decide_route(
        decision, {"is_pure_recall": 0.9, "is_pure_ingest": 0.9}, threshold=0.9
    )
    assert route is Route.CONVERSE


def test_decide_route_low_confidence_falls_back_to_converse():
    decision = RoutingDecision(is_pure_recall=True, is_pure_ingest=False)
    route = decide_route(
        decision, {"is_pure_recall": 0.5, "is_pure_ingest": 0.1}, threshold=0.9
    )
    assert route is Route.CONVERSE


def test_decide_route_confidence_equal_to_threshold_routes():
    # >= is sufficient: confidence exactly at the threshold takes the fast path.
    decision = RoutingDecision(is_pure_recall=True, is_pure_ingest=False)
    route = decide_route(
        decision, {"is_pure_recall": 0.9, "is_pure_ingest": 0.0}, threshold=0.9
    )
    assert route is Route.RECALL


def test_decide_route_confident_recall_wins_over_unconfident_ingest_flag():
    # is_pure_ingest is set but unconfident, so it must not block the recall fast path.
    decision = RoutingDecision(is_pure_recall=True, is_pure_ingest=True)
    route = decide_route(
        decision, {"is_pure_recall": 0.95, "is_pure_ingest": 0.4}, threshold=0.9
    )
    assert route is Route.RECALL


def test_decide_route_confident_ingest_wins_over_unconfident_recall_flag():
    decision = RoutingDecision(is_pure_recall=True, is_pure_ingest=True)
    route = decide_route(
        decision, {"is_pure_recall": 0.4, "is_pure_ingest": 0.95}, threshold=0.9
    )
    assert route is Route.INGEST


# ---------------------------------------------------------------------------
# route_message — running the routing agent and interpreting its result
# ---------------------------------------------------------------------------


async def test_route_message_confident_pure_recall_routes_recall():
    route = await route_message(
        create_routing_agent(),
        routing_model(
            recall=True,
            confidence={"is_pure_recall": 0.99, "is_pure_ingest": 0.01},
        ),
        "What do I know about spaced repetition?",
        [],
    )
    assert route is Route.RECALL


async def test_route_message_confident_pure_ingest_routes_ingest():
    route = await route_message(
        create_routing_agent(),
        routing_model(
            ingest=True,
            confidence={"is_pure_recall": 0.01, "is_pure_ingest": 0.99},
        ),
        "Spaced repetition improves memory.",
        [],
    )
    assert route is Route.INGEST


async def test_route_message_mixed_intent_takes_no_fast_path():
    route = await route_message(
        create_routing_agent(),
        routing_model(
            recall=True,
            ingest=True,
            confidence={"is_pure_recall": 1.0, "is_pure_ingest": 1.0},
        ),
        "Remember that spaced repetition improves memory. What do I know about it?",
        [],
    )
    assert route is None or route is Route.CONVERSE


async def test_route_message_low_confidence_takes_no_fast_path():
    threshold = settings.jev_confidence_threshold
    route = await route_message(
        create_routing_agent(),
        routing_model(
            recall=True,
            confidence={
                "is_pure_recall": threshold - 0.05,
                "is_pure_ingest": 0.0,
            },
        ),
        "What do I know about spaced repetition?",
        [],
    )
    assert route is None or route is Route.CONVERSE


async def test_route_message_confidence_equal_to_settings_threshold_routes():
    threshold = settings.jev_confidence_threshold
    route = await route_message(
        create_routing_agent(),
        routing_model(
            recall=True,
            confidence={"is_pure_recall": threshold, "is_pure_ingest": 0.0},
        ),
        "What do I know about spaced repetition?",
        [],
    )
    assert route is Route.RECALL


async def test_route_message_honors_configured_threshold(monkeypatch):
    monkeypatch.setattr(settings, "jev_confidence_threshold", 0.3)
    route = await route_message(
        create_routing_agent(),
        routing_model(
            recall=True,
            confidence={"is_pure_recall": 0.5, "is_pure_ingest": 0.0},
        ),
        "What do I know about spaced repetition?",
        [],
    )
    assert route is Route.RECALL


async def test_route_message_routing_failure_returns_none_and_is_logged(caplog):
    caplog.set_level(logging.DEBUG)
    route = await route_message(
        create_routing_agent(),
        routing_model(fail=True),
        "What do I know about spaced repetition?",
        [],
    )
    assert route is None
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


async def test_route_message_includes_recent_history_in_routing_state():
    history = [
        ModelRequest(parts=[UserPromptPart(content="What is memory?")]),
        ModelResponse(parts=[TextPart(content="Memory is retention of information.")]),
    ]
    seen: list[list[ModelMessage]] = []
    route = await route_message(
        create_routing_agent(),
        routing_model(
            recall=True,
            confidence={"is_pure_recall": 0.99, "is_pure_ingest": 0.01},
            seen=seen,
        ),
        "And forgetting?",
        history,
    )
    assert route is Route.RECALL
    texts = _state_texts(seen[0])
    assert "And forgetting?" in texts
    assert "What is memory?" in texts
    assert "Memory is retention of information." in texts
