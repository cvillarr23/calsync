"""Pipeline items read through JSONPath into the shared mappers."""

import copy
from datetime import UTC, date, datetime, timedelta

import pytest

from app.adapters.mappers import FieldFailure, Window, map_item
from app.adapters.pipeline.read import jsonpath_reader
from app.adapters.pipeline.run import _mapped
from tests.adapters.pipeline.conftest import BASE_MAP, unit_definition

WINDOW = Window(start=date(2026, 12, 1), end=date(2026, 12, 31))


def mapped(item, **fields):
    definition = unit_definition({**copy.deepcopy(BASE_MAP), **fields})
    return map_item(definition.map, jsonpath_reader(item), WINDOW, definition.uid)


def test_reads_first_jsonpath_match_with_tz():
    start = {"jsonpath": "$.s[0]", "tz": "America/Los_Angeles"}
    event = mapped({"t": "A", "s": ["2026-12-01 10:00", "2026-12-02 10:00"]}, start=start)
    assert event.start_utc == datetime(2026, 12, 1, 18, tzinfo=UTC)


def test_skip_if_without_equals_skips_truthy_values():
    skip = {"skip_if": {"jsonpath": "$.cancelled"}}
    assert mapped({"t": "A", "s": "2026-12-01T10:00", "cancelled": True}, **skip) is None
    assert mapped({"t": "A", "s": "2026-12-01T10:00", "cancelled": False}, **skip) is not None
    assert mapped({"t": "A", "s": "2026-12-01T10:00"}, **skip) is not None


def test_skip_if_equals_matches_numbers():
    skip = {"skip_if": {"jsonpath": "$.status", "equals": -12}}
    assert mapped({"t": "A", "s": "2026-12-01T10:00", "status": -12}, **skip) is None
    assert mapped({"t": "A", "s": "2026-12-01T10:00", "status": 1}, **skip) is not None


def test_css_fields_are_not_supported_yet():
    with pytest.raises(FieldFailure, match="title: css is not supported"):
        mapped({"s": "2026-12-01T10:00"}, title={"selector": "h3"})


def test_unreadable_items_are_reported_and_dropped():
    definition = unit_definition()
    items = [{"t": "A", "s": "2026-12-01T10:00"}, {"t": "B", "s": "soon-ish?"}, {"s": "x"}]
    result = _mapped(definition, items, WINDOW)
    assert [e.title for e in result.events] == ["A"]
    assert [str(p) for p in result.problems] == [
        "item 1: start: can't read a date or time from 'soon-ish?'",
        "item 2: title: jsonpath '$.t' matched nothing",
    ]


def test_duplicate_uids_keep_the_first_and_sort_by_start():
    definition = unit_definition(uid=["start"])
    items = [
        {"t": "Late", "s": "2026-12-05T10:00"},
        {"t": "Early", "s": "2026-12-02T10:00"},
        {"t": "Renamed", "s": "2026-12-05T10:00"},
    ]
    events = _mapped(definition, items, WINDOW).events
    assert [e.title for e in events] == ["Early", "Late"]
    assert events[1].start_utc - events[0].start_utc == timedelta(days=3)
