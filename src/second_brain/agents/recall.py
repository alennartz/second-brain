import json
import logging
from collections.abc import AsyncIterable
from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_ai import Agent, RunContext, TextOutput, UsageLimits
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    RetryPromptPart,
)

from second_brain.db import Storage, project_intake_evidence
from second_brain.models import Context, normalize_edge, normalize_node
from second_brain.tools import recall_tools

logger = logging.getLogger(__name__)

RECALL_SEARCH_RESULT_LIMIT = 5
RECALL_SEARCH_QUERY_MAX_CHARS = 256
RECALL_RECORD_ID_MAX_CHARS = 120
RECALL_MAX_UNIQUE_SEARCHES = 2
RECALL_MAX_NODE_FETCHES = 6
RECALL_TOOL_CALL_LIMIT = 8
RECALL_REQUEST_LIMIT = 12
NO_EVIDENCE_ANSWER = "I couldn't find relevant information in your knowledge base."
RecallRecordId = Annotated[
    str, Field(min_length=1, max_length=RECALL_RECORD_ID_MAX_CHARS)
]


class RecallOutput(BaseModel):
    answer: str | None = Field(max_length=2000)
    has_evidence: bool
    cited_node_ids: list[RecallRecordId] = Field(max_length=20)
    cited_edge_ids: list[RecallRecordId] = Field(max_length=40)
    cited_unprocessed_ids: list[RecallRecordId] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_evidence_citations(self) -> "RecallOutput":
        has_citations = bool(
            self.cited_node_ids or self.cited_edge_ids or self.cited_unprocessed_ids
        )
        if self.has_evidence:
            if not self.answer or not self.answer.strip():
                raise ValueError("An evidence-backed answer must include answer text")
            if not has_citations:
                raise ValueError(
                    "An evidence-backed answer must include at least one citation"
                )
        elif self.answer is not None or has_citations:
            raise ValueError(
                "A no-evidence response must use a null answer and empty citation arrays"
            )

        return self


@dataclass
class RecallDeps:
    storage: Storage
    _searched_queries: set[tuple[str, int]] = field(default_factory=set, repr=False)
    _fetched_node_ids: set[str] = field(default_factory=set, repr=False)
    _available_node_ids: set[str] = field(default_factory=set, repr=False)

    def search_denial(self, query: str, k: int) -> str | None:
        key = (" ".join(query.casefold().split()), k)
        if key in self._searched_queries:
            return "duplicate"
        if len(self._searched_queries) >= RECALL_MAX_UNIQUE_SEARCHES:
            return "budget"
        self._searched_queries.add(key)
        return None

    def remember_graph_nodes(self, nodes: list[dict]) -> None:
        for node in nodes:
            record_id = node.get("id")
            if isinstance(record_id, str):
                self._available_node_ids.add(record_id)
            for connection in node.get("connections", []):
                adjacent_id = connection.get("adjacent_id")
                if isinstance(adjacent_id, str):
                    self._available_node_ids.add(adjacent_id)

    def node_fetch_denial(self, record_id: str) -> str | None:
        if record_id in self._fetched_node_ids:
            return "duplicate"
        if record_id not in self._available_node_ids:
            return "unknown"
        if len(self._fetched_node_ids) >= RECALL_MAX_NODE_FETCHES:
            return "budget"
        self._fetched_node_ids.add(record_id)
        return None


class RecallRunLimitExceeded(RuntimeError):
    """Raised when recall cannot finish within its output or exploration budget."""


class RecallCitationError(RuntimeError):
    """Raised when a required recall citation cannot be resolved to evidence."""


class RecallOutputError(RuntimeError):
    """Raised when the model's final JSON cannot be parsed or validated."""


def _validation_issues_for_log(details: object) -> list[dict[str, str]]:
    if isinstance(details, str):
        return [{"path": "$", "type": "model_retry", "message": details[:200]}]
    if not isinstance(details, list):
        return [
            {
                "path": "$",
                "type": type(details).__name__,
                "message": "Validation failed",
            }
        ]
    issues = []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        location = detail.get("loc", ())
        if not isinstance(location, (list, tuple)):
            location = (location,)
        error_type = str(detail.get("type", "validation_error"))
        message = str(detail.get("msg", "Validation failed"))
        if error_type == "value_error":
            if "Invalid record ID:" in message:
                message = "Invalid record ID"
            else:
                message = message.removeprefix("Value error, ")
        issues.append(
            {
                "path": ".".join(str(part) for part in location) or "$",
                "type": error_type,
                "message": message[:200],
            }
        )
    return issues or [
        {"path": "$", "type": "validation_error", "message": "No error details"}
    ]


def context_has_evidence(context: Context) -> bool:
    return bool(context.nodes or context.edges or context.unprocessed)


