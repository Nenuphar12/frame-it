"""The library filter AST (docs/data-model.md §5.2) — pure validation."""

from __future__ import annotations

import pytest

from frame_it.domain.filters import (
    Clause,
    FilterError,
    collection_ids_used,
    fields_used,
    parse_date,
    parse_filter,
)


def test_bare_clause_is_wrapped_in_an_and() -> None:
    node = parse_filter({"field": "favorite", "op": "eq", "value": True})
    assert node.op == "and"
    assert isinstance(node.clauses[0], Clause)


def test_collection_value_is_normalized_to_a_list() -> None:
    node = parse_filter({"field": "collection", "op": "in", "value": "abc", "include_nested": True})
    clause = node.clauses[0]
    assert isinstance(clause, Clause)
    assert clause.value == ["abc"]
    assert clause.include_nested is True
    assert collection_ids_used(node) == {"abc"}


def test_every_field_declares_its_operators() -> None:
    with pytest.raises(FilterError, match="favorite does not support contains"):
        parse_filter({"field": "favorite", "op": "contains", "value": "x"})


@pytest.mark.parametrize(
    "raw",
    [
        {"field": "favorite", "op": "eq", "value": "yes"},
        {"field": "taken_at", "op": "between", "value": ["2026-04-01"]},
        {"field": "taken_at", "op": "before", "value": "not-a-date"},
        {"field": "worst_tier", "op": "in", "value": ["glorious"]},
        {"field": "photo_count", "op": "eq", "value": -1},
        {"field": "place", "op": "contains", "value": "  "},
        {"field": "place", "op": "near", "value": "Kyoto"},
        {"field": "place", "op": "near", "value": {"lat": 0, "lon": 0, "km": 1001}},
        {"field": "tag", "op": "has_any", "value": []},
    ],
)
def test_bad_values_are_refused(raw: dict[str, object]) -> None:
    with pytest.raises(FilterError):
        parse_filter(raw)


def test_nested_groups_keep_their_fields() -> None:
    node = parse_filter(
        {
            "op": "or",
            "clauses": [
                {"field": "status", "op": "eq", "value": "ready"},
                {
                    "op": "and",
                    "clauses": [
                        {"field": "tag", "op": "has_all", "value": ["a", "b"]},
                        {"field": "text", "op": "match", "value": "temple"},
                    ],
                },
            ],
        }
    )
    assert fields_used(node) == {"status", "tag", "text"}


def test_depth_is_bounded() -> None:
    raw: dict[str, object] = {"field": "favorite", "op": "eq", "value": True}
    for _ in range(6):
        raw = {"op": "and", "clauses": [raw]}
    with pytest.raises(FilterError, match="nested deeper"):
        parse_filter(raw)


def test_dates_become_utc_bounds() -> None:
    start = parse_date("2026-04-01")
    end = parse_date("2026-04-01", end=True)
    assert start.hour == 0 and start.tzinfo is not None
    assert end.hour == 23 and end.minute == 59
    assert parse_date("2026-04-01T10:00:00Z").hour == 10


def test_an_empty_group_is_valid_and_matches_everything() -> None:
    assert parse_filter({"op": "and", "clauses": []}).clauses == []
