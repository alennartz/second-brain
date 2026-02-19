"""Tests for the shared models module."""

from datetime import UTC, datetime

from surrealdb import RecordID

from second_brain.models import Context, make_serializable


def test_make_serializable_handles_record_id():
    """RecordID('note', '1') should become 'note:1', not 'note:⟨1⟩'."""
    result = make_serializable(RecordID("note", "1"))
    assert result == "note:1"


def test_make_serializable_handles_record_id_string_key():
    """RecordID('entity', 'sr') should become 'entity:sr'."""
    result = make_serializable(RecordID("entity", "sr"))
    assert result == "entity:sr"


def test_make_serializable_handles_datetime():
    """datetime objects should be converted to ISO 8601 strings."""
    dt = datetime(2026, 2, 19, 12, 0, 0, tzinfo=UTC)
    result = make_serializable(dt)
    assert result == "2026-02-19T12:00:00+00:00"


def test_make_serializable_handles_nested():
    """Nested dicts and lists should be recursively processed."""
    rid = RecordID("note", "42")
    dt = datetime(2026, 1, 1, tzinfo=UTC)
    data = {
        "id": rid,
        "created": dt,
        "tags": ["a", "b"],
        "meta": {"ref": RecordID("entity", "x"), "count": 5},
    }
    result = make_serializable(data)
    assert result == {
        "id": "note:42",
        "created": "2026-01-01T00:00:00+00:00",
        "tags": ["a", "b"],
        "meta": {"ref": "entity:x", "count": 5},
    }


def test_make_serializable_passthrough():
    """Primitive types (str, int, float, bool, None) pass through unchanged."""
    assert make_serializable("hello") == "hello"
    assert make_serializable(42) == 42
    assert make_serializable(3.14) == 3.14
    assert make_serializable(True) is True
    assert make_serializable(False) is False
    assert make_serializable(None) is None


def test_context_model_defaults():
    """Context() should have empty lists for nodes and edges."""
    ctx = Context()
    assert ctx.nodes == []
    assert ctx.edges == []
