"""Tests for the planning agent and its application-controlled writer."""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from pydantic_ai.models.test import TestModel

from second_brain.agents.ingest import (
    AgentIngestBatchRunner,
    IngestDeps,
    IngestPlan,
    RecordRef,
    _validation_issues_for_log,
    create_ingest_agent,
)


def _valid_plan() -> dict:
    return {
        "entities": [{"name": "Python", "type": "language"}],
        "notes": [
            {
                "label": "coding practice",
                "content": "Python supports useful coding tools.",
            }
        ],
        "edges": [
            {
                "from_ref": {"kind": "new_note", "label": "coding practice"},
                "edge_table": "describes",
                "to_ref": {"kind": "new_entity", "name": "Python"},
            }
        ],
        "updates": [],
        "summary": "Stored a note about Python.",
    }


async def test_ingest_agent_exposes_no_tools():
    agent = create_ingest_agent()
    assert agent._function_toolset.tools == {}


def test_validation_issue_log_keeps_schema_path_without_raw_input():
    issues = _validation_issues_for_log(
        [
            {
                "loc": ("edges", 0, "edge_table"),
                "type": "string_pattern_mismatch",
                "msg": "String should match pattern",
                "input": "private-user-text",
            }
        ]
    )

    assert issues == [
        {
            "path": "edges.0.edge_table",
            "type": "string_pattern_mismatch",
            "message": "String should match pattern",
        }
    ]
    assert "private-user-text" not in repr(issues)


def test_ingest_plan_has_typed_closed_schema():
    schema = IngestPlan.model_json_schema()
    assert set(schema["required"]) == {
        "entities",
        "notes",
        "edges",
        "updates",
        "summary",
    }
    definitions = schema["$defs"]
    expected = {
        "IngestEntityInput": {"name", "type"},
        "IngestNoteInput": {"label", "content"},
        "IngestEdgeInput": {"from_ref", "edge_table", "to_ref"},
        "RecordRef": {"kind"},
    }
    for definition, required_fields in expected.items():
        item_schema = definitions[definition]
        assert item_schema["additionalProperties"] is False
        assert set(item_schema["required"]) == required_fields
        assert set(item_schema["properties"]) >= required_fields

    edge_schema = definitions["IngestEdgeInput"]["properties"]
    assert "pattern" not in edge_schema["edge_table"]
    assert edge_schema["edge_table"]["maxLength"] == 60
    assert "Never use node or intake tables" in edge_schema["edge_table"]["description"]
    assert edge_schema["from_ref"]["$ref"] == "#/$defs/RecordRef"
    assert edge_schema["to_ref"]["$ref"] == "#/$defs/RecordRef"
    ref_schema = definitions["RecordRef"]["properties"]
    assert ref_schema["kind"]["enum"] == ["new_entity", "new_note", "existing"]
    assert set(ref_schema) == {"kind", "name", "label", "record_id"}
    assert ref_schema["name"]["anyOf"][0]["maxLength"] == 120
    assert ref_schema["label"]["anyOf"][0]["maxLength"] == 80
    assert ref_schema["record_id"]["anyOf"][0]["maxLength"] == 120
    assert "pattern" not in ref_schema["record_id"]["anyOf"][0]
    assert schema["properties"]["entities"]["maxItems"] == 20
    assert schema["properties"]["notes"]["maxItems"] == 20
    assert schema["properties"]["edges"]["maxItems"] == 40
    assert (
        schema["$defs"]["IngestNoteInput"]["properties"]["content"]["maxLength"] == 2000
    )

    update_fields = definitions["IngestNodeUpdateFields"]
    assert update_fields["additionalProperties"] is False
    assert set(update_fields["properties"]) == {
        "content",
        "name",
        "type",
        "description",
        "summary",
        "source",
    }


def test_record_ref_normalizes_repeated_existing_table_prefix():
    reference = RecordRef.model_validate(
        {"kind": "existing", "record_id": "entity:entity:abc123"}
    )
    assert reference.record_id == "entity:abc123"


def test_record_ref_discards_fields_that_do_not_match_kind():
    reference = RecordRef.model_validate(
        {
            "kind": "new_entity",
            "name": "Python",
            "record_id": "entity:Python",
        }
    )
    assert reference.kind == "new_entity"
    assert reference.name == "Python"
    assert reference.record_id is None


def test_ingest_plan_recognizes_prefixed_new_entity_name():
    plan = _valid_plan()
    plan["edges"][0]["to_ref"] = {
        "kind": "existing",
        "record_id": "entity:Python",
    }
    with pytest.raises(ValidationError, match="matches a new entity name"):
        IngestPlan.model_validate(plan)


def test_ingest_plan_rejects_duplicate_entity_names_and_note_labels():
    plan = _valid_plan()
    plan["entities"].append({"name": "Python", "type": "language"})
    with pytest.raises(ValidationError, match="Entity names must be unique"):
        IngestPlan.model_validate(plan)

    plan = _valid_plan()
    plan["notes"].append({"label": "coding practice", "content": "Another note."})
    with pytest.raises(ValidationError, match="Note labels must be unique"):
        IngestPlan.model_validate(plan)