def require_resolved_citations(output: RecallOutput, context: Context) -> None:
    if output.has_evidence and not context_has_evidence(context):
        raise RecallCitationError(
            "Recall returned citations, but none resolved to stored evidence"
        )
    if not output.has_evidence and context_has_evidence(context):
        raise RecallCitationError(
            "Recall returned evidence without declaring or citing it"
        )


async def fetch_cited_context(storage: Storage, output: RecallOutput) -> Context:
    """Fetch cited graph records and unprocessed intake evidence."""
    node_ids = [
        record_id
        for record_id in output.cited_node_ids
        if record_id.split(":", 1)[0] in {"note", "entity"}
    ]
    fetched_nodes = await storage.get_nodes(node_ids)
    nodes = [normalize_node(node) for node in fetched_nodes]

    edges: list[dict] = []
    for edge_id in output.cited_edge_ids:
        try:
            edge = await storage.get_edge(edge_id)
        except ValueError:
            logger.warning("Recall citations: skipping malformed edge ID %r", edge_id)
            continue
        if edge:
            edges.append(normalize_edge(edge))

    unprocessed: list[dict] = []
    if output.cited_unprocessed_ids:
        chunks = await storage.get_intake_chunks(output.cited_unprocessed_ids)
        for chunk in chunks:
            evidence = project_intake_evidence(chunk)
            evidence["unprocessed"] = True
            evidence.pop("connections", None)
            unprocessed.append(evidence)

    return Context(nodes=nodes, edges=edges, unprocessed=unprocessed)


def _parse_recall_json(text: str) -> RecallOutput:
    """Parse the model's JSON-text reply into a RecallOutput."""
    start, end = text.find("{"), text.rfind("}") + 1
    if start < 0 or end <= start:
        logger.warning("recall: final output had no JSON object chars=%d", len(text))
        raise RecallOutputError("reply contained no JSON object")
    try:
        data = json.loads(text[start:end])
    except json.JSONDecodeError as exc:
        logger.warning(
            "recall: final output was invalid JSON line=%d column=%d chars=%d",
            exc.lineno,
            exc.colno,
            len(text),
        )
        raise RecallOutputError("reply was not valid JSON") from exc
    try:
        return RecallOutput.model_validate(data)
    except ValidationError as exc:
        issues = _validation_issues_for_log(
            exc.errors(include_url=False, include_context=False, include_input=False)
        )
        logger.warning(
            "recall: final output failed schema validation issues=%s",
            json.dumps(issues, ensure_ascii=False),
        )
        raise RecallOutputError("reply JSON did not match the recall schema") from exc


def _make_recall_event_handler(downstream: Any = None):
    """Log tool activity while preserving any caller-provided event handler."""

    async def handler(ctx: Any, events: AsyncIterable[Any]) -> None:
        async def instrumented_events():
            async for event in events:
                if isinstance(event, FunctionToolCallEvent):
                    logger.info(
                        "recall: tool call name=%s args_valid=%s",
                        event.part.tool_name,
                        event.args_valid,
                    )
                elif isinstance(event, FunctionToolResultEvent) and isinstance(
                    event.part, RetryPromptPart
                ):
                    issues = _validation_issues_for_log(event.part.content)
                    logger.warning(
                        "recall: tool arguments rejected tool=%s issues=%s",
                        event.part.tool_name or "unknown",
                        json.dumps(issues, ensure_ascii=False),
                    )
                yield event

        if downstream is not None:
            await downstream(ctx, instrumented_events())
        else:
            async for _event in instrumented_events():
                pass

    return handler


