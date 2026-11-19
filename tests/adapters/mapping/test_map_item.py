from datetime import UTC, date, datetime

import pytest

from app.adapters.mapping import FieldFailure, Window, map_item
from app.adapters.schema import FieldMap

WINDOW = Window(start=date(2026, 12, 20), end=date(2027, 1, 31))


def mapped(fields, record, window=WINDOW):
    """Map a dict record whose keys are the selectors, so specs read like `{"selector": "t"}`."""
    field_map = FieldMap.model_validate(fields)
    return map_item(field_map, lambda spec, name: record.get(spec.selector), window)


def utc(*args):
    return datetime(*args, tzinfo=UTC)


def test_regex_takes_first_group_and_strip():
    event = mapped(
        {
            "title": {"selector": "t", "regex": r"Event: (.+)", "strip": True},
            "start": {"selector": "s"},
        },
        {"t": "Event:   Skate  ", "s": "2027-01-05T10:00:00Z"},
    )
    assert event.title == "Skate"


def test_named_range_groups_share_meridiem():
    event = mapped(
        {
            "title": {"selector": "t"},
            "date": {"selector": "d", "format": "%Y-%m-%d"},
            "start": {
                "selector": "s",
                "time_range_regex": r"(?P<start>[\d:]+)\s*to\s*(?P<end>.+)",
                "tz": "America/Chicago",
            },
        },
        {"t": "Skate", "d": "2027-01-05", "s": "7:00 to 8:30 pm"},
    )
    assert (event.start_utc, event.end_utc) == (utc(2027, 1, 6, 1, 0), utc(2027, 1, 6, 2, 30))


def test_year_less_format_rolls_into_next_year():
    event = mapped(
        {"title": {"selector": "t"}, "start": {"selector": "s", "format": "%b %d %H:%M"}},
        {"t": "Skate", "s": "Jan 03 18:00"},
    )
    assert event.start_utc == utc(2027, 1, 3, 18, 0)


def test_explicit_offset_wins_over_tz():
    event = mapped(
        {"title": {"selector": "t"}, "start": {"selector": "s", "tz": "America/Chicago"}},
        {"t": "Skate", "s": "2027-01-05T10:00:00Z"},
    )
    assert event.start_utc == utc(2027, 1, 5, 10, 0)


@pytest.mark.parametrize(("equals", "value"), [(-12, "-12"), ("cancelled", "cancelled")])
def test_skip_if_compares_text_with_numbers(equals, value):
    fields = {
        "title": {"selector": "t"},
        "start": {"selector": "s"},
        "skip_if": {"selector": "k", "equals": equals},
    }
    assert mapped(fields, {"t": "x", "s": "2027-01-05T10:00:00Z", "k": value}) is None


def test_unreadable_date_is_a_field_failure():
    with pytest.raises(FieldFailure) as failure:
        mapped(
            {"title": {"selector": "t"}, "start": {"selector": "s"}}, {"t": "x", "s": "soon-ish"}
        )
    assert (failure.value.field, failure.value.msg) == (
        "start",
        "can't read a date or time from 'soon-ish'",
    )


def test_missing_title_names_its_source():
    with pytest.raises(FieldFailure, match="title: selector 't' matched nothing"):
        mapped({"title": {"selector": "t"}, "start": {"selector": "s"}}, {"s": "2027-01-05"})


def test_optional_field_that_matches_nothing_is_none():
    event = mapped(
        {"title": {"selector": "t"}, "start": {"selector": "s"}, "location": {"selector": "l"}},
        {"t": "x", "s": "2027-01-05T10:00:00Z"},
    )
    assert event.location is None and event.end_utc is None
