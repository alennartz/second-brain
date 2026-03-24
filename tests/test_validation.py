"""Tests for the shared validation module."""

import pytest

from second_brain.validation import (
    check_query_result,
    validate_identifier,
    validate_record_id,
)

# --- validate_record_id ---


class TestValidateRecordId:
    """Record ID validation."""

    @pytest.mark.parametrize(
        "rid",
        [
            "note:abc",
            "entity:some_id",
            "relates_to:abc-def",
            "note:⟨123⟩",
            "entity:A1_b2",
        ],
    )
    def test_valid(self, rid: str):
        assert validate_record_id(rid) == rid

    @pytest.mark.parametrize(
        "rid",
        [
            "note:abc; DELETE note",  # injection attempt
            "note:abc OR 1=1",  # another injection
            "note:abc\nDELETE note",  # newline injection
            ":missing_table",  # no table part
            "UPPER:id",  # uppercase table
            "note:",  # empty id
            "",  # empty string
            "note",  # no colon separator
            "note:id:extra",  # extra colon (colon not in allowed chars for id)
        ],
    )
    def test_invalid(self, rid: str):
        with pytest.raises(ValueError, match="Invalid record ID"):
            validate_record_id(rid)


# --- validate_identifier ---


class TestValidateIdentifier:
    """SurrealQL identifier validation."""

    @pytest.mark.parametrize(
        "name",
        [
            "note",
            "entity",
            "relates_to",
            "derived_from",
            "_private",
            "a1b2c3",
        ],
    )
    def test_valid(self, name: str):
        assert validate_identifier(name) == name

    @pytest.mark.parametrize(
        "name",
        [
            "Note",  # uppercase
            "123abc",  # starts with digit
            "has space",  # space
            "has-dash",  # dash
            "semi;colon",  # semicolon
            "",  # empty
            "table:id",  # colon (record ID, not identifier)
        ],
    )
    def test_invalid(self, name: str):
        with pytest.raises(ValueError, match="Invalid identifier"):
            validate_identifier(name)


# --- check_query_result ---


class TestCheckQueryResult:
    """Query result checking."""

    def test_error_string_raises(self):
        with pytest.raises(RuntimeError, match="search: something went wrong"):
            check_query_result("something went wrong", "search")

    def test_list_passthrough(self):
        data = [{"id": "note:abc", "body": "hello"}]
        assert check_query_result(data, "search") is data

    def test_empty_list_passthrough(self):
        assert check_query_result([], "search") == []

    def test_none_returns_empty_list(self):
        assert check_query_result(None, "search") == []

    def test_unexpected_type_returns_empty_list(self):
        assert check_query_result(42, "search") == []