def create_recall_agent() -> Agent[RecallDeps, RecallOutput]:
    """Create a recall agent whose final reply is JSON text, not an output tool.

    Exploration uses real tools. The model ends the run by writing one JSON
    object as plain text; Gemma on SGLang degrades when a synthetic
    ``final_result`` tool competes with the real tools.
    """
    agent = Agent(
        deps_type=RecallDeps,
        output_type=TextOutput(_parse_recall_json),
        model_settings={"parallel_tool_calls": False},
        system_prompt=(
            "You are a personal knowledge recall agent. Explore the user's memory "
            "in two stages.\n\n"
            "First, search once with a concise query. Make a second distinct search only "
            "if the first returns no useful evidence. Never issue query variants after you "
            "have relevant nodes or unprocessed evidence. The application permits at most "
            "two distinct searches.\n\n"
            "Then walk the graph. Call get_node only for an ID in search results or in a "
            "node's connections. Fetch each node once, and follow only new adjacent IDs. "
            "The application permits at most six distinct node reads. If a tool reports "
            "that its budget is exhausted, stop exploring and use the evidence already "
            "collected. Never invent IDs or repeat a node read.\n\n"
            "Make at most 1 or 2 tool calls per turn. Read each result before choosing "
            "the next action. Stop as soon as you have enough evidence.\n\n"
            "End your run by replying with ONLY one JSON object, no other text:\n"
            '{"answer": string or null, "has_evidence": boolean, '
            '"cited_node_ids": [string], "cited_edge_ids": [string], '
            '"cited_unprocessed_ids": [string]}\n'
            "Every factual answer from memory must cite at least one source ID: set "
            "has_evidence=true and include all supporting IDs in the matching citation "
            "arrays. Cite graph nodes in cited_node_ids, graph edges in cited_edge_ids, "
            "and raw intake chunks in cited_unprocessed_ids.\n\n"
            "If the knowledge base has no relevant evidence, set has_evidence=false, "
            "answer=null, and return empty citation arrays. Do not answer from "
            "outside knowledge."
        ),
    )

    @agent.tool
    async def search_knowledge(
        ctx: RunContext[RecallDeps],
        query: str = Field(min_length=1, max_length=RECALL_SEARCH_QUERY_MAX_CHARS),
        k: int = Field(
            default=RECALL_SEARCH_RESULT_LIMIT, ge=1, le=RECALL_SEARCH_RESULT_LIMIT
        ),
    ) -> dict:
        """Search once for a concise query, then prefer graph traversal."""
        k = max(1, min(k, RECALL_SEARCH_RESULT_LIMIT))
        denial = ctx.deps.search_denial(query, k)
        if denial is not None:
            logger.info(
                "recall: skipped search reason=%s query_chars=%d", denial, len(query)
            )
            return {
                "search_skipped": True,
                "reason": denial,
                "instruction": (
                    "Use earlier results and follow new adjacent IDs. Do not search again."
                ),
            }
        logger.info("recall: search_knowledge query_chars=%d k=%d", len(query), k)
        try:
            result = await recall_tools.search_memory(ctx.deps.storage, query, k)
            ctx.deps.remember_graph_nodes(result.nodes)
            logger.info(
                "recall: search_knowledge → %d nodes, %d unprocessed chunks",
                len(result.nodes),
                len(result.unprocessed),
            )
            return {"nodes": result.nodes, "unprocessed": result.unprocessed}
        except Exception as e:
            logger.error("recall: search_knowledge failed: %s", e)
            return {"error": str(e)}

    @agent.tool
    async def get_node(
        ctx: RunContext[RecallDeps],
        record_id: str = Field(min_length=1, max_length=RECALL_RECORD_ID_MAX_CHARS),
    ) -> dict:
        """Fetch one node from search results or a previously read connection."""
        denial = ctx.deps.node_fetch_denial(record_id)
        if denial is not None:
            logger.info(
                "recall: skipped get_node reason=%s record_id_chars=%d",
                denial,
                len(record_id),
            )
            return {
                "node_fetch_skipped": True,
                "reason": denial,
                "instruction": "Use only new IDs from search results or node connections.",
            }
        logger.info("recall: get_node record_id_chars=%d", len(record_id))
        try:
            node = await recall_tools.get_node(ctx.deps.storage, record_id)
            if not node:
                return {
                    "error": "Node not found. Continue with IDs from prior results."
                }
            enriched = await recall_tools.enrich_with_connections(
                ctx.deps.storage, node
            )
            ctx.deps.remember_graph_nodes([enriched])
            return enriched
        except Exception as e:
            logger.error("recall: get_node failed: %s", e)
            return {"error": str(e)}

    return agent


async def run_recall(
    question: str,
    *,
    deps: RecallDeps,
    model: Any,
    agent: Agent[RecallDeps, RecallOutput] | None = None,
    event_stream_handler: Any = None,
) -> RecallOutput:
    """Run recall with a fixed request and tool-call budget."""
    active_agent = agent or create_recall_agent()
    kwargs: dict[str, Any] = {
        "deps": deps,
        "model": model,
        "usage_limits": UsageLimits(
            request_limit=RECALL_REQUEST_LIMIT,
            tool_calls_limit=RECALL_TOOL_CALL_LIMIT,
        ),
    }
    kwargs["event_stream_handler"] = _make_recall_event_handler(event_stream_handler)
    try:
        result = await active_agent.run(question, **kwargs)
    except RecallOutputError as exc:
        raise RecallRunLimitExceeded(
            f"Recall returned invalid final output: {exc}"
        ) from exc
    except UsageLimitExceeded as exc:
        raise RecallRunLimitExceeded(f"Recall reached a usage limit: {exc}") from exc
    except UnexpectedModelBehavior as exc:
        raise RecallRunLimitExceeded(
            f"Recall ended without a usable reply: {exc}"
        ) from exc
    return result.output
