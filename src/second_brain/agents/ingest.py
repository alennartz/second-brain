import asyncio
import json
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_ai import Agent, NativeOutput, RunContext
from pydantic_ai.exceptions import ModelRetry, UnexpectedModelBehavior
from pydantic_ai.messages import OutputToolResultEvent, RetryPromptPart
from pydantic_ai.models import Model

from second_brain.agents.ingestion_pipeline import IngestBatchOutcome
from second_brain.db import Storage
from second_brain.tools import ingest_tools, recall_tools
from second_brain.validation import validate_identifier, validate_record_id

logger = logging.getLogger(__name__)


def _validation_issues_for_log(content: object) -> list[dict[str, str]]:
    """Keep schema paths and messages, but omit model-supplied input values."""
    if isinstance(content, str):
        return [{"path": "$", "type": "model_retry", "message": content[:240]}]
    if not isinstance(content, list):
        return [
            {
                "path": "$",
                "type": type(content).__name__,
                "message": "Unstructured validation failure",
            }
        ]

    issues: list[dict[str, str]] = []
    for error in content:
        if not isinstance(error, dict):
            continue
        location = error.get("loc", ())
        if not isinstance(location, (list, tuple)):
            location = (location,)
        issues.append(
            {
                "path": ".".join(str(part) for part in location) or "$",
                "type": str(error.get("type", "validation_error")),
                "message": str(error.get("msg", "Validation failed"))[:240],
            }
        )
    return issues or [
        {"path": "$", "type": "validation_error", "message": "No error details"}
    ]


def _validation_issues_from_exception(error: BaseException) -> list[dict[str, str]]:
    """Extract safe validation details from PydanticAI's retry exception chain."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        retry_part = getattr(current, "tool_retry", None)
        if isinstance(retry_part, RetryPromptPart):
            return _validation_issues_for_log(retry_part.content)
        errors = getattr(current, "errors", None)
        if callable(errors):
            try:
                details = errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )
            except TypeError:
                details = errors()
            return _validation_issues_for_log(details)
        current = current.__cause__ or current.__context__
    return []


def _make_output_validation_handler(rejection_count: list[int]):
    """Log each rejected final result without logging its raw arguments."""

    async def handler(_ctx: Any, events: Any) -> None:
        async for event in events:
            if not isinstance(event, OutputToolResultEvent):
                continue
            if not isinstance(event.part, RetryPromptPart):
                continue
            rejection_count[0] += 1
            issues = _validation_issues_for_log(event.part.content)
            logger.warning(
                "ingest: structured output rejected attempt=%d tool=%s issues=%s",
                rejection_count[0],
                event.part.tool_name or "final_result",
                json.dumps(issues, ensure_ascii=False),
            )

    return handler


class IngestEntityInput(BaseModel):
    """One entity to add to the knowledge graph."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1, max_length=120, description="Canonical name of the entity."
    )
    type: str = Field(
        min_length=1,
        max_length=60,
        description="Entity category, such as person or concept.",
    )
    description: str | None = Field(
        default=None,
        max_length=400,
        description="Short identifying description, when useful.",
    )