def test_ingest_plan_rejects_reserved_edge_table_and_bad_reference():
    plan = _valid_plan()
    plan["edges"][0]["edge_table"] = "entity"
    with pytest.raises(ValidationError, match="reserved node/intake table"):
        IngestPlan.model_validate(plan)

    plan = _valid_plan()
    plan["edges"][0]["to_ref"] = {"kind": "new_entity", "name": "Missing"}
    with pytest.raises(ValidationError, match="Unknown new entity name"):
        IngestPlan.model_validate(plan)

    plan = _valid_plan()
    plan["edges"][0]["from_ref"] = {"kind": "existing", "name": "Unused name"}
    with pytest.raises(
        ValidationError, match="existing references require record_id only"
    ):
        IngestPlan.model_validate(plan)

    plan = _valid_plan()
    plan["extra"] = "unexpected"
    with pytest.raises(ValidationError):
        IngestPlan.model_validate(plan)


async def test_ingest_agent_returns_validated_plan(storage):
    agent = create_ingest_agent()
    result = await agent.run(
        "I've been thinking about how Python helps with coding practice",
        deps=IngestDeps(storage=storage),
        model=TestModel(call_tools=[], custom_output_args=_valid_plan()),
    )
    assert result.output == IngestPlan.model_validate(_valid_plan())


async def test_batch_runner_applies_one_plan(storage):
    agent = create_ingest_agent()
    runner = AgentIngestBatchRunner(
        agent,
        storage,
        TestModel(call_tools=[], custom_output_args=_valid_plan()),
    )

    outcome = await runner.run("Python supports useful coding tools.", [])

    assert outcome.completed is True
    assert outcome.summary == "Stored a note about Python."
    assert outcome.errors == []
    entities = await storage.hybrid_search("entity", "Python", 10)
    notes = await storage.hybrid_search(
        "note", "Python supports useful coding tools.", 10
    )
    assert any(entity.get("name") == "Python" for entity in entities)
    python_note = next(
        note
        for note in notes
        if note.get("content") == "Python supports useful coding tools."
    )
    outgoing_edges = await storage.get_outgoing_edges(python_note["id"])
    assert any(edge["id"].split(":", 1)[0] == "describes" for edge in outgoing_edges)


class BlockingAgent:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self._never = asyncio.Event()

    async def run(self, *_args, **_kwargs):
        self.started.set()
        try:
            await self._never.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class ImmediateAgent:
    async def run(self, *_args, **_kwargs):
        return SimpleNamespace(output=IngestPlan.model_validate(_valid_plan()))


async def test_batch_runner_stops_after_db_search_before_starting_the_llm(
    storage, monkeypatch
):
    search_finished = asyncio.Event()

    async def hybrid_search(*_args, **_kwargs):
        search_finished.set()
        return []

    monkeypatch.setattr(
        "second_brain.agents.ingest.recall_tools.hybrid_search", hybrid_search
    )
    agent = BlockingAgent()
    runner = AgentIngestBatchRunner(agent, storage, "model")
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        runner.run("Do not call the model.", [], stop_event=stop_event)
    )

    await search_finished.wait()
    stop_event.set()
    outcome = await asyncio.wait_for(task, timeout=1)

    assert outcome.interrupted is True
    assert not agent.started.is_set()


async def test_batch_runner_cancels_an_active_llm_when_shutdown_starts(storage):
    agent = BlockingAgent()
    runner = AgentIngestBatchRunner(agent, storage, "model")
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        runner.run("A pending model call.", [], stop_event=stop_event)
    )

    await agent.started.wait()
    stop_event.set()
    outcome = await asyncio.wait_for(task, timeout=1)

    assert outcome.completed is False
    assert outcome.interrupted is True
    assert outcome.errors == ["shutdown requested"]
    assert agent.cancelled.is_set()


async def test_batch_runner_finishes_db_writes_after_shutdown_starts(
    storage, monkeypatch
):
    writes_started = asyncio.Event()
    release_writes = asyncio.Event()

    async def store_knowledge(*_args, **_kwargs):
        writes_started.set()
        await release_writes.wait()
        return {"errors": [], "storage_errors": []}

    monkeypatch.setattr(
        "second_brain.agents.ingest.ingest_tools.store_knowledge", store_knowledge
    )
    runner = AgentIngestBatchRunner(ImmediateAgent(), storage, "model")
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        runner.run("Finish the database write.", [], stop_event=stop_event)
    )

    await writes_started.wait()
    stop_event.set()
    await asyncio.sleep(0)
    assert not task.done()
    release_writes.set()

    outcome = await asyncio.wait_for(task, timeout=1)

    assert outcome.completed is True
    assert outcome.interrupted is False
