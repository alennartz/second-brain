"""Fast-path routing for one conversational turn.

A Jev decision pass classifies the message before the full converse agent runs:
confidently-pure recall or ingest messages dispatch straight to their sub-agent,
skipping the converse LLM router round-trip. Everything else — chat, mixed
intent, low confidence, or any routing failure — falls through to the converse
agent, which remains the fallback router.

This module owns the routing *policy* (question wording, thresholds, dispatch
rules). It depends on Core (models/config types) and PydanticAI only — no
Storage, no Tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, NamedTuple

from pydantic import BaseModel, Field
from pydantic_ai import Agent, BoolCriteria
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.models import Model


class Route(StrEnum):
    """Where a conversational turn should be handled."""

    RECALL = "recall"
    INGEST = "ingest"
    CONVERSE = "converse"  # fall through to today's full converse agent


class RoutingDecision(BaseModel):
    """Fast-path routing for one conversational turn.

    The fields are the Jev questions: the field descriptions say what is being
    asked and the ``BoolCriteria`` say what either answer amounts to.
    """

    is_pure_recall: Annotated[
        bool,
        BoolCriteria(
            true=(
                "The message ONLY asks a question to answer from stored knowledge. "
                "It contains nothing new to store."
            ),
            false="It stores new information, does both, or is small talk/meta.",
        ),
    ] = Field(
        description="Is this message exclusively a question about stored knowledge?"
    )

    is_pure_ingest: Annotated[
        bool,
        BoolCriteria(
            true=(
                "The message ONLY states new information to remember. "
                "It contains no question to answer."
            ),
            false="It asks a question, does both, or is small talk/meta.",
        ),
    ] = Field(description="Is this message exclusively new knowledge to store?")


class RoutingRunResult(NamedTuple):
    """A routing decision with the per-field confidence it was made at."""

    decision: RoutingDecision
    confidence: dict[str, float]  # field name -> confidence from provider_details


@dataclass
class RoutingDeps:
    """Dependencies for the routing agent.

    The routing decision is pure classification over the message text: no
    Storage and no tools, so there is nothing to inject. Threshold and history
    window config are read from settings where the policy needs them.
    """


def create_routing_agent() -> Agent[RoutingDeps, RoutingDecision]:
    """Create the routing agent.

    ``output_type=RoutingDecision`` — the field descriptions and ``BoolCriteria``
    above are the Jev questions.
    """
    raise NotImplementedError("not implemented")


async def route_message(
    routing_agent: Agent[RoutingDeps, RoutingDecision],
    routing_model: Model | str,
    message: str,
    message_history: list[ModelRequest | ModelResponse],
) -> Route | None:
    """Run the routing agent and interpret the result.

    Returns None when no fast-path route is warranted (low confidence, mixed
    intent) — callers then take the CONVERSE fallback. Raises nothing: any
    exception (missing key, 429/529, network) is logged and returns None.
    Confidence absent, nonfinite, or outside [0, 1] is below threshold.
    Routing state includes exactly the most recent configured history turns;
    zero turns means only the current message. Emits a structured decision log
    with route, confidence, threshold, and path (fast/fallback), even on failure.
    """
    raise NotImplementedError("not implemented")


def decide_route(
    decision: RoutingDecision, confidence: dict[str, float], threshold: float
) -> Route:
    """Pure interpretation of a routing decision.

    Both purity flags true always means CONVERSE, regardless of confidence.
    Otherwise RECALL iff is_pure_recall and valid confidence >= threshold;
    symmetric for INGEST. Missing, nonfinite, or out-of-range confidence is
    below threshold. Otherwise CONVERSE.
    """
    raise NotImplementedError("not implemented")