class IngestNoteInput(BaseModel):
    """One source-faithful note to add to the knowledge graph."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(
        min_length=1,
        max_length=80,
        description="Short unique label for references from edges. Use at most six words.",
    )
    content: str = Field(
        min_length=1,
        max_length=2000,
        description="The note text to preserve — quote concisely, never paste whole documents.",
    )
    source: str | None = Field(
        default=None,
        max_length=120,
        description="Provenance label. Omit to use the intake default.",
    )
    summary: str | None = Field(
        default=None,
        max_length=300,
        description="Optional concise summary of the note.",
    )

    @field_validator("label")
    @classmethod
    def keep_note_label_short(cls, value: str) -> str:
        if len(value.split()) > 6:
            raise ValueError("Note labels must contain no more than six words")
        return value


_RESERVED_EDGE_TABLES = frozenset({"entity", "note", "intake_chunk", "intake_key"})


class IngestNodeUpdateFields(BaseModel):
    """Fields that can be changed on a note or entity."""

    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, max_length=2000)
    name: str | None = Field(default=None, max_length=120)
    type: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=400)
    summary: str | None = Field(default=None, max_length=300)
    source: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def require_update_field(self) -> "IngestNodeUpdateFields":
        if not self.model_fields_set:
            raise ValueError("provide at least one field to update")
        return self


def _normalize_repeated_table_prefix(record_id: str) -> str:
    table, separator, remainder = record_id.partition(":")
    if not separator or table not in {"entity", "note"}:
        return record_id

    prefix = f"{table}:"
    repetitions = 0
    while remainder.startswith(prefix):
        remainder = remainder[len(prefix) :]
        repetitions += 1
    if repetitions:
        logger.warning(
            "ingest: normalized repeated record table prefix table=%s repetitions=%d",
            table,
            repetitions,
        )
        return f"{table}:{remainder}"
    return record_id


class RecordRef(BaseModel):
    """Reference a planned entity/note by name or an existing record by ID."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["new_entity", "new_note", "existing"]
    name: str | None = Field(
        default=None,
        max_length=120,
        description="Exact name from this plan's entities list for kind=new_entity.",
    )
    label: str | None = Field(
        default=None,
        max_length=80,
        description="Exact short label from this plan's notes list for kind=new_note.",
    )
    record_id: str | None = Field(
        default=None,
        max_length=120,
        description='Existing record ID exactly as supplied, e.g. "entity:abc123".',
    )

    @model_validator(mode="before")
    @classmethod
    def discard_inapplicable_reference_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        kind = value.get("kind")
        if not isinstance(kind, str):
            return value
        kept_field = {
            "new_entity": "name",
            "new_note": "label",
            "existing": "record_id",
        }.get(kind)
        if kept_field is None:
            return value
        discarded = [
            field_name
            for field_name in ("name", "label", "record_id")
            if field_name != kept_field and value.get(field_name) is not None
        ]
        if not discarded:
            return value
        logger.warning(
            "ingest: normalized RecordRef kind=%s ignored_fields=%s",
            kind,
            discarded,
        )
        cleaned = dict(value)
        for field_name in discarded:
            cleaned.pop(field_name, None)
        return cleaned

    @field_validator("record_id")
    @classmethod
    def normalize_existing_record_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_repeated_table_prefix(value)

    @model_validator(mode="after")
    def require_matching_reference_fields(self) -> "RecordRef":
        if self.kind == "existing":
            if (
                self.name is not None
                or self.label is not None
                or self.record_id is None
            ):
                raise ValueError("existing references require record_id only")
        elif self.kind == "new_entity":
            if (
                self.name is None
                or self.label is not None
                or self.record_id is not None
            ):
                raise ValueError("new_entity references require name only")
        elif self.label is None or self.name is not None or self.record_id is not None:
            raise ValueError("new_note references require label only")
        return self


class IngestEdgeInput(BaseModel):
    """One directed relationship between new or existing graph records."""

    model_config = ConfigDict(extra="forbid")

    from_ref: RecordRef
    edge_table: str = Field(
        min_length=1,
        max_length=60,
        description=(
            "Lowercase snake_case relationship name, such as designed_by. "
            "Never use node or intake tables: entity, note, intake_chunk, intake_key."
        ),
    )
    to_ref: RecordRef
    context: str | None = Field(default=None, max_length=400)

    @field_validator("edge_table")
    @classmethod
    def validate_edge_table(cls, value: str) -> str:
        validate_identifier(value)
        if value in _RESERVED_EDGE_TABLES:
            raise ValueError(
                f"{value!r} is a reserved node/intake table, not an edge table"
            )
        return value


class IngestNodeUpdatePlan(BaseModel):
    """One update to a previously discovered note or entity."""

    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(
        min_length=1,
        max_length=120,
        description='Existing record ID, e.g. "entity:abc123".',
    )
    fields: IngestNodeUpdateFields

    @field_validator("record_id")
    @classmethod
    def normalize_existing_record_id(cls, value: str) -> str:
        return _normalize_repeated_table_prefix(value)


class IngestPlan(BaseModel):
    """Complete, validated graph-write plan returned before any writes occur."""

    model_config = ConfigDict(extra="forbid")

    entities: list[IngestEntityInput] = Field(
        max_length=20,
        description="New entities to create. Empty list when none are needed.",
    )
    notes: list[IngestNoteInput] = Field(
        max_length=20,
        description="Source-faithful notes to create. Empty list when none are needed.",
    )
    edges: list[IngestEdgeInput] = Field(
        max_length=40,
        description="Relationships among new and existing records.",
    )
    updates: list[IngestNodeUpdatePlan] = Field(
        max_length=20,
        description="Changes to existing records. Empty list when none are needed.",
    )
    summary: str = Field(
        min_length=1,
        max_length=300,
        description="Brief summary of the planned changes.",
    )

    @model_validator(mode="after")
    def validate_new_references(self) -> "IngestPlan":
        entity_names = [item.name for item in self.entities]
        note_labels = [item.label for item in self.notes]
        normalized_entities = [name.casefold() for name in entity_names]
        normalized_labels = [label.casefold() for label in note_labels]
        if len(normalized_entities) != len(set(normalized_entities)):
            duplicates = sorted(
                name
                for name in set(normalized_entities)
                if normalized_entities.count(name) > 1
            )
            raise ValueError(
                f"Entity names must be unique; disambiguate duplicates: {', '.join(duplicates)}"
            )
        if len(normalized_labels) != len(set(normalized_labels)):
            duplicates = sorted(
                label
                for label in set(normalized_labels)
                if normalized_labels.count(label) > 1
            )
            raise ValueError(
                f"Note labels must be unique; disambiguate duplicates: {', '.join(duplicates)}"
            )

        entity_name_set = set(normalized_entities)
        note_label_set = set(normalized_labels)
        for edge in self.edges:
            for reference in (edge.from_ref, edge.to_ref):
                if reference.kind == "existing" and reference.record_id is not None:
                    table, separator, suffix = reference.record_id.partition(":")
                    if (
                        separator
                        and table == "entity"
                        and suffix.casefold() in entity_name_set
                    ):
                        raise ValueError(
                            f"Existing ID {reference.record_id!r} matches a new entity name. "
                            f"Use kind='new_entity' with name={suffix!r}, or copy an exact candidate ID."
                        )
                    if (
                        separator
                        and table == "note"
                        and suffix.casefold() in note_label_set
                    ):
                        raise ValueError(
                            f"Existing ID {reference.record_id!r} matches a new note label. "
                            f"Use kind='new_note' with label={suffix!r}, or copy an exact candidate ID."
                        )
                    try:
                        validate_record_id(reference.record_id)
                    except ValueError as exc:
                        table, separator, suffix = reference.record_id.partition(":")
                        if (
                            separator
                            and table == "entity"
                            and suffix.casefold() in entity_name_set
                        ):
                            raise ValueError(
                                f"{reference.record_id!r} names a new entity in this plan. "
                                f"Use kind='new_entity' and name={suffix!r}."
                            ) from exc
                        if (
                            separator
                            and table == "note"
                            and suffix.casefold() in note_label_set
                        ):
                            raise ValueError(
                                f"{reference.record_id!r} names a new note in this plan. "
                                f"Use kind='new_note' and label={suffix!r}."
                            ) from exc
                        raise ValueError(
                            f"Invalid existing record ID {reference.record_id!r}. "
                            "Copy an exact ID from the candidate list or its connections."
                        ) from exc
                if reference.kind == "new_entity":
                    name = reference.name
                    if name is None or name.casefold() not in entity_name_set:
                        raise ValueError(
                            f"Unknown new entity name {name!r}. Valid entity names: "
                            f"{', '.join(entity_names) or 'none'}"
                        )
                if reference.kind == "new_note":
                    label = reference.label
                    if label is None or label.casefold() not in note_label_set:
                        raise ValueError(
                            f"Unknown new note label {label!r}. Valid note labels: "
                            f"{', '.join(note_labels) or 'none'}"
                        )
        for update in self.updates:
            try:
                validate_record_id(update.record_id)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid update target {update.record_id!r}. Use an existing candidate ID."
                ) from exc
        return self


@dataclass
class IngestDeps:
    storage: Storage
    candidates: tuple[dict, ...] = ()


def _store_reference(reference: RecordRef, plan: IngestPlan) -> str:
    """Compile a model reference into the internal writer's reference syntax."""
    if reference.kind == "existing":
        if reference.record_id is None:
            raise ValueError("existing reference has no record_id")
        return reference.record_id
    if reference.kind == "new_entity":
        if reference.name is None:
            raise ValueError("new_entity reference has no name")
        for index, entity in enumerate(plan.entities):
            if entity.name.casefold() == reference.name.casefold():
                return f"new_entity:{index}"
        raise ValueError(f"Unknown new entity name {reference.name!r}")
    if reference.label is None:
        raise ValueError("new_note reference has no label")
    for index, note in enumerate(plan.notes):
        if note.label.casefold() == reference.label.casefold():
            return f"new_note:{index}"
    raise ValueError(f"Unknown new note label {reference.label!r}")


class _ShutdownRequested(Exception):
    """Signal that shutdown interrupted the next LLM boundary."""


class AgentIngestBatchRunner:
    """Search once in code, ask for a plan, then apply writes once in code."""

    def __init__(
        self, agent: Agent[IngestDeps, IngestPlan], storage: Storage, model: Model | str
    ) -> None:
        self.agent = agent
        self.storage = storage
        self.model = model

    @staticmethod
    def _raise_if_stopping(stop_event: asyncio.Event | None) -> None:
        if stop_event is not None and stop_event.is_set():
            raise _ShutdownRequested

    async def _find_candidates(
        self, query: str, stop_event: asyncio.Event | None = None
    ) -> list[dict]:
        self._raise_if_stopping(stop_event)
        candidates: dict[str, dict] = {}
        for table in ("entity", "note"):
            matches = await recall_tools.hybrid_search(self.storage, table, query, k=5)
            self._raise_if_stopping(stop_event)
            for match in matches:
                record_id = str(match.get("id", ""))
                if not record_id or record_id in candidates:
                    continue
                enriched = await recall_tools.enrich_with_connections(
                    self.storage, match
                )
                self._raise_if_stopping(stop_event)
                candidates[record_id] = {
                    key: enriched[key]
                    for key in (
                        "id",
                        "table",
                        "name",
                        "type",
                        "description",
                        "content",
                        "summary",
                        "source",
                    )
                    if key in enriched
                }
                candidates[record_id]["connections"] = enriched.get("connections", [])[
                    :8
                ]
        return list(candidates.values())

    async def _run_agent(
        self,
        prompt: str,
        candidates: list[dict],
        rejection_count: list[int],
        stop_event: asyncio.Event | None,
    ) -> Any:
        self._raise_if_stopping(stop_event)

        async def run_agent() -> Any:
            return await self.agent.run(
                prompt,
                deps=IngestDeps(storage=self.storage, candidates=tuple(candidates)),
                model=self.model,
                event_stream_handler=_make_output_validation_handler(rejection_count),
            )

        if stop_event is None:
            return await run_agent()

        agent_task = asyncio.create_task(run_agent())
        stop_task = asyncio.create_task(stop_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {agent_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if agent_task in done:
                return await agent_task
            agent_task.cancel()
            with suppress(asyncio.CancelledError):
                await agent_task
            raise _ShutdownRequested
        finally:
            if not stop_task.done():
                stop_task.cancel()
            with suppress(asyncio.CancelledError):
                await stop_task

    async def run(
        self,
        text: str,
        hints: list[str],
        *,
        stop_event: asyncio.Event | None = None,
    ) -> IngestBatchOutcome:
        hint_text = ", ".join(hints)
        search_query = f"{hint_text}\n{text}" if hint_text else text
        rejection_count = [0]
        try:
            candidates = await self._find_candidates(search_query, stop_event)
            logger.info(
                "ingest: prepared plan context (%d graph candidates, %d source chars)",
                len(candidates),
                len(text),
            )
            prompt = (
                "## Intake batch\n"
                f"{text}\n\n"
                "## Possibly related nodes\n"
                f"{hint_text or 'None'}\n\n"
                "## Existing graph candidates\n"
                f"{json.dumps(candidates, ensure_ascii=False, indent=2)}\n\n"
                "Use these candidates for deduplication. The application already ran one "
                "broad hybrid search. Do not request another search. If the candidate list "
                "is empty, treat the input as new knowledge. Return one IngestPlan."
            )
            result = await self._run_agent(
                prompt, candidates, rejection_count, stop_event
            )
        except _ShutdownRequested:
            logger.info("ingest: shutdown requested before graph writes")
            return IngestBatchOutcome(
                completed=False,
                errors=["shutdown requested"],
                interrupted=True,
            )
        except UnexpectedModelBehavior as exc:
            issues = _validation_issues_from_exception(exc)
            logger.error(
                "ingest: structured output exhausted retries rejections=%d issues=%s",
                rejection_count[0],
                json.dumps(issues, ensure_ascii=False),
            )
            raise
        plan = result.output
        edges = []
        for edge in plan.edges:
            item = edge.model_dump(exclude_none=True)
            item["from_ref"] = _store_reference(edge.from_ref, plan)
            item["to_ref"] = _store_reference(edge.to_ref, plan)
            edges.append(item)
        writes = await ingest_tools.store_knowledge(
            self.storage,
            [item.model_dump(exclude_none=True) for item in plan.entities],
            [
                item.model_dump(exclude_none=True, exclude={"label"})
                for item in plan.notes
            ],
            edges,
        )
        errors = [str(error) for error in writes.get("errors", [])]
        errors.extend(str(error) for error in writes.get("storage_errors", []))

        for update in plan.updates:
            fields = update.fields.model_dump(exclude_unset=True)
            try:
                updated = await self.storage.update_node(update.record_id, fields)
                if not updated:
                    errors.append(f"Update target {update.record_id!r} was not found")
            except Exception as exc:
                errors.append(f"Update failed for {update.record_id!r}: {exc}")

        logger.info(
            "ingest: plan applied (%d entities, %d notes, %d edges, %d updates)",
            len(plan.entities),
            len(plan.notes),
            len(plan.edges),
            len(plan.updates),
        )
        return IngestBatchOutcome(
            completed=not errors,
            summary=plan.summary,
            errors=errors,
        )


def create_ingest_agent(
    *, native_output: bool = False, max_output_tokens: int = 8192
) -> Agent[IngestDeps, IngestPlan]:
    """Create a bounded planning agent; application code owns all writes.

    Self-hosted OpenAI endpoints use native JSON-schema output instead of
    synthetic output tools. Other providers retain their existing output mode.
    """
    agent = Agent(
        deps_type=IngestDeps,
        output_type=NativeOutput(IngestPlan) if native_output else IngestPlan,
        retries=2,
        model_settings={
            "parallel_tool_calls": False,
            "max_tokens": max_output_tokens,
        },
        system_prompt=(
            "You are a personal knowledge ingest planner. The user provides raw text; "
            "the application provides one broad search of existing notes and entities. "
            "Use those candidates to avoid duplicate entities. If a candidate is the same "
            "real-world thing, reference its existing ID instead of creating a duplicate.\n\n"
            "Be selective when extracting entities. Create an entity only when it is a named, "
            "independently useful retrieval target or a necessary endpoint for a meaningful "
            "relationship. Do not create an entity for every noun or named mention. Skip "
            "incidental people, generic roles, dates, attributes, and subcomponents unless they "
            "are central to the intake. Preserve secondary details in notes. Prefer the smallest "
            "entity set that preserves the important facts and links. Do not pad the graph.\n\n"
            "Return exactly one complete IngestPlan. Do not call write tools; the application "
            "validates your plan and performs the writes once. Include entities, notes, edges, "
            "updates, and summary. Use empty arrays for sections with no items.\n\n"
            "Use RecordRef objects for every edge endpoint. For a new entity, use "
            '{"kind":"new_entity","name":"Exact entity name"}; for a new note, use '
            '{"kind":"new_note","label":"Exact note label"}. For an existing record, use '
            '{"kind":"existing","record_id":"entity:abc123"}. Include only the matching '
            "field for each kind. Copy existing IDs exactly once; never add or repeat a table "
            "prefix. Never form an ID by adding entity: or note: to a name. Use the exact new "
            "entity names and note labels from this plan. Entity names "
            "and note labels must be unique within the plan; note labels must be at most six words.\n\n"
            "Keep each plan within its schema limits: 20 entities, 20 notes, 40 edges, and 20 "
            "updates. Keep note content under 2,000 characters and summaries under 300. Prefer "
            "fewer useful entities over exhaustive extraction.\n\n"
            "Use meaningful lowercase snake_case relationship names such as designed_by, "
            "part_of, member_of, launched, or located_in. Never use reserved node or intake "
            "table names as edge names: entity, note, intake_chunk, intake_key.\n\n"
            "Prefer direct entity-to-entity relationships, connect notes to their primary "
            "entities with describes edges, and add useful hierarchical relationships. "
            "Do not invent generic labels such as references or relates_to. "
            "Preserve the user's source meaning in notes and summaries."
        ),
    )

    @agent.output_validator
    def validate_existing_references(
        ctx: RunContext[IngestDeps], plan: IngestPlan
    ) -> IngestPlan:
        candidate_ids = {
            str(candidate["id"])
            for candidate in ctx.deps.candidates
            if candidate.get("id")
        }
        visible_ids = set(candidate_ids)
        for candidate in ctx.deps.candidates:
            for connection in candidate.get("connections", []):
                adjacent_id = connection.get("adjacent_id")
                if isinstance(adjacent_id, str):
                    visible_ids.add(adjacent_id)

        unknown_refs = sorted(
            {
                reference.record_id
                for edge in plan.edges
                for reference in (edge.from_ref, edge.to_ref)
                if reference.kind == "existing"
                and reference.record_id is not None
                and reference.record_id not in visible_ids
            }
        )
        unknown_updates = sorted(
            {
                update.record_id
                for update in plan.updates
                if update.record_id not in candidate_ids
            }
        )
        if unknown_refs or unknown_updates:
            available = sorted(visible_ids)
            available_text = ", ".join(available[:20]) or "none"
            if len(available) > 20:
                available_text += f", and {len(available) - 20} more"
            new_entity_names = (
                ", ".join(entity.name for entity in plan.entities) or "none"
            )
            new_note_labels = ", ".join(note.label for note in plan.notes) or "none"
            raise ModelRetry(
                "Use existing IDs exactly as supplied in the candidate list or its "
                "connections. Do not add or repeat a table prefix. If an endpoint is a new "
                "item, use its exact name or note label instead of an ID. "
                f"Unknown edge references: {unknown_refs or 'none'}. "
                f"Unknown update targets: {unknown_updates or 'none'}. "
                f"Valid existing IDs: {available_text}. "
                f"New entity names: {new_entity_names}. New note labels: {new_note_labels}."
            )

        existing_entities = {
            (
                str(candidate.get("name", "")).casefold(),
                str(candidate.get("type", "")).casefold(),
            ): str(candidate["id"])
            for candidate in ctx.deps.candidates
            if candidate.get("table") == "entity" and candidate.get("id")
        }
        duplicates = [
            (
                entity.name,
                existing_entities[(entity.name.casefold(), entity.type.casefold())],
            )
            for entity in plan.entities
            if (entity.name.casefold(), entity.type.casefold()) in existing_entities
        ]
        if duplicates:
            details = "; ".join(
                f"{name!r} already exists as {record_id}"
                for name, record_id in duplicates
            )
            raise ModelRetry(
                f"Do not create duplicate entities: {details}. Reference the existing ID instead."
            )
        return plan

    return agent
